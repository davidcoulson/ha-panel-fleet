"""Panel Fleet: a high-level view of the wall panels on the network.

Finds Kiosk Satellite and ha-paneld panels over mDNS, remembers them, polls
each one's unauthenticated health endpoint, compares its version with the
latest GitHub release and, through Home Assistant, shows the page it is on.
Everything else is a link to the panel's own admin page.
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from html import unescape
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

log = logging.getLogger("panel_fleet")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATA = Path(os.environ.get("DATA_DIR", "/data"))
STORE = DATA / "devices.json"
HERE = Path(__file__).parent


def _options():
    try:
        return json.loads((DATA / "options.json").read_text())
    except (OSError, ValueError):
        return {}


OPTIONS = _options()
SCAN_INTERVAL = int(OPTIONS.get("scan_interval", 60))

# Home Assistant: the Supervisor proxy inside the add-on, or HA_URL/HA_TOKEN
# when run by hand for development.
if os.environ.get("SUPERVISOR_TOKEN"):
    HA_API = "http://supervisor/core/api"
    HA_TOKEN = os.environ["SUPERVISOR_TOKEN"]
else:
    HA_API = os.environ.get("HA_URL", "").rstrip("/") + "/api" if os.environ.get("HA_URL") else ""
    HA_TOKEN = os.environ.get("HA_TOKEN", "")

KINDS = {
    "_kiosk-satellite._tcp.local.": "ks",
    "_ha-paneld._tcp.local.": "paneld",
}

RELEASE_REPOS = {
    "ks": "jxlarrea/kiosk-satellite",
    "paneld": "maxlyth/ha-paneld",
}

OFFLINE_AFTER = 3  # failed polls in a row before a panel reads offline


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
    def __init__(self):
        self.devices = {}
        self.latest = {}  # kind -> {"version", "url", "checked"}
        self.ha_error = None
        self.on_new = None  # called with a newly found panel
        self._load()

    def _load(self):
        try:
            saved = json.loads(STORE.read_text())
            self.devices = saved.get("devices", {})
            self.latest = saved.get("latest", {})
        except (OSError, ValueError):
            pass
        # Not known until the first poll answers: "checking", not "offline".
        for d in self.devices.values():
            d["online"] = None
            d["misses"] = OFFLINE_AFTER - 1

    def save(self):
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"devices": self.devices, "latest": self.latest}, indent=1))
        tmp.replace(STORE)

    def upsert(self, kind, ident, **fields):
        key = f"{kind}:{ident}"
        now = time.time()
        d = self.devices.get(key)
        if d is None:
            d = self.devices[key] = {
                "key": key,
                "kind": kind,
                "id": ident,
                "first_seen": now,
                "online": False,
                "misses": 0,
            }
            log.info("found %s %s at %s", kind, fields.get("name") or ident, fields.get("host"))
            if self.on_new:
                self.on_new(d)
        for k, v in fields.items():
            if v not in (None, ""):
                d[k] = v
        d["announced"] = now
        self.save()
        return d


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


async def _resolve(zc, service_type, name):
    info = AsyncServiceInfo(service_type, name)
    if not await info.async_request(zc.zeroconf, 3000):
        return
    addresses = info.parsed_addresses(IPVersion.V4Only)
    if not addresses:
        return
    txt = _txt(info)
    kind = KINDS[service_type]
    instance = name[: -len(service_type) - 1] if name.endswith(service_type) else name
    if kind == "ks":
        ident = txt.get("id") or instance.removeprefix("ks-")
        port = int(txt.get("port") or info.port or 2324)
        fleet.upsert(kind, ident, name=txt.get("name"), host=addresses[0], port=port,
                     version=txt.get("version"), hostname=txt.get("host"))
    else:
        ident = txt.get("did") or instance
        fleet.upsert(kind, ident, name=txt.get("name") or instance, host=addresses[0],
                     port=info.port or 8888, version=txt.get("ver"))


async def discover(zc):
    pending = set()

    def on_change(zeroconf, service_type, name, state_change):
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            task = asyncio.ensure_future(_resolve(zc, service_type, name))
            pending.add(task)
            task.add_done_callback(pending.discard)

    return AsyncServiceBrowser(zc.zeroconf, list(KINDS), handlers=[on_change])


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


async def _poll_ks(session, d):
    async with session.get(f"http://{d['host']}:{d.get('port', 2324)}/api/health") as r:
        r.raise_for_status()
        h = await r.json(content_type=None)
    return {
        "name": h.get("name"),
        "version": h.get("appVersion"),
        "model": _model(h.get("brand"), h.get("model")),
        "android": h.get("androidVersion"),
        "screen_on": h.get("screenOn"),
        "uptime": _uptime_seconds(h.get("uptime")),
        "host": h.get("ip") or d["host"],
    }


def _cells(html):
    """{label: text} from the <tr><th>label</th><td>text</td></tr> rows that
    ha-paneld's info endpoint serves for its own web UI."""
    out = {}
    for th, td in re.findall(r"<tr><th>(.*?)</th><td[^>]*>(.*?)</td></tr>", html or "", re.S):
        # Drop the row's own links (its edit pencil) before the markup.
        td = re.sub(r"<a\b[^>]*>.*?</a>", "", td, flags=re.S)
        text = re.sub(r"<[^>]+>", "", td).replace("&nbsp;", " ")
        out[re.sub(r"<[^>]+>", "", th).strip()] = unescape(text).strip()
    return out


