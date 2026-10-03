"""Custom wake word models, held by Panel Fleet and mirrored on the members.

A Kiosk Satellite leader passes its custom wake word models to every
follower whose profile syncs Voice Satellite (fleet_sync_manager.dart,
_syncWakeModels), and the followers mirror its set: they get what it has,
lose what it does not, and cannot add or delete models of their own. Files
are compared by SHA-256, so an unchanged set costs one small request per
member. The follower's side (remote_manager.dart, fleet token):

  GET    /api/fleet/wake-models              -> {ok, data: {files: {"folder/name": sha256}}}
  PUT    /api/fleet/wake-models?path=f/name  the file as the raw body
  DELETE /api/fleet/wake-models?path=f/name

where folder is microwakeword, openwakeword or vswakeword
(custom_wake_models.dart). A follower writes what arrives straight into
place, unchecked ("the leader already checked it"), so Panel Fleet checks
an upload as far as it can without loading the model: the file names, the
grouping by engine (a microWakeWord manifest needs its .tflite, a vsWakeWord
manifest its .onnx, an openWakeWord model is one .onnx or .tflite), the
manifests, and that a .tflite is a TFLite flatbuffer. It cannot run the
model; add new models to one panel first if in doubt, and compare.

A panel's model files cannot be downloaded through any Kiosk Satellite
endpoint (they live in the app's private storage, outside the file
manager's roots), so the set is uploaded here. What a panel holds can be
compared with it, by checksum.

Mirroring deletes, so it is off until switched on, and never runs with an
empty set: an empty set would clear every member's models.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp

import ks_rules as ks
from jsonfile import read_json, write_json

log = logging.getLogger("panel_fleet.wake")

FOLDERS = ("microwakeword", "openwakeword", "vswakeword")
ENGINE_NAMES = {"microwakeword": "microWakeWord", "openwakeword": "openWakeWord",
                "vswakeword": "vsWakeWord"}
EXTENSIONS = (".json", ".tflite", ".onnx")
MAX_FILE_BYTES = 64 * 1024 * 1024  # custom_wake_models.dart maxFileBytes
VOICE = "Voice Satellite"
FILE_TIMEOUT = aiohttp.ClientTimeout(total=300, sock_connect=10)


class WakeModelError(ValueError):
    pass


def check_name(name):
    """_checkName: a plain file name with one of the three extensions."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise WakeModelError(f"{name or 'A file'} is not a file name.")
    if os.path.splitext(name)[1].lower() not in EXTENSIONS:
        raise WakeModelError(f"{name}: only .json, .tflite and .onnx files are models.")


def _stem(name):
    return os.path.splitext(name)[0]


def _ext(name):
    return os.path.splitext(name)[1].lower()


def _is_tflite(path):
    with open(path, "rb") as f:
        head = f.read(8)
    return len(head) == 8 and head[4:8] == b"TFL3"


