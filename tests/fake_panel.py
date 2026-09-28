"""A Kiosk Satellite panel's side of the fleet wire, as a test server.

Written from kiosk-satellite's remote_manager.dart (the routes and the auth
gate) and fleet_sync_manager.dart (receiveInvite, pollInvite, accept,
followerStatus, apply, receiveRoster), independently of ks_rules.py so the
tests check the add-on against the protocol, not against itself.
"""

import hashlib
import json
import secrets

import aiohttp
from aiohttp import web

SECRET_VALUES = {
    "ha.token": "ha-secret-token-value",
    "sendspin.ma_token": "ma-secret-token-value",
}

# /api/settings rows, the shape SettingsManager.describe() serves.
SETTINGS_ROWS = [
    {"key": "ha.url", "type": "string", "title": "Home Assistant URL", "description": "",
     "category": "Home Assistant", "default": "", "value": "http://ha.local:8123", "secret": False},
    {"key": "ha.token", "type": "password", "title": "Token", "description": "",
     "category": "Home Assistant", "default": None, "value": "__set__", "secret": True},
    {"key": "ha.satellite_entity", "type": "string", "title": "Assigned satellite",
     "description": "", "category": "Voice Satellite", "default": "", "value": "x",
     "secret": False, "perDevice": True},
    {"key": "browser.start_url", "type": "string", "title": "Start page", "description": "",
     "category": "Browser", "default": "", "value": "http://ha.local:8123/lovelace/0",
     "secret": False},
    {"key": "browser.zoom", "type": "number", "title": "Zoom", "description": "",
     "category": "Browser", "default": 100, "value": 110, "min": 50, "max": 200, "step": 5,
     "unit": "%", "secret": False},
    {"key": "webcontent.camera", "type": "boolean", "title": "Camera", "description": "",
     "category": "Web Content", "default": False, "value": True, "secret": False},
    {"key": "screensaver.mode", "type": "select", "title": "Mode", "description": "",
     "category": "Screensaver", "default": "clock", "value": "clock",
     "options": ["clock", "black", "plugin:weather:radar"],
     "optionLabels": {"clock": "Clock", "black": "Black", "plugin:weather:radar": "Radar"},
     "secret": False},
    {"key": "screensaver.timeout", "type": "number", "title": "Timeout", "description": "",
     "category": "Screensaver", "default": 300, "value": 600, "secret": False,
     "section": "Timing", "subpage": "Idle"},
    {"key": "sendspin.ma_token", "type": "password", "title": "MA token", "description": "",
     "category": "Sendspin", "default": None, "value": "__set__", "secret": True},
    {"key": "device.name", "type": "string", "title": "Name", "description": "",
     "category": "Device", "default": "", "value": "Office Panel", "secret": False,
     "perDevice": True},
    {"key": "fleet.leader", "type": "boolean", "title": "Lead this fleet", "description": "",
     "category": "Fleet", "default": False, "value": False, "secret": False, "perDevice": True},
    {"key": "plugins.enabled", "type": "boolean", "title": "Enable Plugins", "description": "",
     "category": "Plugins", "default": False, "value": True, "secret": False},
    {"key": "kiosk.enabled", "type": "boolean", "title": "Kiosk mode", "description": "",
     "category": "Kiosk", "default": False, "value": True, "secret": False},
]


def _md5(text):
    return hashlib.md5(text.encode()).hexdigest()


