"""Fleet updates: an APK uploaded to Panel Fleet, installed on the members.

A Kiosk Satellite leader's "Install on the fleet" (fleet_sync_manager.dart,
installUploadedOnFleet) streams the APK uploaded to it to each online
follower's own upload endpoint, with the follower's fleet token, then asks
that follower to install it:

  POST /api/update/upload             the APK as the raw body (fleet token)
      -> {ok, data: {version, buildNumber, size, path, currentVersion,
                     currentBuild}} or {ok: false, error}
  POST /api/commands/installUploadedApk   {} (fleet token)
      -> {ok: true, data: {...}} once handed to the installer

The follower inspects the file itself (a Kiosk Satellite package, not older
than what it runs, room for two copies) and installs it the way it installs
any update: silently when Android lets it (device owner, Android 12+ as its
own installer of record), through the ADB update helper, or through Shizuku
when "Install updates through Shizuku" is on; otherwise it opens Android's
install confirmation on its screen. A follower already on that build is
skipped.

Panel Fleet does the same with two differences. It holds one APK per ABI
(arm64-v8a for the wall panels, armeabi-v7a for 32-bit boxes, or a
universal one), read out of the file (apk.py), and gives each member the one
its own ABIs take, read from its admin (/api/info, `abis`): Kiosk Satellite
itself never checks the ABI of an uploaded APK, so a wrong one would only
fail at Android's installer. And it never lets an install put anything on
an agent's screen: an agent (a projector, a media box) is checked first with
getUpdateInstallerStatus over its admin, and one that would need Android's
confirmation is skipped as "needs adb/Shizuku" rather than lighting up a
projector in an empty room. The check runs again right before the install,
after the minutes the upload takes.
"""

import asyncio
import hashlib
import logging
import os
import re
import secrets
import time
from pathlib import Path

import aiohttp

import ks_rules as ks
from apk import KNOWN_ABIS, KS_PACKAGE, ApkError, choose_apk, read_apk
from jsonfile import read_json, write_json

log = logging.getLogger("panel_fleet.updates")

MAX_APK_BYTES = 400 * 1024 * 1024
CHUNK = 1024 * 1024
# A release APK is about 100 MB; a wall tablet's Wi-Fi moves that in a
# minute or two. The ceiling is Kiosk Satellite's own (uploadTimeout).
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=15 * 60, sock_connect=10, sock_read=120)
# An installer status older than this is read again before it decides.
INSTALLER_FRESH = 300

AGENT_BLOCKED = "Needs adb/Shizuku: Android would ask on its screen, which an agent's never is"


def build_code(version):
    """The build number after a '+', as a fleet version may carry it."""
    m = re.search(r"\+(\d+)\s*$", version or "")
    return int(m.group(1)) if m else None


def version_numbers(name):
    """Every number of a version name, in order: 2026.10.4-djc-2026.10.02.3
    is (2026, 10, 4, 2026, 10, 2, 3)."""
    return tuple(int(n) for n in re.findall(r"\d+", name or ""))


def silent_install(installer):
    """(silent, how or why not) from getUpdateInstallerStatus, as
    update_manager.dart's _installFile decides: Shizuku when its updates
    are on (it fails rather than asking when Shizuku is down), else
    Android's own silent path, else the ADB update helper, else Android's
    confirmation screen."""
    if not isinstance(installer, dict):
        return False, "unknown"
    if installer.get("shizukuEnabled") is True:
        if installer.get("shizukuReady") is True:
            return True, "Shizuku"
        return False, "Shizuku updates are on, but Shizuku is not running"
    if installer.get("nativeSilent") is True:
        return True, "Android"
    if installer.get("helper") == "ready":
        return True, "the update helper"
    return False, "confirmation"