async def _poll_paneld(session, d):
    base = f"http://{d['host']}:{d.get('port', 8888)}"
    async with session.get(f"{base}/api/v1/health") as r:
        r.raise_for_status()
    out = {}
    try:
        async with session.get(f"{base}/api/v1/info") as r:
            if r.status == 200:
                info = await r.json(content_type=None)
                rows = {}
                for html in (info.get("cards") or {}).values():
                    rows.update(_cells(html))
                android = rows.get("Android", "").split(" (")[0]
                out = {
                    "name": rows.get("Friendly name"),
                    "version": rows.get("ha-paneld", "").split(" (")[0] or None,
                    "model": rows.get("Model") or rows.get("Platform"),
                    "android": f"Android {android}" if android else None,
                    "home_dashboard": rows.get("Home dashboard"),
                    "dashboard_path_now": rows.get("Navigate"),
                }
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        pass
    return out


POLL_LOCK = asyncio.Lock()


async def poll_once(session):
    async with POLL_LOCK:
        await _poll_all(session)


async def poll_device(session, d):
    try:
        fields = await (_poll_ks if d["kind"] == "ks" else _poll_paneld)(session, d)
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
    await poll_device(session, d)
    await enrich_from_ha(session)
    fleet.save()


async def poll_loop(session):
    while True:
        await poll_once(session)
        await asyncio.sleep(SCAN_INTERVAL)


# ── Latest releases ───────────────────────────────────────────────────


async def releases_loop(session):
    while True:
        for kind, repo in RELEASE_REPOS.items():
            try:
                async with session.get(
                    f"https://api.github.com/repos/{repo}/releases/latest",
                    headers={"Accept": "application/vnd.github+json"},
                ) as r:
                    r.raise_for_status()
                    rel = await r.json()
                fleet.latest[kind] = {
                    "version": rel.get("tag_name", "").lstrip("v"),
                    "url": rel.get("html_url"),
                    "checked": time.time(),
                }
            except Exception as e:
                log.warning("latest release for %s: %s", repo, e)
        fleet.save()
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
    """Match each kiosk to its ESPHome device by its IPv4 address sensor, and
    read the page it reports showing. No kiosk password needed."""
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
        if d["kind"] != "ks":
            continue
        v = by_ip.get(d.get("host") or "")
        if v:
            url = v.get("url") or ""
            d["dashboard_url"] = url if url.startswith("http") else None
            d["ha_device"] = v.get("device")
            d["ha_name"] = v.get("name")


# ── Web ───────────────────────────────────────────────────────────────


def view(d):
    latest = fleet.latest.get(d["kind"], {}).get("version")
    installed = d.get("version")
    out = {k: v for k, v in d.items() if k not in ("misses",)}
    out["latest"] = latest
    out["version_status"] = version_status(installed, latest)
    out["fork"] = fork_suffix(installed) if d["kind"] == "ks" else ""
    port = d.get("port") or (2324 if d["kind"] == "ks" else 8888)
    out["admin"] = f"http://{d['host']}:{port}/" if d.get("host") else None
    if d["kind"] == "paneld":
        now_path = d.get("dashboard_path_now")
        home = d.get("home_dashboard") or ""
        # "/" is ha-paneld's own start: the home dashboard, when it names one.
        path = home if now_path in (None, "", "/") and home.startswith("/") else now_path
        if path and path.startswith("/"):
            out["dashboard_path"] = path
            out["dashboard_href"] = path
    dash = d.get("dashboard_url")
    if dash:
        p = urlparse(dash)
        out["dashboard_path"] = (p.path or "/") + (f"#{p.fragment}" if p.fragment else "")
        out["dashboard_href"] = dash
    return out


async def api_devices(request):
    items = sorted((view(d) for d in fleet.devices.values()),
                   key=lambda x: (not x.get("online"), (x.get("name") or x["id"]).lower()))
    return web.json_response({
        "devices": items,
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


async def index(request):
    return web.FileResponse(HERE / "index.html")


# Ingress is the only way in: the Supervisor's proxy address, or anything
# when run by hand.
INGRESS_PEERS = {"172.30.32.2", "127.0.0.1", "::1"}


@web.middleware
async def only_ingress(request, handler):
    if os.environ.get("SUPERVISOR_TOKEN") and request.remote not in INGRESS_PEERS:
        raise web.HTTPForbidden()
    return await handler(request)


async def main():
    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    browser = await discover(azc)
    timeout = aiohttp.ClientTimeout(total=6)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        app = web.Application(middlewares=[only_ingress])
        app["session"] = session
        fleet.on_new = lambda d: asyncio.ensure_future(_first_poll(session, d))
        app.router.add_get("/", index)
        app.router.add_get("/api/devices", api_devices)
        app.router.add_post("/api/scan", api_scan)
        app.router.add_delete("/api/devices/{key}", api_forget)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.environ.get("PORT", 8099))
        await web.TCPSite(runner, "0.0.0.0", port).start()
        log.info("Panel Fleet on :%d, scanning every %ds", port, SCAN_INTERVAL)
        tasks = [asyncio.create_task(poll_loop(session)),
                 asyncio.create_task(releases_loop(session))]
        try:
            await asyncio.gather(*tasks)
        finally:
            await browser.async_cancel()
            await azc.async_close()


if __name__ == "__main__":
    asyncio.run(main())