def classify(stem, group):
    """_classify, without loading the model: (folder, [paths to keep]) for
    one name's files, or WakeModelError saying what is wrong."""
    js, tflite, onnx = group.get(".json"), group.get(".tflite"), group.get(".onnx")
    if js is not None:
        try:
            manifest = json.loads(Path(js).read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise WakeModelError(f"{stem}.json is not valid JSON.") from e
        if not isinstance(manifest, dict):
            raise WakeModelError(f"{stem}.json is not a manifest.")
        if isinstance(manifest.get("micro"), dict) or manifest.get("type") == "micro":
            if tflite is None:
                raise WakeModelError(f"A microWakeWord model needs {stem}.tflite too.")
            if not _is_tflite(tflite):
                raise WakeModelError(f"{stem}.tflite is not a TFLite model.")
            return "microwakeword", [js, tflite]
        if manifest.get("format") == "vs-wake-word-ctc-v1":
            if onnx is None:
                raise WakeModelError(f"A vsWakeWord model needs {stem}.onnx too.")
            return "vswakeword", [js, onnx]
        raise WakeModelError(f"{stem}.json is neither a microWakeWord nor a vsWakeWord manifest.")
    model = onnx or tflite
    if model is None:
        raise WakeModelError(f"No model file for {stem}.")
    if onnx is not None and tflite is not None:
        raise WakeModelError(f"Add either {stem}.onnx or {stem}.tflite, not both.")
    if tflite is not None and not _is_tflite(tflite):
        raise WakeModelError(f"{stem}.tflite is not a TFLite model.")
    return "openwakeword", [model]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def diff(mine, theirs):
    """What mirroring `mine` onto a member holding `theirs` does: the
    files to send (missing or different) and the ones to remove."""
    return {"send": sorted(k for k, v in mine.items() if theirs.get(k) != v),
            "remove": sorted(k for k in theirs if k not in mine)}


class WakeModels:
    def __init__(self, leader, data_dir):
        self.leader = leader
        self.dir = Path(data_dir) / "wake_models"
        state = read_json(Path(data_dir) / "wake_models.json", {})
        self._state_file = Path(data_dir) / "wake_models.json"
        self.enabled = isinstance(state, dict) and state.get("enabled") is True
        self._hashes = {}  # path -> (size, mtime, sha256)
        self._session = None

    def _save(self):
        write_json(self._state_file, {"enabled": self.enabled})

    def _folder(self, name):
        d = self.dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── The set ───────────────────────────────────────────────────────

    def manifest(self):
        """customWakeModelsManifest: every file with its SHA-256, by
        folder/name."""
        out = {}
        for folder in FOLDERS:
            d = self.dir / folder
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file() or f.name.endswith(".part"):
                    continue
                st = f.stat()
                cached = self._hashes.get(str(f))
                if not cached or cached[:2] != (st.st_size, st.st_mtime_ns):
                    cached = (st.st_size, st.st_mtime_ns, _sha256(f))
                    self._hashes[str(f)] = cached
                out[f"{folder}/{f.name}"] = cached[2]
        return out

    def revision(self, manifest=None):
        return ks.fingerprint(manifest if manifest is not None else self.manifest())

    def models(self):
        """The models, one per engine and name, with their files."""
        out = {}
        for path, sha in self.manifest().items():
            folder, name = path.split("/", 1)
            m = out.setdefault((folder, _stem(name)), {
                "engine": folder, "engineName": ENGINE_NAMES[folder], "id": _stem(name),
                "files": [], "wakeWord": None})
            f = self.dir / folder / name
            m["files"].append({"name": name, "size": f.stat().st_size, "sha256": sha})
            if _ext(name) == ".json":
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    word = data.get("wake_word") if isinstance(data, dict) else None
                    m["wakeWord"] = word if isinstance(word, str) else None
                except (ValueError, OSError, UnicodeDecodeError):
                    pass
        return sorted(out.values(), key=lambda m: (m["id"].lower(), m["engine"]))

    async def stage(self, name, chunks):
        """One uploaded file into the staging folder, to be checked with the
        others of the same upload by commit()."""
        check_name(name)
        staging = self._folder(".staging")
        part = staging / f"{name}.part"
        size = 0
        try:
            with open(part, "wb") as f:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise WakeModelError(f"{name} is larger than 64 MB.")
                    f.write(chunk)
            if size == 0:
                raise WakeModelError(f"{name} arrived empty.")
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, staging / name)

    def commit(self):
        """Check what was staged together, keep each complete model in its
        engine's folder (a model of the same name there replaced whole), and
        clear the staging folder. Answers {added, rejected}."""
        staging = self._folder(".staging")
        by_stem = {}
        for f in staging.iterdir():
            if f.is_file() and not f.name.endswith(".part"):
                by_stem.setdefault(_stem(f.name), {})[_ext(f.name)] = f
        added, rejected = [], []
        for stem, group in sorted(by_stem.items()):
            try:
                folder, keep = classify(stem, group)
            except WakeModelError as e:
                rejected.extend({"file": p.name, "reason": str(e)} for p in group.values())
                continue
            dest = self._folder(folder)
            for old in dest.iterdir():
                if old.is_file() and _stem(old.name) == stem:
                    old.unlink()
            for p in keep:
                os.replace(p, dest / p.name)
            added.append({"engine": folder, "id": stem})
            log.info("custom wake word model %s/%s added", folder, stem)
        shutil.rmtree(staging, ignore_errors=True)
        if added:
            self.leader.schedule_tick()
        return {"added": added, "rejected": rejected}

    def delete(self, folder, stem):
        if folder not in FOLDERS:
            return "No such model"
        d = self.dir / folder
        gone = [f for f in d.iterdir() if f.is_file() and _stem(f.name) == stem] if d.is_dir() else []
        if not gone:
            return "No such model"
        for f in gone:
            f.unlink()
        log.info("custom wake word model %s/%s deleted", folder, stem)
        self.leader.schedule_tick()
        return None

    def set_enabled(self, on):
        if on and not self.manifest():
            return ("Add models first: mirroring an empty set would delete every member's "
                    "custom models.")
        self.enabled = bool(on)
        for m in self.leader.members.values():
            m.wake_revision = None
        self._save()
        log.info("custom wake word models: mirroring %s", "on" if self.enabled else "off")
        self.leader.schedule_tick()
        return None

    # ── The wire ──────────────────────────────────────────────────────

    def syncs(self, m):
        return VOICE in self.leader.profile_for(m)["categories"]

    async def _their_files(self, target, token=None):
        """(files, error) of a panel's custom wake word set: a member's with
        its fleet token, any other panel's through its admin."""
        try:
            if token:
                res = await self.leader._request("GET", f"{target.url}/api/fleet/wake-models",
                                                 token=token)
            else:
                res = await self.leader.admin_request(target, "GET", "/api/fleet/wake-models")
        except LookupError as e:
            return None, str(e)
        if res is None:
            return None, "It did not answer"
        status, body = res
        data = (body or {}).get("data")
        if status in (401, 403):
            return None, "It refused Panel Fleet's credentials"
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("files"), dict):
            # An agent runs no voice, and an older build has no such route.
            return None, "No custom wake word models here (an agent, or a build without them)"
        return {str(k): str(v) for k, v in data["files"].items()}, None

    async def sync_member(self, m):
        """_syncWakeModels: send what is missing or different, remove what
        Panel Fleet does not hold. Only while mirroring is on, the set is not
        empty, and the member's profile syncs Voice Satellite."""
        if not self.enabled or not self.syncs(m):
            return
        mine = self.manifest()
        if not mine:
            return
        revision = self.revision(mine)
        if m.wake_revision == revision:
            return
        token = self.leader.tokens.get(m.id)
        theirs, _ = await self._their_files(m, token)
        if theirs is None:
            return
        plan = diff(mine, theirs)
        for path in plan["send"]:
            status = await self._send(m, token, path)
            if status != 200:
                m.error = f"Could not send the wake word model {path.split('/')[-1]}"
                log.warning("%s: %s (%s)", m.name, m.error, status)
                return
        for path in plan["remove"]:
            res = await self.leader._request(
                "DELETE", f"{m.url}/api/fleet/wake-models?path={quote(path, safe='')}",
                token=token)
            if not res or res[0] != 200:
                log.warning("%s: could not remove the wake word model %s", m.name, path)
        m.wake_revision = revision
        if plan["send"] or plan["remove"]:
            log.info("wake word models in step on %s (%d files: %d sent, %d removed)", m.name,
                     len(mine), len(plan["send"]), len(plan["remove"]))

    async def _send(self, m, token, path):
        folder, name = path.split("/", 1)
        f = self.dir / folder / name
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=FILE_TIMEOUT)
        try:
            with open(f, "rb") as body:
                async with self._session.put(
                        f"{m.url}/api/fleet/wake-models?path={quote(path, safe='')}",
                        data=body, ssl=False,
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/octet-stream"}) as r:
                    await r.read()
                    return r.status
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            log.debug("PUT %s to %s: %s", path, m.name, type(e).__name__)
            return None

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def plan(self, panel_id=None):
        """What mirroring would do on each member (or on one panel, member or
        not), without doing it: {rows: [{id, name, syncs, send, remove,
        same, error}]}."""
        mine = self.manifest()
        targets = []
        if panel_id and panel_id not in self.leader.members:
            dev = self.leader.devices().get(panel_id)
            if not dev or not dev.get("host"):
                return {"rows": [], "error": "That panel is not on the network right now."}
            from leader import Member
            targets.append((Member(panel_id, name=dev.get("name") or "", address=dev["host"],
                                   port=int(dev.get("port") or 2324), tls=bool(dev.get("tls"))),
                            None))
        else:
            for m in self.leader.members.values():
                if panel_id and m.id != panel_id:
                    continue
                if m.id in self.leader.tokens and m.id not in self.leader.invites:
                    targets.append((m, self.leader.tokens[m.id]))

        async def one(m, token):
            theirs, error = await self._their_files(m, token)
            row = {"id": m.id, "name": m.name or m.id,
                   "syncs": token is not None and self.syncs(m), "error": error}
            if theirs is not None:
                d = diff(mine, theirs)
                row.update(send=d["send"], remove=d["remove"],
                           same=len([k for k in mine if theirs.get(k) == mine[k]]),
                           theirs=len(theirs))
            return row

        rows = await asyncio.gather(*(one(m, t) for m, t in targets))
        return {"rows": sorted(rows, key=lambda r: r["name"].lower()), "at": time.time()}

    def view(self):
        models = self.models()
        return {"enabled": self.enabled, "models": models,
                "files": sum(len(m["files"]) for m in models),
                "engines": [{"id": f, "name": ENGINE_NAMES[f]} for f in FOLDERS]}
