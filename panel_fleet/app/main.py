"""Panel Fleet: the Kiosk Satellite wall panels on the network, and their
fleet leader.

Finds Kiosk Satellite panels over mDNS, remembers them, polls each one's
unauthenticated health endpoint, compares its version with the latest
GitHub release and, through Home Assistant, shows the page it is on.

It also leads them as a Kiosk Satellite fleet (leader.py): it invites
panels, keeps the fleet's settings and profiles, and pushes each follower
what its profile allows, the way a panel leading the fleet would. The
followers call back one address on it, GET /api/fleet/identity on
fleet_port, to check an invitation came from the leader it names; that is
the only thing served outside ingress.
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from jsonfile import read_json, write_json
from leader import Leader

log = logging.getLogger("panel_fleet")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATA = Path(os.environ.get("DATA_DIR", "/data"))
STORE = DATA / "devices.json"
HERE = Path(__file__).parent

OPTIONS = read_json(DATA / "options.json", {})
SCAN_INTERVAL = int(OPTIONS.get("scan_interval", 60))
# The panels' remote admin password, for reading the settings definitions
# (Import from panel, Refresh definitions). Nothing else logs in.
PANEL_PASSWORD = OPTIONS.get("panel_password") or ""
FLEET_PORT = int(OPTIONS.get("fleet_port", 2330))

# Home Assistant: the Supervisor proxy inside the add-on, or HA_URL/HA_TOKEN
# when run by hand for development.
if os.environ.get("SUPERVISOR_TOKEN"):
    HA_API = "http://supervisor/core/api"
    HA_TOKEN = os.environ["SUPERVISOR_TOKEN"]
else:
    HA_API = os.environ.get("HA_URL", "").rstrip("/") + "/api" if os.environ.get("HA_URL") else ""
    HA_TOKEN = os.environ.get("HA_TOKEN", "")

SERVICE = "_kiosk-satellite._tcp.local."
RELEASE_REPO = "jxlarrea/kiosk-satellite"

OFFLINE_AFTER = 3  # failed polls in a row before a panel reads offline

# This add-on's own version, baked in by the build (Supervisor's BUILD_VERSION).
ADDON_VERSION = os.environ.get("ADDON_VERSION") or None


# ── Versions ──────────────────────────────────────────────────────────


def version_key(text):
    """The comparable part of a version: 2026.9.74-djc-2026.09.22.01 and
    v2026.9.74 both give (2026, 9, 74). None when there is no number."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def version_status(installed, latest):
    """'current', 'outdated', 'ahead' or 'unknown'."""
    a, b = version_key(installed), version_key(latest)
    if a is None or b is None:
        return "unknown"
    if a == b:
        return "current"
    return "outdated" if a < b else "ahead"


def fork_suffix(version):
    """The part after the upstream version, for a fork build: '-djc-2026.09.22.01'."""
    m = re.match(r"v?\d+(?:\.\d+)*(.*)", version or "")
    return m.group(1) if m else ""


# ── Store ─────────────────────────────────────────────────────────────


class Fleet:
    """The panels discovery has found. Only discovery and polling facts:
    fleet membership, tokens and settings are the leader's, in files of
    their own, so nothing here can carry a secret to a page."""

    def __init__(self):
        self.devices = {}
        self.latest = {}  # "ks" -> {"version", "url", "checked"}
        self.ha_error = None
        self.on_new = None  # called with a newly found panel
        self._load()

    def _load(self):
        saved = read_json(STORE, {})
        # Only Kiosk Satellite panels: 0.3.0 dropped the other kind.
        self.devices = {k: d for k, d in (saved.get("devices") or {}).items()
                        if d.get("kind") == "ks"}
        self.latest = {k: v for k, v in (saved.get("latest") or {}).items() if k == "ks"}
        # Not known until the first poll answers: "checking", not "offline".
        for d in self.devices.values():
            d["online"] = None
            d["misses"] = OFFLINE_AFTER - 1

    def save(self):
        write_json(STORE, {"devices": self.devices, "latest": self.latest})

    def upsert(self, ident, **fields):
        key = f"ks:{ident}"
        now = time.time()
        d = self.devices.get(key)
        if d is None:
            d = self.devices[key] = {
                "key": key,
                "kind": "ks",
                "id": ident,
                "first_seen": now,
                "online": False,
                "misses": 0,
            }
            log.info("found %s at %s", fields.get("name") or ident, fields.get("host"))
            if self.on_new:
                self.on_new(d)
        for k, v in fields.items():
            if v not in (None, ""):
                d[k] = v
        d["announced"] = now
        self.save()
        return d

    def by_id(self):
        """The panels by their Kiosk Satellite id, for the leader."""
        return {d["id"]: d for d in self.devices.values()}


