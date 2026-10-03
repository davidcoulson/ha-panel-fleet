"""Panel Fleet as the leader of a Kiosk Satellite fleet.

A Kiosk Satellite leader keeps a list of followers and pushes each the
settings its profile allows, over the followers' own fleet endpoints. This
does the same from the add-on, so no wall panel has to lead: it invites a
panel, found by discovery or by its address (which the panel accepts on its
own screen, or Panel Fleet accepts for it through its remote admin with the
panel password), polls each follower, holds a push while the versions
differ, pushes the full set when a follower's applied revision is not the
one it should hold, and shares the member directory. The rules for what travels are in ks_rules.py; this is
the state and the wire. App updates are in updates.py, the custom wake
word models in wake_models.py.

What it keeps, all in /data:
- leader.json: the id the followers know this leader by.
- fleet_settings.json: the settings definitions, as one panel's admin
  served them, and the fleet's values for them.
- profiles.json: the profiles, the Default first.
- members.json: each follower's public facts and its profile.
- secrets.json (0600): the fleet tokens and the invitation nonces. Nothing
  else reads it, and no page ever sees what is in it.
- apks/: the uploaded APKs, one per ABI, and apks.json describing them.
- wake_models/ and wake_models.json: the custom wake word set, and whether
  it is mirrored.
fleet_settings.json is 0600 as well: the fleet's credentials are values.
"""

import asyncio
import ipaddress
import logging
import secrets
import socket
import time
from pathlib import Path

import aiohttp

import ks_rules as ks
from jsonfile import read_json, write_json
from updates import FleetUpdates
from wake_models import WakeModels

log = logging.getLogger("panel_fleet.leader")

# One call to a follower, as long as a Kiosk Satellite leader gives it: a
# panel on the list is on the same network, and past this it is not there.
PUSH_TIMEOUT = aiohttp.ClientTimeout(total=6)
# A login and a full settings read are heavier, and happen by hand.
ADMIN_TIMEOUT = aiohttp.ClientTimeout(total=30)

TICK_EVERY = 30        # seconds between ticks while someone is looking
IDLE_EVERY = 300       # and while nobody is
WATCHED_FOR = 90       # a page read counts as someone looking for this long
BUMP_DELAY = 2         # a change waits this long for the burst to settle

# What a definition keeps in the store: everything the editor draws from,
# never the panel's value (the fleet's is kept beside it).
DEFINITION_FIELDS = (
    "key", "type", "title", "description", "category", "section", "subpage",
    "hidden", "default", "secret", "perDevice", "options", "optionLabels",
    "min", "max", "step", "unit", "placeholder", "multiline", "dependsOn",
    "dependsOnValue", "alsoDependsOn", "alsoDependsOnValue", "notice",
)

SECRET_MASK = "__set__"