class FleetUpdates:
    def __init__(self, leader, data_dir):
        self.leader = leader
        self.dir = Path(data_dir) / "apks"
        state = read_json(self.dir / "apks.json", {})
        state = state if isinstance(state, dict) else {}
        self.apks = [a for a in state.get("apks") or []
                     if isinstance(a, dict) and (self.dir / str(a.get("file") or "")).is_file()]
        self.keep = state.get("keep") is True
        self.run = None
        # Each member's last install, from whichever run it was in: a run
        # for one member leaves the others' results standing.
        self.results = {}
        self._task = None
        self._queued = set()
        self._auto_tried = {}  # member id -> sha256 of the APK it was given
        self._session = None

    def _save(self):
        write_json(self.dir / "apks.json", {"apks": self.apks, "keep": self.keep})

    @property
    def running(self):
        return self._task is not None and not self._task.done()

    async def wait(self):
        """Until the install under way, if any, is done."""
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    async def stop(self):
        if self.running:
            self._task.cancel()
            await self.wait()
        if self._session:
            await self._session.close()
            self._session = None

    # ── The APKs ──────────────────────────────────────────────────────

    async def receive(self, chunks, filename=""):
        """Stream an uploaded APK to disk, read it, and keep it as the APK
        for its ABIs. Answers its entry; raises ApkError saying why not."""
        if self.running:
            raise ApkError("A fleet install is under way. Upload when it is done.")
        self.dir.mkdir(parents=True, exist_ok=True)
        part = self.dir / f"upload-{secrets.token_hex(4)}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with open(part, "wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > MAX_APK_BYTES:
                        raise ApkError(f"The file is larger than {MAX_APK_BYTES >> 20} MB.")
                    digest.update(chunk)
                    f.write(chunk)
            if size == 0:
                raise ApkError("The upload was empty.")
            meta = await asyncio.to_thread(read_apk, part)
            if meta["package"] != KS_PACKAGE:
                raise ApkError(f"The APK is {meta['package']}, not Kiosk Satellite ({KS_PACKAGE}).")
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        sha = digest.hexdigest()
        aid = sha[:12]
        dest = self.dir / f"{aid}.apk"
        os.replace(part, dest)
        entry = {"id": aid, "file": dest.name, "name": os.path.basename(filename or "")[:160],
                 "package": meta["package"], "versionName": meta["versionName"],
                 "versionCode": meta["versionCode"], "abis": meta["abis"], "size": size,
                 "sha256": sha, "uploadedAt": int(time.time() * 1000)}
        # One APK per ABI: the new one takes the place of every APK whose
        # ABIs it covers. An APK with no native code covers them all.
        new = set(meta["abis"])
        kept = []
        for a in self.apks:
            covered = a["id"] == aid or not new or (a["abis"] and set(a["abis"]) <= new)
            if covered:
                if a["file"] != dest.name:
                    (self.dir / a["file"]).unlink(missing_ok=True)
            else:
                kept.append(a)
        self.apks = sorted([*kept, entry], key=lambda a: (a["abis"], a["versionCode"]))
        self._save()
        self._auto_tried.clear()
        log.info("stored the APK %s (build %s) for %s, %.1f MB", meta["versionName"],
                 meta["versionCode"], ", ".join(meta["abis"]) or "any ABI", size / 1048576)
        self.leader.schedule_tick()
        return entry

    def delete(self, aid):
        if self.running:
            return "A fleet install is under way."
        a = next((a for a in self.apks if a["id"] == aid), None)
        if a is None:
            return "No such APK"
        (self.dir / a["file"]).unlink(missing_ok=True)
        self.apks.remove(a)
        self._save()
        log.info("removed the APK %s for %s", a["versionName"], ", ".join(a["abis"]) or "any ABI")
        return None

    def set_keep(self, on):
        self.keep = bool(on)
        self._auto_tried.clear()
        self._save()
        log.info("keep members on the uploaded version: %s", "on" if self.keep else "off")
        self.leader.schedule_tick()

    # ── Who gets what ─────────────────────────────────────────────────

    def is_agent(self, m):
        """Discovery's word when it has one; otherwise the member's own,
        and unknown counts as an agent: a screen is never risked."""
        dev = self.leader.devices().get(m.id) or {}
        if isinstance(dev.get("agent"), bool):
            return dev["agent"]
        return m.agent is not False

    def apk_for(self, m):
        """(apk, None) or (None, why not)."""
        if not self.apks:
            return None, "No APK uploaded"
        if m.abis:
            a = choose_apk(self.apks, m.abis)
            return (a, None) if a else (None, f"No uploaded APK runs on {', '.join(m.abis)}")
        # The ABIs are not known: only an APK that runs on all of them will do.
        anywhere = [a for a in self.apks
                    if not a["abis"] or set(KNOWN_ABIS[:2]) <= set(a["abis"])]
        if anywhere:
            return max(anywhere, key=lambda a: a["versionCode"]), None
        if not self.leader.password:
            return None, "Its ABI is unknown: set panel_password so Panel Fleet can read it"
        return None, "Its ABI is not known yet: press Check"

    @staticmethod
    def behind(m, a):
        """Whether a member runs an older build than `a`: True, False, or
        None when that cannot be told. Every number in the version name
        counts, the fork's build stamp included: the fork's builds of one
        release share a versionCode (302 for every 2026.10.4-djc-…), so the
        code cannot tell them apart, and neither can Kiosk Satellite's own
        three-number isNewer."""
        theirs = ks.version_name(m.version)
        if not theirs:
            return None
        if theirs == a["versionName"]:
            return False
        code = build_code(m.version)
        if code is not None and code != a["versionCode"]:
            return code < a["versionCode"]
        x, y = version_numbers(theirs), version_numbers(a["versionName"])
        if x == y:
            return None
        return x < y

    def blocker(self, m):
        """Why a member would not be sent its APK now, or None."""
        if m.id not in self.leader.tokens or m.id in self.leader.invites:
            return "Not a member yet"
        if not m.online:
            return "Offline"
        a, why = self.apk_for(m)
        if a is None:
            return why
        if self.behind(m, a) is False:
            return f"Already on {a['versionName']}"
        if self.is_agent(m):
            if m.installer is None:
                return ("Agent: set panel_password so Panel Fleet can check it installs "
                        "without its screen" if not self.leader.password else
                        "Agent: its installer is not known yet: press Check")
            silent, why = silent_install(m.installer)
            if not silent:
                return AGENT_BLOCKED if why == "confirmation" else f"Agent: {why}"
        return None

    def installer_words(self, m):
        if m.installer is None:
            return None
        silent, how = silent_install(m.installer)
        if silent:
            return f"Installs silently ({how})"
        if how == "confirmation":
            return "No silent installer" if self.is_agent(m) else "Asks for a tap on its screen"
        return how

    # ── Facts from a member's admin ───────────────────────────────────

    async def read_facts(self, m, installer=True):
        """ABIs, agent mode and installer of one member, over its admin with
        the panel password (none of these is open to a fleet token).
        Answers an error or None."""
        try:
            status, info = await self.leader.admin_request(m, "GET", "/api/info")
            abis = (info or {}).get("abis") if status == 200 else None
            if isinstance(abis, list) and all(isinstance(x, str) for x in abis) and abis:
                m.abis = list(abis)
            if m.agent is None and not isinstance(
                    (self.leader.devices().get(m.id) or {}).get("agent"), bool):
                status, body = await self.leader.admin_request(m, "GET", "/api/settings")
                for row in (body or {}).get("settings") or [] if status == 200 else []:
                    if isinstance(row, dict) and row.get("key") == "device.agent_mode":
                        m.agent = row.get("value") is True
            if installer:
                status, body = await self.leader.admin_request(
                    m, "POST", "/api/commands/getUpdateInstallerStatus", {})
                data = (body or {}).get("data") if status == 200 and (body or {}).get("ok") else None
                m.installer = ({k: data.get(k) for k in
                                ("nativeSilent", "shizukuReady", "shizukuEnabled", "helper")}
                               if isinstance(data, dict) else None)
                m.installer_at = time.time()
        except LookupError as e:
            return str(e)
        finally:
            self.leader._save_members()
        return None

    async def check(self):
        """Read every member's state and facts afresh, for the Updates page.
        Answers {member name: error} for the ones that could not be read."""
        members = [m for m in self.leader.members.values()
                   if m.id in self.leader.tokens and m.id not in self.leader.invites]

        async def one(m):
            if m.id not in self.leader.tokens:
                return None
            await self.leader._poll_status(m)
            if not m.online:
                return None
            return await self.read_facts(m)

        results = await asyncio.gather(*(one(m) for m in members), return_exceptions=True)
        out = {}
        for m, r in zip(members, results):
            if isinstance(r, Exception):
                log.error("checking %s: %r", m.name or m.id, r)
                out[m.name or m.id] = "See the add-on log"
            elif r:
                out[m.name or m.id] = r
        return out

    # ── Installing ────────────────────────────────────────────────────

    def start(self, only=None, auto=False):
        """Install on every member (or the ids in `only`), one at a time, in
        the background. Answers an error or None; GET /api/updates rides
        the progress."""
        if self.running:
            return "A fleet install is already under way."
        if not self.apks:
            return "Upload an APK first."
        targets = sorted((m for m in self.leader.members.values()
                          if m.id in self.leader.tokens and m.id not in self.leader.invites
                          and (only is None or m.id in only)),
                         key=lambda m: (m.name or m.id).lower())
        if not targets:
            return "No member to update."
        self.run = {"startedAt": int(time.time() * 1000), "finishedAt": None, "done": False,
                    "auto": auto, "members": [m.id for m in targets]}
        for m in targets:
            self.results[m.id] = {"id": m.id, "name": m.name, "phase": "queued",
                                  "progress": None, "reason": None, "apk": None,
                                  "version": None, "auto": auto}
        self._task = asyncio.create_task(self._run(targets))
        return None

    async def _run(self, targets):
        try:
            for m in targets:
                entry = self.results[m.id]
                try:
                    await self._one(m, entry)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("installing on %s", m.name or m.id)
                    entry.update(phase="failed", reason="See the add-on log")
                finally:
                    m.sending = None
                    entry["progress"] = None
        finally:
            self.run["done"] = True
            self.run["finishedAt"] = int(time.time() * 1000)
            started = [self.results[i]["name"] for i in self.run["members"]
                       if self.results[i]["phase"] == "installing"]
            log.info("%sfleet install done: %d installing (%s)", "keep-on-version " if self.run["auto"]
                     else "", len(started), ", ".join(started) or "none")

    async def _one(self, m, entry):
        # Its state now, not the last tick's.
        if m.id in self.leader.tokens:
            await self.leader._poll_status(m)
        if m.id not in self.leader.tokens:
            entry.update(phase="skipped", reason="No longer follows Panel Fleet")
            return
        # An agent's installer is read afresh every time: whether its helper
        # still runs decides whether anything would show on its screen.
        if m.online and self.leader.password and (
                not m.abis or self.is_agent(m)
                or time.time() - m.installer_at > INSTALLER_FRESH):
            await self.read_facts(m)
        reason = self.blocker(m)
        if reason:
            entry.update(phase="current" if reason.startswith("Already on") else "skipped",
                         reason=reason)
            return
        a, _ = self.apk_for(m)
        entry.update(apk=a["id"], version=a["versionName"], phase="sending", progress=0.0)
        log.info("sending %s (%s) to %s", a["versionName"], ", ".join(a["abis"]) or "any ABI",
                 m.name)
        sent = await self._upload(m, a, entry)
        m.sending = None
        entry["progress"] = None
        if sent is None:
            entry.update(phase="failed", reason="The upload did not get through")
            return
        status, body = sent
        if status in (401, 403):
            entry.update(phase="failed", reason="It no longer honors Panel Fleet's token")
            return
        if not body or body.get("ok") is not True:
            # The follower's own words: older build, not enough space...
            entry.update(phase="skipped",
                         reason=str((body or {}).get("error") or "It did not take the upload"))
            return
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        # Kiosk Satellite's leader skips a follower whose currentBuild is the
        # APK's versionCode. The fork's builds of one release share that
        # code, so here the version name decides; the code only when the
        # follower does not say its version.
        current = data.get("currentVersion")
        if (current == a["versionName"] if isinstance(current, str) and current
                else data.get("currentBuild") == a["versionCode"]):
            entry.update(phase="current", reason=f"Already on {a['versionName']}")
            return
        if self.is_agent(m):
            # The upload took minutes; a helper can stop meanwhile, and then
            # Android would ask on the projector's screen.
            await self.read_facts(m)
            silent, why = silent_install(m.installer)
            if not silent:
                entry.update(phase="skipped",
                             reason=AGENT_BLOCKED if why in ("confirmation", "unknown")
                             else f"Agent: {why}")
                return
        res = await self.leader._request("POST", f"{m.url}/api/commands/installUploadedApk",
                                         token=self.leader.tokens.get(m.id), body={})
        if res and res[0] == 200 and res[1] and res[1].get("ok") is True:
            entry.update(phase="installing", reason=None)
            m.error = None
            m.update = {**(m.update or {}), "installing": True, "lastOutcome": None}
            log.info("%s is installing %s", m.name, a["versionName"])
        else:
            entry.update(phase="failed",
                         reason=str(((res[1] if res else None) or {}).get("error")
                                    or "It did not answer"))

    async def _upload(self, m, a, entry):
        """Stream the APK to the member's upload endpoint with its fleet
        token: (status, JSON or None), or None when it did not answer."""
        path = self.dir / a["file"]
        size = path.stat().st_size

        async def body():
            sent = 0
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK):
                    sent += len(chunk)
                    entry["progress"] = m.sending = sent / size if size else 1.0
                    yield chunk

        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=UPLOAD_TIMEOUT)
        headers = {"Authorization": f"Bearer {self.leader.tokens.get(m.id)}",
                   "Content-Type": "application/vnd.android.package-archive",
                   "Content-Length": str(size)}
        try:
            async with self._session.post(f"{m.url}/api/update/upload", data=body(),
                                          headers=headers, ssl=False) as r:
                try:
                    data = await r.json(content_type=None)
                except ValueError:
                    data = None
                return r.status, data if isinstance(data, dict) else None
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            log.warning("sending the APK to %s failed: %s", m.name, type(e).__name__)
            return None

    # ── Keep members on this version ──────────────────────────────────

    def note_status(self, m):
        """A member just answered its status poll: with Keep members on this
        version on, one behind its APK is queued for it, once per APK."""
        if not self.keep or self.running:
            return
        a, _ = self.apk_for(m)
        if a is None or self.behind(m, a) is not True:
            return
        if self._auto_tried.get(m.id) == a["sha256"]:
            return
        update = m.update or {}
        if update.get("installing") is True or isinstance(update.get("progress"), (int, float)):
            return
        self._auto_tried[m.id] = a["sha256"]
        self._queued.add(m.id)

    def after_tick(self):
        if self._queued and not self.running:
            ids, self._queued = set(self._queued), set()
            names = [self.leader.members[i].name for i in ids if i in self.leader.members]
            log.info("keep members on this version: updating %s", ", ".join(sorted(names)))
            self.start(ids, auto=True)

    # ── What the page sees ────────────────────────────────────────────

    def _row(self, m, entry):
        a, why = self.apk_for(m)
        row = {
            "id": m.id, "name": m.name, "version": m.version, "online": m.online,
            "agent": self.is_agent(m),
            "agentKnown": isinstance((self.leader.devices().get(m.id) or {}).get("agent"), bool)
            or m.agent is not None, "abis": m.abis,
            "apk": {"id": a["id"], "versionName": a["versionName"],
                    "abis": a["abis"]} if a else None,
            "behind": self.behind(m, a) if a else None,
            "installer": self.installer_words(m), "blocker": self.blocker(m),
            "phase": None, "progress": None, "reason": None,
        }
        if entry:
            row.update(phase=entry["phase"], progress=entry["progress"], reason=entry["reason"])
            if entry["phase"] == "installing":
                outcome = (m.update or {}).get("lastOutcome")
                if ks.version_name(m.version) == entry["version"]:
                    row.update(phase="updated", reason=f"Now on {entry['version']}")
                elif outcome == "confirm":
                    row["reason"] = "Waiting for Install to be tapped on its screen"
                elif outcome == "cancelled":
                    row.update(phase="failed", reason="The install was declined on its screen")
                elif outcome == "failed":
                    row.update(phase="failed", reason="The install failed on the panel; see its log")
        return row

    def view(self):
        run = self.run or {}
        entries = self.results
        members = [m for m in self.leader.members.values()
                   if m.id in self.leader.tokens and m.id not in self.leader.invites]
        rows = sorted((self._row(m, entries.get(m.id)) for m in members),
                      key=lambda r: (r["name"] or r["id"]).lower())
        versions = sorted({a["versionName"] for a in self.apks})
        return {
            "apks": [{k: a[k] for k in ("id", "name", "versionName", "versionCode", "abis",
                                        "size", "sha256", "uploadedAt")} for a in self.apks],
            "mixedVersions": len(versions) > 1,
            "keep": self.keep,
            "running": self.running,
            "run": {"startedAt": run.get("startedAt"), "finishedAt": run.get("finishedAt"),
                    "done": run.get("done"), "auto": run.get("auto")} if run else None,
            "members": rows,
            "passwordSet": bool(self.leader.password),
        }