fleet = Fleet()


# ── Discovery ─────────────────────────────────────────────────────────


def _txt(info):
    out = {}
    for k, v in (info.properties or {}).items():
        try:
            out[k.decode()] = v.decode() if isinstance(v, bytes) else (v or "")
        except UnicodeDecodeError:
            continue
    return out


async def _resolve(zc, name):
    info = AsyncServiceInfo(SERVICE, name)
    if not await info.async_request(zc.zeroconf, 3000):
        return
    addresses = info.parsed_addresses(IPVersion.V4Only)
    if not addresses:
        return
    txt = _txt(info)
    instance = name[: -len(SERVICE) - 1] if name.endswith(SERVICE) else name
    ident = txt.get("id") or instance.removeprefix("ks-")
    port = int(txt.get("port") or info.port or 2324)
    # agent=1: a Kiosk Satellite running as a management agent - no
    # dashboard, no voice, no screensaver. tls=1: its admin (and fleet
    # endpoints) answer HTTPS only.
    fleet.upsert(ident, name=txt.get("name"), host=addresses[0], port=port,
                 version=txt.get("version"), hostname=txt.get("host"),
                 agent=txt.get("agent") == "1", tls=txt.get("tls") == "1")


async def discover(zc):
    pending = set()

    def on_change(zeroconf, service_type, name, state_change):
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            task = asyncio.ensure_future(_resolve(zc, name))
            pending.add(task)
            task.add_done_callback(pending.discard)

    return AsyncServiceBrowser(zc.zeroconf, [SERVICE], handlers=[on_change])


# ── Polling ───────────────────────────────────────────────────────────


def _uptime_seconds(value):
    if isinstance(value, dict):
        for k in ("appSeconds", "app", "seconds", "processSeconds"):
            if isinstance(value.get(k), (int, float)):
                return value[k]
    return value if isinstance(value, (int, float)) else None


def _model(brand, model):
    """'Apolosign Electron rk3576_u', but 'rockchip px30_evb', not
    'rockchip rockchip px30_evb'."""
    brand, model = (brand or "").strip(), (model or "").strip()
    if brand and model.lower().startswith(brand.lower()):
        return model
    return " ".join(x for x in (brand, model) if x)


def _gb(n):
    """Bytes as '4.1 GB', the way a panel's own admin writes it."""
    if not isinstance(n, (int, float)):
        return None
    return f"{n / 1_000_000_000:.1f} GB"


def _ks_screen(h):
    s = h.get("screen") or {}
    w, ht = s.get("width"), s.get("height")
    if not (w and ht):
        return None
    out = {"width": w, "height": ht}
    # Older builds (and upstream) answer size alone: infer what they imply
    # rather than leaving the row blank, and take the rest when it is there.
    out["orientation"] = s.get("orientation") or ("portrait" if ht > w else "landscape")
    if isinstance(s.get("density"), (int, float)):
        out["dpi"] = round(s["density"] * 160)
    if isinstance(s.get("rotation"), int):
        out["rotation"] = s["rotation"]
    return out


def _admin_url(d):
    scheme = "https" if d.get("tls") else "http"
    return f"{scheme}://{d['host']}:{d.get('port', 2324)}"