def local_address(target):
    """The address this host reaches `target` from: the add-on runs on the
    host network, so it is the one a panel sees and can call back. A UDP
    connect sends nothing; it only picks the route."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _now_ms():
    return int(time.time() * 1000)


class Member:
    """One panel this leader pushes to: what is persisted about it and what
    the last poll learned. Its token and invitation nonce live in the
    secrets file, never here."""

    def __init__(self, id, name="", address="", port=2324, tls=False, version="",
                 profile=None, declined=False, added_at=None, last_sync_at=0, agent=None,
                 abis=None):
        self.id = id
        self.name = name
        self.address = address
        self.port = port
        self.tls = tls
        self.version = version
        self.profile = profile  # None for the Default
        self.declined = declined
        self.added_at = added_at or _now_ms()
        self.last_sync_at = last_sync_at
        # Agent mode: True, False, or None until discovery or the panel's
        # admin says. An agent's screen is never to be woken by a fleet
        # action (see updates.py).
        self.agent = agent
        # Android's supported ABIs, in its preference order, from the
        # panel's admin (/api/info). Empty until read.
        self.abis = list(abis or [])
        # What the last poll learned. Not persisted.
        self.online = False
        self.applied_revision = None
        self.dirty = False
        self.update = None
        self.error = None
        self.roster_revision = None
        # The installer the panel would use (getUpdateInstallerStatus) and
        # when it was read; the custom wake word set it last matched; how
        # much of an APK is on its way to it. Not persisted.
        self.installer = None
        self.installer_at = 0.0
        self.wake_revision = None
        self.sending = None

    @property
    def url(self):
        host = f"[{self.address}]" if ":" in self.address else self.address
        return f"{'https' if self.tls else 'http'}://{host}:{self.port}"

    def to_json(self):
        return {
            "id": self.id, "name": self.name, "address": self.address, "port": self.port,
            "tls": self.tls, "version": self.version, "profile": self.profile,
            "declined": self.declined, "addedAt": self.added_at, "lastSyncAt": self.last_sync_at,
            "agent": self.agent, "abis": self.abis,
        }

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        port = raw.get("port")
        return cls(
            id=str(raw["id"]), name=str(raw.get("name") or ""),
            address=str(raw.get("address") or ""),
            port=int(port) if isinstance(port, (int, float)) else 2324,
            tls=raw.get("tls") is True, version=str(raw.get("version") or ""),
            profile=raw.get("profile") or None, declined=raw.get("declined") is True,
            added_at=raw.get("addedAt"), last_sync_at=int(raw.get("lastSyncAt") or 0),
            agent=raw.get("agent") if isinstance(raw.get("agent"), bool) else None,
            abis=[str(a) for a in raw.get("abis") or [] if isinstance(a, str)],
        )


class Leader:
    def __init__(self, data_dir, *, fleet_port, password, version, devices=None, remember=None):
        self.data = Path(data_dir)
        self.fleet_port = fleet_port
        self.password = password or ""
        # The add-on's version: what the panels are told this leader runs.
        self.version = version or "dev"
        # The Kiosk Satellite panels discovery knows now, by id.
        self.devices = devices or (lambda: {})
        # Called with a kiosk found by its address (Add by IP), so the Panels
        # list polls it like one discovery found.
        self.remember = remember
        self.name = "Panel Fleet"
        self.listening = False
        self.address = None
        self.last_tick = None
        self.watched_until = 0.0
        self._http = None
        self._admin = None
        self._admin_tokens = {}  # panel id -> admin session token, memory only
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._bump = None
        self._last_tick_at = 0.0
        self._load()
        self.updates = FleetUpdates(self, self.data)
        self.wake = WakeModels(self, self.data)

    # ── Files ─────────────────────────────────────────────────────────

    def _load(self):
        ident = read_json(self.data / "leader.json", {})
        self.id = ident.get("id") if isinstance(ident, dict) else None
        if not self.id:
            self.id = secrets.token_hex(8)
            write_json(self.data / "leader.json", {"id": self.id})
        store = read_json(self.data / "fleet_settings.json", {})
        self.store = store if isinstance(store, dict) else {}
        self.store.setdefault("definitions", [])
        self.store.setdefault("values", {})
        self.store.setdefault("subpageHints", {})
        self.profiles = []
        for raw in read_json(self.data / "profiles.json", []) or []:
            p = ks.parse_profile(raw)
            if p and p["id"] and p["id"] != ks.UPDATES_ONLY_ID:
                self.profiles.append(p)
        if not any(p["id"] == ks.DEFAULT_ID for p in self.profiles):
            self.profiles.insert(0, ks.default_profile())
            self._save_profiles()
        self.members = {}
        for raw in read_json(self.data / "members.json", []) or []:
            m = Member.from_json(raw)
            if m:
                self.members[m.id] = m
        sec = read_json(self.data / "secrets.json", {})
        sec = sec if isinstance(sec, dict) else {}
        self.tokens = {k: v for k, v in (sec.get("tokens") or {}).items() if isinstance(v, str) and v}
        self.invites = {k: v for k, v in (sec.get("invites") or {}).items() if isinstance(v, str) and v}

    def _save_store(self):
        # The fleet's credentials are among these values: private too.
        write_json(self.data / "fleet_settings.json", self.store, private=True)

    def _save_profiles(self):
        write_json(self.data / "profiles.json", self.profiles)

    def _save_members(self):
        write_json(self.data / "members.json", [m.to_json() for m in self.members.values()])

    def _save_secrets(self):
        write_json(self.data / "secrets.json", {"tokens": self.tokens, "invites": self.invites},
                   private=True)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def open(self):
        self._http = aiohttp.ClientSession(timeout=PUSH_TIMEOUT)
        self._admin = aiohttp.ClientSession(timeout=ADMIN_TIMEOUT)

    async def close(self):
        await self.updates.stop()
        await self.wake.close()
        for s in (self._http, self._admin):
            if s:
                await s.close()

    def viewed(self):
        """A page read the fleet: tick at the watched cadence for a while."""
        self.watched_until = time.time() + WATCHED_FOR

    def schedule_tick(self, delay=BUMP_DELAY):
        """A tick soon, after the burst a slider or an import makes has
        settled: two triggers in a row share one tick."""
        if self._bump:
            self._bump.cancel()
        try:
            self._bump = asyncio.get_running_loop().call_later(delay, self._wake.set)
        except RuntimeError:  # no loop: tests driving the store directly
            self._bump = None

    async def run(self):
        """The leader's loop: every 30 s while a page is watching, every
        5 min otherwise, and soon after anything changes. One failed tick is
        logged and the next one runs; nothing here ends the loop."""
        while True:
            try:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=TICK_EVERY)
                except asyncio.TimeoutError:
                    pass
                woken = self._wake.is_set()
                self._wake.clear()
                if (woken or time.time() < self.watched_until
                        or time.time() - self._last_tick_at >= IDLE_EVERY):
                    await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fleet tick failed")

    # ── The wire ──────────────────────────────────────────────────────

    async def _request(self, method, url, *, token=None, body=None, session=None):
        """(status, JSON object or None), or None when nothing answered.
        Panel certificates are self-signed and never verified, as between
        Kiosk Satellite panels; the fleet token is what is trusted."""
        session = session or self._http
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            async with session.request(method, url, json=body, headers=headers, ssl=False) as r:
                try:
                    data = await r.json(content_type=None)
                except ValueError:
                    data = None
                return r.status, data if isinstance(data, dict) else None
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            # An invitation's nonce is in its poll URL: never in the log.
            shown = url.split("/api/fleet/invite/")[0] + "/api/fleet/invite/…" \
                if "/api/fleet/invite/" in url else url
            log.debug("%s %s: %s", method, shown, type(e).__name__)
            return None

    # ── Profiles ──────────────────────────────────────────────────────

    def all_profiles(self):
        """The Default, Updates only, then the leader's own."""
        default = next(p for p in self.profiles if p["id"] == ks.DEFAULT_ID)
        rest = [p for p in self.profiles if p["id"] != ks.DEFAULT_ID]
        return [default, ks.updates_only_profile(), *rest]

    def profile_for(self, m):
        """The member's own profile, or the Default when it names none or one
        that was deleted."""
        for p in self.all_profiles():
            if p["id"] == (m.profile or ks.DEFAULT_ID):
                return p
        return self.all_profiles()[0]

    def set_profile(self, raw):
        """Add or change a profile. Answers (error, id)."""
        p = ks.parse_profile(raw)
        if p is None:
            return "A profile needs its categories", None
        name = p["name"].strip()
        if not p["id"]:
            if not name:
                return "A profile needs a name", None
            p["id"] = secrets.token_hex(6)
        if p["id"] == ks.UPDATES_ONLY_ID:
            return "The Updates only profile cannot be changed", None
        if p["id"] == ks.DEFAULT_ID:
            p["name"] = "Default"
        elif not name:
            return "A profile needs a name", None
        else:
            p["name"] = name
        p["categories"] = [c for c in ks.CATEGORY_IDS if c in p["categories"]]
        if any(q["id"] != p["id"] and q["name"].lower() == p["name"].lower()
               for q in self.all_profiles()):
            return f"A profile named {p['name']} exists", None
        for i, q in enumerate(self.profiles):
            if q["id"] == p["id"]:
                self.profiles[i] = p
                break
        else:
            self.profiles.append(p)
        self._save_profiles()
        self.schedule_tick()
        return None, p["id"]

    def delete_profile(self, pid):
        if pid == ks.DEFAULT_ID:
            return "The Default profile stays"
        if pid == ks.UPDATES_ONLY_ID:
            return "The Updates only profile stays"
        before = len(self.profiles)
        self.profiles = [p for p in self.profiles if p["id"] != pid]
        if len(self.profiles) == before:
            return "No such profile"
        for m in self.members.values():
            if m.profile == pid:
                m.profile = None
        self._save_profiles()
        self._save_members()
        self.schedule_tick()
        return None

    def assign_profile(self, member_id, pid):
        m = self.members.get(member_id)
        if m is None:
            return "Not a member"
        if pid and pid != ks.DEFAULT_ID and not any(p["id"] == pid for p in self.all_profiles()):
            return "No such profile"
        m.profile = None if not pid or pid == ks.DEFAULT_ID else pid
        self._save_members()
        self.schedule_tick()
        return None

    # ── What a member should hold ─────────────────────────────────────

    @property
    def store_version(self):
        return self.store.get("version") or ""

    def payload_for(self, m):
        return ks.profile_settings(self.store["definitions"], self.store["values"],
                                   self.profile_for(m))

    def fingerprint_for(self, m):
        return ks.fingerprint(self.payload_for(m))

    def _version_matches(self, m):
        mine = ks.version_name(self.store_version)
        return bool(mine) and ks.version_name(m.version) == mine

    # ── The tick ──────────────────────────────────────────────────────

    async def tick(self, only=None, force=False):
        async with self._lock:
            before = [m.to_json() for m in self.members.values()]
            chosen = [m for m in list(self.members.values()) if only is None or m.id == only]
            # Each member on its own: one that does not answer costs its own
            # timeout, not everyone's.
            results = await asyncio.gather(*(self._sync_member(m, force) for m in chosen),
                                           return_exceptions=True)
            for m, r in zip(chosen, results):
                if isinstance(r, Exception):
                    log.error("syncing %s: %r", m.name or m.id, r)
                    m.error = "Sync failed; see the add-on log"
            if before != [m.to_json() for m in self.members.values()]:
                self._save_members()
            await self._share_roster()
            self.last_tick = time.time()
            self._last_tick_at = self.last_tick
        # Outside the lock: an install streams for minutes and must not hold
        # up the next tick.
        self.updates.after_tick()

    async def _sync_member(self, m, force):
        # Membership survives missing multicast: discovery refreshes the
        # address when it has one, and the saved one is tried otherwise.
        dev = self.devices().get(m.id)
        if dev and dev.get("host"):
            m.address = dev["host"]
            m.port = int(dev.get("port") or m.port)
            m.tls = bool(dev.get("tls"))
            if dev.get("name"):
                m.name = dev["name"]
            if dev.get("version"):
                m.version = dev["version"]
            if isinstance(dev.get("agent"), bool):  # mDNS says; a kiosk added by IP does not
                m.agent = dev["agent"]
        if m.id in self.invites:
            await self._poll_invite(m)
            if m.id not in self.tokens:
                return
        if m.id not in self.tokens:
            m.online = False
            return
        await self._poll_status(m)
        if m.error or m.id not in self.tokens:
            return
        # Keep members on this version: one behind the uploaded APK is
        # queued for it, whatever the settings' version.
        self.updates.note_status(m)
        if not self._version_matches(m):
            return
        if force or m.dirty or m.applied_revision != self.fingerprint_for(m):
            await self._push(m)
        # The custom wake word models travel only to a member in step, as a
        # Kiosk Satellite leader sends them only after its push.
        if not m.error and m.id in self.tokens:
            await self.wake.sync_member(m)

    async def _poll_invite(self, m):
        nonce = self.invites.get(m.id)
        if not nonce:
            return
        res = await self._request("GET", f"{m.url}/api/fleet/invite/{nonce}")
        if not res or res[0] != 200 or res[1] is None:
            m.online = False
            return
        m.online = True
        status = res[1].get("status")
        if status == "accepted":
            token = res[1].get("token")
            if not isinstance(token, str) or not token:
                return
            self.tokens[m.id] = token
            self.invites.pop(m.id, None)
            m.declined = False
            m.applied_revision = None
            self._save_secrets()
            log.info("%s joined the fleet", m.name)
        elif status in ("declined", "unknown"):
            # Unknown: the panel forgot the invitation (a restart past its
            # day, or a newer one replaced it). Either way, waiting is over.
            self.invites.pop(m.id, None)
            m.declined = True
            self._save_secrets()
            log.info("%s declined the invitation", m.name)

    async def _poll_status(self, m):
        m.online = False
        m.roster_revision = None
        res = await self._request("GET", f"{m.url}/api/fleet/status", token=self.tokens[m.id])
        if res is None:
            m.error = "Unreachable"
            return
        status, body = res
        if status in (401, 403):
            # The panel no longer honors the token: it left, or another
            # leader has it now.
            self._drop_token(m)
            log.info("%s no longer follows Panel Fleet", m.name)
            return
        if status != 200 or body is None:
            m.error = "Bad answer"
            return
        # A saved address can be handed to another panel by DHCP.
        if body.get("id") != m.id or body.get("leaderId") != self.id:
            m.error = "The address belongs to a different kiosk or fleet"
            return
        m.error = None
        m.online = True
        rr = body.get("rosterRevision")
        m.roster_revision = rr if isinstance(rr, str) else None
        m.version = str(body.get("version") or m.version)
        m.applied_revision = body.get("appliedRevision")
        m.dirty = body.get("dirty") is True
        m.update = body.get("update") if isinstance(body.get("update"), dict) else None
        if isinstance(body.get("name"), str) and body["name"]:
            m.name = body["name"]

    def _drop_token(self, m):
        self.tokens.pop(m.id, None)
        m.error = None
        m.online = False
        self._save_secrets()

    async def _push(self, m):
        """The full set every time, not a delta: a few hundred values,
        idempotent, and the follower skips what it already holds."""
        settings = self.payload_for(m)
        revision = ks.fingerprint(settings)
        res = await self._request("POST", f"{m.url}/api/fleet/apply", token=self.tokens[m.id],
                                  body={"revision": revision, "version": self.store_version,
                                        "settings": settings})
        if res is None or res[1] is None:
            m.error = "Unreachable"
            return
        status, body = res
        if status in (401, 403):
            self._drop_token(m)
            return
        data = body.get("data")
        if body.get("ok") is not True or not isinstance(data, dict):
            m.error = str(body.get("error") or "The push failed")
            return
        if data.get("held") is not None:
            # Refused for the version: the next poll shows why.
            m.version = str(data.get("version") or m.version)
            return
        m.applied_revision = revision
        m.dirty = False
        m.error = None
        m.last_sync_at = _now_ms()
        log.info("synced %d settings to %s (%s changed)", len(settings), m.name,
                 data.get("applied", 0))

    def roster(self, address=None):
        """The member directory: this leader, then every panel that
        accepted and has not left, sorted by id. The leader is an agent so
        no panel offers it as an intercom peer. `address` is the leader's
        address as the receiving panel reaches it: the host sits on several
        networks, and a panel on the IoT network must be given the address
        on its own network, where replies take the same path back."""
        entries = [ks.directory_entry(self.id, self.name, self.version,
                                      address or self.address or "",
                                      self.fleet_port, agent=True)]
        for m in self.members.values():
            if m.id in self.tokens and m.id not in self.invites and not m.declined:
                entries.append(ks.directory_entry(m.id, m.name, m.version, m.address, m.port,
                                                  tls=m.tls))
        return sorted(entries, key=lambda e: e["id"])

    async def _share_roster(self):
        """Membership travels on its own, whatever the versions: a follower
        that reports a roster revision is sent the list when its revision is
        not this one."""
        target = next((m.address for m in self.members.values() if m.address), None) or next(
            (d.get("host") for d in self.devices().values() if d.get("host")), None)
        self.address = (local_address(target) if target else None) or self.address
        if not self.address:
            return
        for m in list(self.members.values()):
            if m.id not in self.tokens or not m.online or m.roster_revision is None:
                continue
            # The same list for everyone but the leader's own address, which
            # is the one the route to this panel leaves from; so each panel
            # has its own revision.
            devices = self.roster(local_address(m.address) if m.address else None)
            revision = ks.roster_revision(devices)
            if m.roster_revision == revision:
                continue
            res = await self._request("POST", f"{m.url}/api/fleet/roster",
                                      token=self.tokens[m.id], body={"devices": devices})
            if res and res[0] == 200 and res[1] and res[1].get("ok") is True:
                m.roster_revision = revision

    # ── Membership ────────────────────────────────────────────────────

    async def lookup(self, address, port=None):
        """Find a kiosk by its address, for one discovery cannot see (another
        VLAN, no multicast): Kiosk Satellite's own fleetLookup. Its public
        identity over HTTP, then HTTPS, and the same refusals. Answers
        (error, kiosk) without inviting or saving anything."""
        try:
            ip = ipaddress.ip_address(str(address or "").strip())
        except ValueError:
            return "Enter a valid IP address.", None
        if port in (None, ""):
            number = 2324
        else:
            try:
                number = int(str(port).strip())
            except ValueError:
                number = 0
        if not 1 <= number <= 65535:
            return "Enter a port from 1 to 65535.", None
        probe = Member("", address=str(ip), port=number)
        res = await self._request("GET", f"{probe.url}/api/fleet/identity")
        if res is None:
            # A kiosk with HTTPS on answers only that; only this public
            # probe is retried with the other protocol.
            probe.tls = True
            res = await self._request("GET", f"{probe.url}/api/fleet/identity")
        if res is None:
            return "That kiosk did not answer", None
        if res[0] != 200:
            return ("That kiosk runs a build without Fleet Management. It joins once it runs "
                    "one."), None
        ident = res[1] or {}
        if (not isinstance(ident.get("id"), str) or not ident["id"]
                or not isinstance(ident.get("name"), str)
                or not isinstance(ident.get("version"), str)
                or not isinstance(ident.get("leader"), bool)):
            return "That address did not return a valid kiosk identity.", None
        if ident["id"] == self.id:
            return "Pick another kiosk", None
        if ident["id"] in self.tokens or ident["id"] in self.invites:
            return "This kiosk already belongs to this fleet.", None
        if ident["leader"]:
            return "That kiosk leads a fleet.", None
        if ident.get("follows") is not None:
            return "That kiosk already follows another leader.", None
        return None, {"id": ident["id"], "name": ident["name"], "version": ident["version"],
                      "address": probe.address, "port": probe.port, "tls": probe.tls}

    async def invite(self, panel_id, profile=None, address=None, port=None):
        """Invite a panel: one discovery found, a saved member, or the one at
        `address` (found by lookup). The invitation waits on its screen;
        nothing syncs until it is accepted there, or for it with
        accept_remotely. Answers an error or None."""
        if not self.listening:
            return (f"Panel Fleet is not answering on port {self.fleet_port}, so no panel "
                    "could check the invitation. See the add-on log.")
        if profile and profile != ks.DEFAULT_ID and not any(
                p["id"] == profile for p in self.all_profiles()):
            return "No such profile"
        dev = self.devices().get(panel_id) or {}
        saved = self.members.get(panel_id)
        manual = address not in (None, "")
        if manual:
            error, found = await self.lookup(address, port)
            if error:
                return error
            if found["id"] != panel_id:
                return "The address belongs to a different kiosk or fleet"
            probe = Member(panel_id, address=found["address"], port=found["port"],
                           tls=found["tls"])
        elif dev.get("host"):
            probe = Member(panel_id, address=dev["host"], port=int(dev.get("port") or 2324),
                           tls=bool(dev.get("tls")))
        elif saved and saved.address:
            probe = Member(panel_id, address=saved.address, port=saved.port, tls=saved.tls)
        else:
            return "That panel is not on the network right now"
        address = probe.address
        res = await self._request("GET", f"{probe.url}/api/fleet/identity")
        if res is None:
            return "That panel did not answer"
        if res[0] != 200:
            return "That panel runs a build without Fleet Management. It joins once it runs one."
        ident = res[1] or {}
        if (not isinstance(ident.get("id"), str) or not ident["id"]
                or not isinstance(ident.get("name"), str)
                or not isinstance(ident.get("version"), str)
                or not isinstance(ident.get("leader"), bool)):
            return "That address did not return a valid kiosk identity."
        if ident["id"] != panel_id:
            return "The address belongs to a different kiosk or fleet"
        if ident["leader"]:
            return "That panel leads a fleet of its own. Turn off Lead this fleet on it first."
        if ident.get("follows") is not None and saved is None:
            return f"That panel already follows {ident['follows']}. It must leave that fleet first."
        nonce = secrets.token_hex(32)
        res = await self._request("POST", f"{probe.url}/api/fleet/invite", body={
            "invite": nonce,
            "leader": {"id": self.id, "name": self.name, "version": self.version,
                       "port": self.fleet_port},
        })
        if res is None:
            return "That panel did not answer"
        status, body = res
        if status != 200 or not body or body.get("ok") is not True:
            # The panel's own words: "This kiosk leads a fleet of its own".
            return str((body or {}).get("error") or "That panel refused the invitation")
        m = saved or Member(panel_id)
        m.name = ident["name"] or dev.get("name") or address
        m.address, m.port, m.tls = probe.address, probe.port, probe.tls
        m.version = ident["version"]
        m.profile = None if not profile or profile == ks.DEFAULT_ID else profile
        m.declined = False
        m.online = True
        m.error = None
        if isinstance(dev.get("agent"), bool):
            m.agent = dev["agent"]
        data = body.get("data")
        token = data.get("token") if isinstance(data, dict) else None
        if isinstance(token, str) and token:
            # It already trusts this leader: no question on its screen.
            self.tokens[panel_id] = token
            self.invites.pop(panel_id, None)
        else:
            self.tokens.pop(panel_id, None)
            self.invites[panel_id] = nonce
        self.members[panel_id] = m
        self._save_members()
        self._save_secrets()
        log.info("invited %s at %s", m.name, address)
        if manual and not dev and self.remember:
            # Found by its address: the Panels list polls it from now on.
            self.remember({"id": panel_id, "name": m.name, "host": m.address, "port": m.port,
                           "tls": m.tls, "version": m.version})
        self.schedule_tick()
        return None

    async def accept_remotely(self, member_id):
        """Accept the invitation waiting on a panel for it, with the panels'
        admin password: what tapping Accept in its remote admin does
        (fleetAccept, which only an admin session may run, never a fleet
        token). Nothing comes up on the panel's screen, which is the point
        on an agent: a projector must not light up for this. Then the
        token is collected and membership checked. Answers an error or
        None."""
        m = self.members.get(member_id)
        if m is None or member_id not in self.invites:
            return "No invitation of Panel Fleet's is waiting on that panel."
        if not self.password:
            return "Set panel_password in the add-on configuration to accept for the panel."
        # The invitation pending there must be this one: fleetAccept takes
        # whichever is waiting, and another leader's must never be accepted.
        # Polling it by its nonce says so (and collects the token, handed
        # out once, if someone tapped Accept meanwhile).
        await self._poll_invite(m)
        if member_id not in self.tokens:
            if member_id not in self.invites:
                self._save_members()
                return "That panel no longer holds Panel Fleet's invitation. Invite it again."
            if not m.online:
                return f"{m.name or 'The panel'} did not answer."
            try:
                status, body = await self.admin_request(m, "POST", "/api/commands/fleetAccept", {})
            except LookupError as e:
                return str(e)
            if status != 200 or not body or body.get("ok") is not True:
                return f"{m.name or 'The panel'} did not accept: " + str(
                    (body or {}).get("error") or f"it answered {status}")
        if member_id in self.invites:
            await self._poll_invite(m)
        if member_id not in self.tokens:
            return (f"{m.name or 'The panel'} accepted, but has not handed over its fleet token "
                    "yet. It joins at the next check.")
        await self._poll_status(m)
        self._save_members()
        if m.error:
            return f"{m.name or 'The panel'} joined, but its status reads: {m.error}"
        log.info("accepted the invitation on %s for it", m.name)
        self.schedule_tick()
        return None

    async def remove(self, member_id):
        """Take a panel off the list. It keeps its settings; a follower that
        is reached is told to forget this leader."""
        m = self.members.pop(member_id, None)
        if m is None:
            return "Not a member"
        token = self.tokens.pop(member_id, None)
        self.invites.pop(member_id, None)
        self._save_members()
        self._save_secrets()
        if token:
            await self._request("POST", f"{m.url}/api/fleet/leave", token=token, body={})
        log.info("removed %s from the fleet", m.name)
        self.schedule_tick()
        return None

    # ── The settings store ────────────────────────────────────────────

    def _defs_by_key(self):
        return {d["key"]: d for d in self.store["definitions"]}

    async def admin_request(self, target, method, path, body=None):
        """(status, JSON object or None) of an admin endpoint of a panel,
        with the panels' admin password: log in, and log in again once when
        the session has expired. `target` is anything with an id and a url
        (a Member). The session token stays in memory and, like the
        password, is never logged. Raises LookupError with words for the
        page when it cannot."""
        if not self.password:
            raise LookupError("Set panel_password in the add-on configuration first.")
        name = getattr(target, "name", "") or target.address
        for attempt in (0, 1):
            token = self._admin_tokens.get(target.id)
            if not token:
                res = await self._request("POST", f"{target.url}/api/login",
                                          body={"password": self.password}, session=self._admin)
                if res is None:
                    raise LookupError(f"{name} did not answer.")
                if res[0] == 429:
                    raise LookupError(f"Too many failed logins on {name}. Wait a minute.")
                if res[0] != 200 or not (res[1] or {}).get("token"):
                    raise LookupError(f"{name} refused panel_password.")
                token = self._admin_tokens[target.id] = res[1]["token"]
            res = await self._request(method, f"{target.url}{path}", token=token, body=body,
                                      session=self._admin)
            if res and res[0] == 401 and attempt == 0:
                self._admin_tokens.pop(target.id, None)
                continue
            if res is None:
                raise LookupError(f"{name} did not answer.")
            return res
        raise LookupError(f"{name} refused panel_password.")

    async def _admin_json(self, dev, path):
        """GET an admin endpoint of a discovered panel: its JSON, or a
        LookupError."""
        m = Member(dev["id"], name=dev.get("name") or "", address=dev["host"],
                   port=int(dev.get("port") or 2324), tls=bool(dev.get("tls")))
        try:
            status, body = await self.admin_request(m, "GET", path)
        except LookupError as e:
            # The import's own words: the page names the panel already.
            raise LookupError(str(e).replace(m.name or m.address, "That panel", 1)) from None
        if status != 200 or body is None:
            raise LookupError(f"{path} on that panel answered {status}.")
        return body

    async def _read_panel(self, panel_id):
        """The definitions, the version and every value (secrets included,
        from the admin's config export) of one panel."""
        dev = self.devices().get(panel_id)
        if not dev or not dev.get("host"):
            raise LookupError("That panel is not on the network right now.")
        if dev.get("agent"):
            raise LookupError("That panel runs as an agent, whose admin leaves out the "
                              "display and voice settings. Pick a wall panel.")
        m = Member(panel_id, address=dev["host"], port=int(dev.get("port") or 2324),
                   tls=bool(dev.get("tls")))
        res = await self._request("GET", f"{m.url}/api/fleet/identity", session=self._admin)
        ident = (res[1] if res and res[0] == 200 else None) or {}
        if not ident.get("version"):
            raise LookupError("That panel runs a build without Fleet Management.")
        described = await self._admin_json(dev, "/api/settings")
        exported = await self._admin_json(dev, "/api/config/export")
        rows = described.get("settings")
        values = exported.get("settings")
        if not isinstance(rows, list) or not isinstance(values, dict):
            raise LookupError("That panel's settings could not be read.")
        definitions, panel_values = [], {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("key") or not ks.is_syncable_definition(row):
                continue
            d = {k: row[k] for k in DEFINITION_FIELDS if k in row}
            if row["key"] == "screensaver.mode":
                # Plugin screensavers are the source panel's own, and a
                # plugin pick never travels.
                d["options"] = [o for o in d.get("options") or [] if not ks.is_plugin_screensaver(o)]
                d["optionLabels"] = {k: v for k, v in (d.get("optionLabels") or {}).items()
                                     if k in d["options"]}
            definitions.append(d)
            if row["key"] in values:
                panel_values[row["key"]] = values[row["key"]]
            elif not row.get("secret") and "value" in row:
                panel_values[row["key"]] = row["value"]
        return {
            "version": ident["version"], "source": ident.get("name") or dev.get("name") or "",
            "sourceId": panel_id, "definitions": definitions,
            "subpageHints": described.get("subpageHints") or {}, "values": panel_values,
        }

    async def import_from(self, panel_id):
        """Replace the definitions and the fleet's values with one panel's.
        Answers an error or None."""
        try:
            read = await self._read_panel(panel_id)
        except LookupError as e:
            return str(e)
        self.store = {**read, "importedAt": _now_ms()}
        self._save_store()
        log.info("imported %d fleet settings from %s (%s)", len(read["definitions"]),
                 read["source"], read["version"])
        self.schedule_tick()
        return None

    def newest_panel(self):
        """The online, non-agent panel on the newest version."""
        best = None
        for pid, d in self.devices().items():
            if not d.get("host") or d.get("agent") or d.get("online") is False:
                continue
            if best is None or ks.is_newer(d.get("version"), best[1].get("version")):
                best = (pid, d)
        return best[0] if best else None

    async def refresh_definitions(self, panel_id=None):
        """Move the definitions to a newer version, keeping the fleet's
        values: new settings take that panel's value, settings that are gone
        go, and a pick no longer offered takes the panel's."""
        panel_id = panel_id or self.newest_panel()
        if not panel_id:
            return "No online panel to read the definitions from."
        try:
            read = await self._read_panel(panel_id)
        except LookupError as e:
            return str(e)
        old = self.store.get("values") or {}
        values = {}
        for d in read["definitions"]:
            key = d["key"]
            keep = key in old and not (d.get("type") == "select" and d.get("options")
                                       and old[key] not in d["options"])
            if keep:
                values[key] = old[key]
            elif key in read["values"]:
                values[key] = read["values"][key]
        added = len([d for d in read["definitions"] if d["key"] not in old])
        dropped = len([k for k in old if k not in values])
        self.store = {**read, "values": values, "importedAt": _now_ms()}
        self._save_store()
        log.info("definitions now %s from %s: %d new, %d gone", read["version"],
                 read["source"], added, dropped)
        self.schedule_tick()
        return None

    def patch_settings(self, changes):
        """Set fleet values from the editor. Answers the KS PATCH shape:
        {ok, rejected, errors}."""
        by_key = self._defs_by_key()
        rejected, errors = [], {}
        changed = False
        for key, value in (changes or {}).items():
            d = by_key.get(key)
            error = "Not a fleet setting" if d is None else _invalid(d, value)
            if error:
                rejected.append(key)
                errors[key] = error
                continue
            if d.get("secret") and value == "":
                continue  # an untouched secret field keeps the secret
            if isinstance(value, float) and value.is_integer():
                value = int(value)  # a panel keeps a whole number as an int
            if self.store["values"].get(key) != value or key not in self.store["values"]:
                self.store["values"][key] = value
                changed = True
        if changed:
            self._save_store()
            self.schedule_tick()
        return {"ok": not rejected, "rejected": rejected, "errors": errors}

    # ── Views: what a page may see ────────────────────────────────────

    def settings_view(self):
        values = self.store["values"]
        defs = []
        for d in self.store["definitions"]:
            v = values.get(d["key"], d.get("default"))
            if d.get("secret"):
                v = SECRET_MASK if v else ""
            defs.append({**d, "value": v})
        return {
            "version": self.store_version,
            "source": self.store.get("source") or "",
            "sourceId": self.store.get("sourceId") or "",
            "importedAt": self.store.get("importedAt"),
            "definitions": defs,
            "subpageHints": self.store.get("subpageHints") or {},
            "categories": [{"id": c, "title": t, "note": n} for c, t, n in ks.FLEET_SYNC_CATEGORIES],
        }

    def profiles_view(self):
        counts = {}
        for m in self.members.values():
            pid = self.profile_for(m)["id"]
            counts[pid] = counts.get(pid, 0) + 1
        return {
            "profiles": [{**p, "members": counts.get(p["id"], 0),
                          "describe": ks.describe_profile(p),
                          "builtIn": p["id"] in (ks.DEFAULT_ID, ks.UPDATES_ONLY_ID)}
                         for p in self.all_profiles()],
            "categories": [{"id": c, "title": t, "note": n} for c, t, n in ks.FLEET_SYNC_CATEGORIES],
            "credentials": [{"key": k, "title": t} for k, t in ks.FLEET_CREDENTIALS],
            "dashboardKeys": sorted(ks.FLEET_DASHBOARD_KEYS),
            # Every setting a profile can take out: what travels with a
            # category (credentials and the dashboard have their own switches).
            "syncable": [{"key": d["key"], "title": d.get("title") or d["key"],
                          "category": ks.CATEGORY_TITLES.get(ks.fleet_category_of(d), ""),
                          "subpage": d.get("subpage"), "hidden": bool(d.get("hidden"))}
                         for d in self.store["definitions"]
                         if d["key"] not in ks.FLEET_CREDENTIAL_KEYS
                         and d["key"] not in ks.FLEET_DASHBOARD_KEYS],
        }

    def membership(self, m):
        """(state, words) for a member row."""
        if m.declined:
            return "declined", "Declined on the panel"
        if m.id in self.invites:
            return "invited", "Invited – confirm on the panel"
        if m.id not in self.tokens:
            return "left", "Left the fleet"
        return "member", "Member"

    def sync_state(self, m):
        """phaseOf: (phase, words, tone), tone ok, warn or muted."""
        state, _ = self.membership(m)
        if state != "member":
            return state, "—", "muted"
        if not m.online:
            return "offline", "Offline", "muted"
        if m.error:
            return "error", m.error, "warn"
        update = m.update or {}
        if update.get("installing") is True:
            return "updating", "Installing", "muted"
        mine = ks.version_name(self.store_version)
        if not mine:
            return "nostore", "No fleet settings yet: import them from a panel", "warn"
        theirs = ks.version_name(m.version)
        if theirs and theirs != mine:
            if ks.is_newer(m.version, mine):
                return "version", f"Runs {theirs}: refresh the definitions", "warn"
            return "version", f"Needs update to {mine}", "warn"
        if isinstance(update.get("progress"), (int, float)):
            return "updating", f"Downloading {round(update['progress'] * 100)}%", "muted"
        if (not m.dirty and m.applied_revision == self.fingerprint_for(m)
                and m.last_sync_at > 0):
            return "synced", "In sync", "ok"
        return "syncing", "Syncing…", "muted"

    def member_view(self, m):
        """A member as a page sees it: public facts only, built field by
        field so nothing from the secrets file can ride along."""
        state, words = self.membership(m)
        phase, status, tone = self.sync_state(m)
        profile = self.profile_for(m)
        return {
            "id": m.id, "name": m.name, "address": m.address, "port": m.port, "tls": m.tls,
            "version": m.version, "online": m.online, "state": state, "stateText": words,
            "phase": phase, "status": status, "tone": tone,
            "profile": profile["id"], "profileName": profile["name"],
            "lastSyncAt": m.last_sync_at or None, "member": True, "agent": bool(m.agent),
        }

    def status_view(self):
        """The Fleet page: the leader, the store and every Kiosk Satellite
        panel, member or not."""
        rows = {m.id: self.member_view(m) for m in self.members.values()}
        for pid, d in self.devices().items():
            if pid in rows:
                rows[pid]["discovered"] = True
                if isinstance(d.get("agent"), bool):
                    rows[pid]["agent"] = d["agent"]
                rows[pid]["reachable"] = d.get("online")
                continue
            rows[pid] = {
                "id": pid, "name": d.get("name") or pid, "address": d.get("host") or "",
                "port": d.get("port") or 2324, "tls": bool(d.get("tls")),
                "version": d.get("version") or "", "online": d.get("online"),
                "reachable": d.get("online"), "agent": bool(d.get("agent")),
                "state": "none", "stateText": "Not in fleet", "phase": "none", "status": "",
                "tone": "muted", "profile": None, "profileName": None, "lastSyncAt": None,
                "member": False, "discovered": True,
            }
        order = {"member": 0, "invited": 1, "declined": 2, "left": 3, "none": 4}
        return {
            "leader": {"id": self.id, "name": self.name, "version": self.version,
                       "address": self.address, "port": self.fleet_port,
                       "listening": self.listening, "lastTick": self.last_tick},
            "passwordSet": bool(self.password),
            "updatesOnly": ks.UPDATES_ONLY_ID,
            "store": {"version": self.store_version, "source": self.store.get("source") or "",
                      "sourceId": self.store.get("sourceId") or "",
                      "importedAt": self.store.get("importedAt"),
                      "count": len(self.store["definitions"])},
            "newestPanel": self.newest_panel(),
            "profiles": [{"id": p["id"], "name": p["name"]} for p in self.all_profiles()],
            "members": sorted(rows.values(), key=lambda r: (order.get(r["state"], 9),
                                                            (r["name"] or r["id"]).lower())),
        }

    def device_fleet(self, panel_id):
        """The one-line fleet state the Panels table shows for a panel."""
        m = self.members.get(panel_id)
        if m is None:
            return {"state": "none", "text": "Not in fleet"}
        state, words = self.membership(m)
        phase, status, tone = self.sync_state(m)
        return {"state": state, "text": words if state != "member" else status, "tone": tone}


def _invalid(d, value):
    """Why a value does not fit its definition, or None."""
    kind = d.get("type")
    if kind == "boolean":
        return None if isinstance(value, bool) else "Must be on or off"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "Must be a number"
        if d.get("min") is not None and value < d["min"]:
            return f"At least {d['min']}"
        if d.get("max") is not None and value > d["max"]:
            return f"At most {d['max']}"
        return None
    if kind == "select":
        return None if value in (d.get("options") or []) else "Not one of the choices"
    return None if isinstance(value, str) else "Must be text"