class FakePanel:
    def __init__(self, id="panel-1", name="Office Panel", version="2026.9.87+286",
                 password="admin-pw"):
        self.id, self.name, self.version, self.password = id, name, version, password
        self.leading = False
        self.leader = None       # leaderInfo while following
        self.invite = None       # the invitation waiting on the screen
        self.fleet_tokens = {}   # token -> the leader id it was minted for
        self.admin_tokens = set()
        self.roster = ""
        self.applied_revision = ""
        self.applies, self.rosters, self.invites, self.leaves = [], [], [], []
        self.logins = 0
        self.dirty = False
        self.invite_error = None  # a refusal of the panel's own, verbatim
        self.rows = [dict(r) for r in SETTINGS_ROWS]
        self.values = {r["key"]: r["value"] for r in SETTINGS_ROWS} | SECRET_VALUES

    # What a person does on the panel's screen.
    def accept(self):
        token = secrets.token_hex(16)
        self.fleet_tokens[token] = self.invite["leader"]["id"]
        self.leader = self.invite["leader"]
        self.invite = {**self.invite, "status": "accepted", "token": token}

    def decline(self):
        self.invite = {**self.invite, "status": "declined"}

    def leave(self):
        self.leader = None
        self.roster = ""

    def app(self):
        app = web.Application()
        r = app.router
        r.add_get("/api/fleet/identity", self.identity)
        r.add_post("/api/fleet/invite", self.receive_invite)
        r.add_get("/api/fleet/invite/{nonce}", self.poll_invite)
        r.add_get("/api/fleet/status", self.status)
        r.add_post("/api/fleet/apply", self.apply)
        r.add_post("/api/fleet/roster", self.receive_roster)
        r.add_post("/api/fleet/leave", self.left)
        r.add_post("/api/login", self.login)
        r.add_get("/api/settings", self.settings)
        r.add_get("/api/config/export", self.export)
        return app

    async def identity(self, request):
        return web.json_response({"id": self.id, "name": self.name, "version": self.version,
                                  "leader": self.leading,
                                  "follows": self.leader["name"] if self.leader else None})

    async def receive_invite(self, request):
        if request.headers.get("Origin"):
            return web.json_response({"error": "cross-origin"}, status=403)
        body = await request.json()
        self.invites.append(body)
        if self.leading:
            return web.json_response({"ok": False, "error": "This kiosk leads a fleet of its own"},
                                     status=400)
        if self.invite_error:
            return web.json_response({"ok": False, "error": self.invite_error}, status=400)
        leader = body["leader"]
        # The one callback: the leader at the address the invitation came
        # from must be the one it names.
        url = f"http://{request.remote}:{leader['port']}/api/fleet/identity"
        try:
            async with aiohttp.ClientSession() as s, s.get(url) as res:
                ident = await res.json()
        except aiohttp.ClientError:
            ident = None
        if not ident or ident.get("id") != leader["id"]:
            return web.json_response(
                {"ok": False, "error": "The invitation does not match the kiosk it came from"},
                status=400)
        info = {"id": leader["id"], "name": leader["name"], "version": leader["version"],
                "address": request.remote, "port": leader["port"]}
        if self.leader and self.leader["id"] == leader["id"]:
            token = secrets.token_hex(16)
            self.fleet_tokens[token] = leader["id"]
            return web.json_response({"ok": True, "data": {"token": token}})
        self.invite = {"invite": body["invite"], "leader": info, "status": "pending"}
        return web.json_response({"ok": True, "data": {"pending": True}})

    async def poll_invite(self, request):
        inv = self.invite
        if not inv or inv["invite"] != request.match_info["nonce"]:
            return web.json_response({"status": "unknown"})
        if inv["status"] == "accepted":
            self.invite = None  # handed out once
            return web.json_response({"status": "accepted", "token": inv["token"]})
        if inv["status"] == "declined":
            self.invite = None
            return web.json_response({"status": "declined"})
        return web.json_response({"status": "pending"})

    def _gate(self, request):
        """remote_manager.dart: 401 without a valid token, 403 for a fleet
        token that names someone other than the followed leader."""
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ")
        if token not in self.fleet_tokens:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.leader or self.fleet_tokens[token] != self.leader["id"]:
            return web.json_response({"error": "not this kiosk's leader"}, status=403)
        return None

    async def status(self, request):
        if (refused := self._gate(request)) is not None:
            return refused
        return web.json_response({
            "id": self.id, "name": self.name, "version": self.version,
            "leaderId": self.leader["id"] if self.leader else None,
            "rosterRevision": _md5(self.roster) if self.roster else "",
            "appliedRevision": self.applied_revision or None,
            "dirty": self.dirty, "update": None,
        })

    async def apply(self, request):
        if (refused := self._gate(request)) is not None:
            return refused
        body = await request.json()
        self.applies.append(body)
        if str(body.get("version", "")).split("+")[0] != self.version.split("+")[0]:
            return web.json_response({"ok": True, "data": {"held": "version",
                                                           "version": self.version}})
        self.applied_revision = body["revision"]
        self.dirty = False
        self.values.update(body["settings"])
        return web.json_response({"ok": True, "data": {
            "applied": len(body["settings"]), "received": len(body["settings"]), "skipped": 0,
            "appliedRevision": body["revision"]}})

    async def receive_roster(self, request):
        if (refused := self._gate(request)) is not None:
            return refused
        body = await request.json()
        self.rosters.append(body)
        entries = {}
        for d in body["devices"]:
            if not isinstance(d.get("id"), str) or not isinstance(d.get("port"), int):
                return web.json_response({"ok": False, "error": "Invalid fleet member"}, status=400)
            entry = {"id": d["id"], "name": str(d.get("name") or ""),
                     "version": str(d.get("version") or ""), "address": d["address"],
                     "port": d["port"]}
            if d.get("tls") is True:
                entry["tls"] = True
            if d.get("agent") is True:
                entry["agent"] = True
            entries[d["id"]] = entry
        if self.leader["id"] not in entries:
            return web.json_response(
                {"ok": False, "error": "The roster must include this kiosk's leader"}, status=400)
        self.leader = entries[self.leader["id"]]
        # Re-encoded the way Dart's jsonEncode writes it: compact, UTF-8.
        self.roster = json.dumps([entries[k] for k in sorted(entries)],
                                 separators=(",", ":"), ensure_ascii=False)
        return web.json_response({"ok": True, "data": True})

    async def left(self, request):
        if (refused := self._gate(request)) is not None:
            return refused
        self.leaves.append(True)
        self.leave()
        return web.json_response({"ok": True, "data": True})

    async def login(self, request):
        body = await request.json()
        self.logins += 1
        if body.get("password") != self.password:
            return web.json_response({"error": "invalid password"}, status=401)
        token = secrets.token_hex(8)
        self.admin_tokens.add(token)
        return web.json_response({"token": token})

    def _admin(self, request):
        return request.headers.get("Authorization", "").removeprefix("Bearer ") in self.admin_tokens

    async def settings(self, request):
        if not self._admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"settings": self.rows,
                                  "subpageHints": {"Idle": "When the screensaver starts"}})

    async def export(self, request):
        if not self._admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"kind": "kiosk-satellite-config", "version": 1,
                                  "settings": dict(self.values), "localStorage": "{}"})