async def _poll_ks(session, d):
    # A panel with HTTPS on serves a self-signed certificate: not verified,
    # as between the panels themselves.
    async with session.get(f"{_admin_url(d)}/api/health", ssl=False) as r:
        r.raise_for_status()
        h = await r.json(content_type=None)
    up = h.get("uptime") if isinstance(h.get("uptime"), dict) else {}
    wv = h.get("webview") or {}
    ram, storage = h.get("ram") or {}, h.get("storage") or {}
    cpu = h.get("cpu") or {}
    return {
        "name": h.get("name"),
        "version": h.get("appVersion"),
        "model": _model(h.get("brand"), h.get("model")),
        "android": h.get("androidVersion"),
        "android_api": h.get("sdkInt"),
        "android_build": h.get("androidBuild"),
        "screen_on": h.get("screenOn"),
        "uptime": _uptime_seconds(h.get("uptime")),
        "uptime_device": up.get("device"),
        "screen": _ks_screen(h),
        "webview": wv.get("version"),
        "webview_package": wv.get("package"),
        "link": h.get("link") or None,
        "ram_text": f"{_gb(ram.get('free'))} free of {_gb(ram.get('total'))}"
        if ram.get("total") else None,
        "storage_text": f"{_gb(storage.get('free'))} free of {_gb(storage.get('total'))}"
        if storage.get("total") else None,
        "cpu_text": f"{round(cpu['usage'])}%" + (f" · {round(cpu['temp'])} °C" if cpu.get("temp") else "")
        if isinstance(cpu.get("usage"), (int, float)) else None,
        "battery": h.get("battery"),
        "host": h.get("ip") or d["host"],
    }


POLL_LOCK = asyncio.Lock()


async def poll_once(session):
    async with POLL_LOCK:
        await _poll_all(session)


async def poll_device(session, d):
    try:
        fields = await _poll_ks(session, d)
        for k, v in fields.items():
            if v not in (None, ""):
                d[k] = v
        d["online"] = True
        d["misses"] = 0
        d["last_seen"] = time.time()
        d.pop("error", None)
    except Exception as e:  # any failure is just "did not answer"
        d["misses"] = d.get("misses", 0) + 1
        d["error"] = type(e).__name__ if not str(e) else str(e)[:160]
        if d["misses"] >= OFFLINE_AFTER:
            d["online"] = False


async def _poll_all(session):
    await asyncio.gather(*(poll_device(session, d) for d in list(fleet.devices.values())))
    await enrich_from_ha(session)
    fleet.save()


async def _first_poll(session, d):
    """A panel just found is polled at once, not at the next interval."""
    try:
        await poll_device(session, d)
        await enrich_from_ha(session)
        fleet.save()
    except Exception:
        log.exception("first poll of %s", d.get("name") or d["id"])


async def poll_loop(session):
    while True:
        try:
            await poll_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("polling the panels failed")
        await asyncio.sleep(SCAN_INTERVAL)


# ── Latest release ────────────────────────────────────────────────────


async def releases_loop(session):
    while True:
        try:
            async with session.get(
                f"https://api.github.com/repos/{RELEASE_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            ) as r:
                r.raise_for_status()
                rel = await r.json()
            fleet.latest["ks"] = {
                "version": rel.get("tag_name", "").lstrip("v"),
                "url": rel.get("html_url"),
                "checked": time.time(),
            }
            fleet.save()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("latest release for %s: %s", RELEASE_REPO, e)
        await asyncio.sleep(6 * 3600)


# ── Home Assistant: what each panel is showing ────────────────────────


TEMPLATE = """
{%- set ns = namespace(out={}) -%}
{%- for s in states.sensor if s.entity_id is match('.*_ipv4_address(_\\d+)?$') -%}
  {%- set dev = device_id(s.entity_id) -%}
  {%- if dev -%}
    {%- set ents = device_entities(dev) -%}
    {%- set page = ents | select('match', '^sensor\\..*_current_page(_\\d+)?$') | list -%}
    {%- set ns.out = dict(ns.out, **{s.state: {
        'url': states(page[0]) if page else '',
        'device': dev,
        'name': device_attr(dev, 'name_by_user') or device_attr(dev, 'name')}}) -%}
  {%- endif -%}
{%- endfor -%}
{{ ns.out | tojson }}
"""


async def enrich_from_ha(session):
    """Match each panel to its ESPHome device by its IPv4 address sensor, and
    read the page it reports showing."""
    if not HA_API or not HA_TOKEN:
        fleet.ha_error = "not connected to Home Assistant"
        return
    try:
        async with session.post(
            f"{HA_API}/template",
            headers={"Authorization": f"Bearer {HA_TOKEN}"},
            json={"template": TEMPLATE},
        ) as r:
            r.raise_for_status()
            by_ip = json.loads(await r.text())
        fleet.ha_error = None
    except Exception as e:
        fleet.ha_error = f"Home Assistant: {e}"[:200]
        return
    for d in fleet.devices.values():
        v = by_ip.get(d.get("host") or "")
        if v:
            url = v.get("url") or ""
            d["dashboard_url"] = url if url.startswith("http") else None
            d["ha_device"] = v.get("device")
            d["ha_name"] = v.get("name")


# ── Web ───────────────────────────────────────────────────────────────


def view(d, leader):
    latest = fleet.latest.get("ks", {}).get("version")
    installed = d.get("version")
    out = {k: v for k, v in d.items() if k not in ("misses",)}
    out["latest"] = latest
    out["version_status"] = version_status(installed, latest)
    out["fork"] = fork_suffix(installed)
    out["admin"] = f"{_admin_url(d)}/" if d.get("host") else None
    dash = d.get("dashboard_url")
    if dash:
        p = urlparse(dash)
        out["dashboard_path"] = (p.path or "/") + (f"#{p.fragment}" if p.fragment else "")
        out["dashboard_href"] = dash
    out["fleet"] = leader.device_fleet(d["id"])
    return out


def _json(data, status=200):
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


async def _body(request):
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def _result(error, ok_data=None):
    if error:
        return _json({"ok": False, "error": error}, status=400)
    return _json({"ok": True, **(ok_data or {})})


async def api_devices(request):
    leader = request.app["leader"]
    leader.viewed()
    items = sorted((view(d, leader) for d in fleet.devices.values()),
                   key=lambda x: (not x.get("online"), (x.get("name") or x["id"]).lower()))
    return _json({
        "devices": items,
        "version": ADDON_VERSION,
        "latest": fleet.latest,
        "ha_error": fleet.ha_error,
        "scan_interval": SCAN_INTERVAL,
        "now": time.time(),
    })


async def api_scan(request):
    # A moment for fresh mDNS answers, then a full poll before answering.
    await asyncio.sleep(1)
    await poll_once(request.app["session"])
    return await api_devices(request)


async def api_forget(request):
    key = request.match_info["key"]
    if fleet.devices.pop(key, None) is not None:
        fleet.save()
        log.info("forgot %s", key)
    return await api_devices(request)


async def api_leader(request):
    leader = request.app["leader"]
    leader.viewed()
    return _json(leader.status_view())


async def api_invite(request):
    body = await _body(request)
    error = await request.app["leader"].invite(request.match_info["id"], body.get("profile"))
    return _result(error)


async def api_remove(request):
    return _result(await request.app["leader"].remove(request.match_info["id"]))


async def api_assign(request):
    body = await _body(request)
    return _result(request.app["leader"].assign_profile(request.match_info["id"],
                                                        body.get("profile")))


async def api_sync(request):
    """Sync now: push to one member, or every member without an id, whether
    or not anything changed."""
    leader = request.app["leader"]
    body = await _body(request)
    await leader.tick(only=body.get("id") or None, force=True)
    return _json(leader.status_view())


async def api_settings(request):
    return _json(request.app["leader"].settings_view())


async def api_settings_patch(request):
    return _json(request.app["leader"].patch_settings(await _body(request)))


async def api_settings_import(request):
    body = await _body(request)
    if not body.get("panel"):
        return _result("Pick the panel to import from.")
    return _result(await request.app["leader"].import_from(body["panel"]))


async def api_settings_refresh(request):
    body = await _body(request)
    return _result(await request.app["leader"].refresh_definitions(body.get("panel") or None))


async def api_profiles(request):
    return _json(request.app["leader"].profiles_view())


async def api_profile_set(request):
    body = await _body(request)
    error, pid = request.app["leader"].set_profile(body.get("profile"))
    return _result(error, {"id": pid})


async def api_profile_delete(request):
    return _result(request.app["leader"].delete_profile(request.match_info["id"]))


async def index(request):
    # Never cached: the sidebar keeps this page in a long-lived frame, so a
    # cached copy outlives several add-on updates and looks like an update
    # that did not take. The static files carry the version in their URL.
    html = (HERE / "index.html").read_text().replace("__V__", ADDON_VERSION or str(STARTED))
    return web.Response(text=html, content_type="text/html",
                        headers={"Cache-Control": "no-store"})


STARTED = int(time.time())


async def _static_headers(request, response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"


# Ingress is the only way in: the Supervisor's proxy address, or anything
# when run by hand.
INGRESS_PEERS = {"172.30.32.2", "127.0.0.1", "::1"}


@web.middleware
async def only_ingress(request, handler):
    if os.environ.get("SUPERVISOR_TOKEN") and request.remote not in INGRESS_PEERS:
        raise web.HTTPForbidden()
    return await handler(request)


def build_app(session, leader):
    """The page and its API, behind ingress."""
    app = web.Application(middlewares=[only_ingress])
    app["session"] = session
    app["leader"] = leader
    app.on_response_prepare.append(_static_headers)
    r = app.router
    r.add_get("/", index)
    r.add_static("/static", HERE / "static")
    r.add_get("/api/devices", api_devices)
    r.add_post("/api/scan", api_scan)
    r.add_delete("/api/devices/{key}", api_forget)
    r.add_get("/api/leader", api_leader)
    r.add_post("/api/sync", api_sync)
    r.add_post("/api/members/{id}/invite", api_invite)
    r.add_delete("/api/members/{id}", api_remove)
    r.add_post("/api/members/{id}/profile", api_assign)
    r.add_get("/api/fleet-settings", api_settings)
    r.add_patch("/api/fleet-settings", api_settings_patch)
    r.add_post("/api/fleet-settings/import", api_settings_import)
    r.add_post("/api/fleet-settings/refresh", api_settings_refresh)
    r.add_get("/api/profiles", api_profiles)
    r.add_post("/api/profiles", api_profile_set)
    r.add_delete("/api/profiles/{id}", api_profile_delete)
    return app


def build_fleet_app(leader):
    """What the panels reach on fleet_port: who this leader is, so a panel
    can check an invitation came from the leader it names. Nothing else;
    every other path is a 404."""
    async def identity(request):
        return web.json_response({"id": leader.id, "name": leader.name,
                                  "version": leader.version, "leader": True, "follows": None})

    app = web.Application()
    app.router.add_get("/api/fleet/identity", identity)
    return app


async def _supervised(name, coro_fn):
    """Run a loop; if it ever falls out, log it and start it again."""
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s stopped; restarting it", name)
        await asyncio.sleep(5)


async def main():
    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    browser = await discover(azc)
    leader = Leader(DATA, fleet_port=FLEET_PORT, password=PANEL_PASSWORD,
                    version=ADDON_VERSION, devices=fleet.by_id)
    await leader.open()
    runners = []
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
            def on_new(d):
                asyncio.ensure_future(_first_poll(session, d))
                # A member back on the network is the moment to look again.
                if d["id"] in leader.members:
                    leader.schedule_tick()
            fleet.on_new = on_new
            # No access log: the page asks twice every fifteen seconds, and
            # the add-on log is for what the fleet did.
            runner = web.AppRunner(build_app(session, leader), access_log=None)
            runners.append(runner)
            await runner.setup()
            port = int(os.environ.get("PORT", 8099))
            await web.TCPSite(runner, "0.0.0.0", port).start()
            fleet_runner = web.AppRunner(build_fleet_app(leader), access_log=None)
            runners.append(fleet_runner)
            await fleet_runner.setup()
            try:
                await web.TCPSite(fleet_runner, "0.0.0.0", FLEET_PORT).start()
                leader.listening = True
            except OSError as e:
                log.error("cannot listen on fleet_port %d (%s): panels cannot accept "
                          "invitations until it is free or fleet_port is changed", FLEET_PORT, e)
            log.info("Panel Fleet on :%d, fleet leader %s on :%d, scanning every %ds",
                     port, leader.id, FLEET_PORT, SCAN_INTERVAL)
            tasks = [asyncio.create_task(_supervised("polling", lambda: poll_loop(session))),
                     asyncio.create_task(_supervised("releases", lambda: releases_loop(session))),
                     asyncio.create_task(_supervised("fleet leader", leader.run))]
            leader.schedule_tick(1)
            await asyncio.gather(*tasks)
    finally:
        for r in reversed(runners):
            await r.cleanup()
        await leader.close()
        await browser.async_cancel()
        await azc.async_close()


if __name__ == "__main__":
    asyncio.run(main())
