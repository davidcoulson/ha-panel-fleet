"""What the pages and the panels can read over HTTP."""

import aiohttp
import pytest

from fake_panel import SECRET_VALUES, FakePanel
from leader import Leader


@pytest.fixture
async def site(aiohttp_server, aiohttp_client, tmp_path):
    import main

    panel = FakePanel()
    server = await aiohttp_server(panel.app())
    main.fleet.devices.clear()
    main.fleet.devices[f"ks:{panel.id}"] = {
        "key": f"ks:{panel.id}", "kind": "ks", "id": panel.id, "name": panel.name,
        "host": "127.0.0.1", "port": server.port, "tls": False, "version": panel.version,
        "online": True, "agent": False, "misses": 0,
    }
    leader = Leader(tmp_path, fleet_port=0, password=panel.password, version="0.3.0",
                    devices=main.fleet.by_id)
    identity = await aiohttp_server(main.build_fleet_app(leader))
    leader.fleet_port, leader.listening = identity.port, True
    await leader.open()
    async with aiohttp.ClientSession() as session:
        client = await aiohttp_client(main.build_app(session, leader))
        yield panel, leader, client, identity
    await leader.close()
    main.fleet.devices.clear()


async def test_no_page_ever_sees_a_secret(site):
    panel, leader, client, _ = site
    r = await client.post("/api/fleet-settings/import", json={"panel": panel.id})
    assert (await r.json())["ok"] is True
    r = await client.post(f"/api/members/{panel.id}/invite", json={})
    assert (await r.json()) == {"ok": True, "pending": True, "accepted": False,
                                "acceptError": None}
    nonce = leader.invites[panel.id]
    panel.accept()
    await client.post("/api/sync", json={})
    token = leader.tokens[panel.id]
    assert leader.members[panel.id].last_sync_at > 0

    forbidden = [token, nonce, panel.password, *SECRET_VALUES.values()]
    for path in ("/", "/api/devices", "/api/leader", "/api/fleet-settings", "/api/profiles"):
        r = await client.get(path)
        assert r.status == 200, path
        text = await r.text()
        for secret in forbidden:
            assert secret not in text, (path, secret)
    r = await client.post("/api/sync", json={"id": panel.id})
    text = await r.text()
    assert token not in text and nonce not in text

    devices = (await (await client.get("/api/devices")).json())["devices"]
    assert devices[0]["fleet"] == {"state": "member", "text": "In sync", "tone": "ok"}
    status = await (await client.get("/api/leader")).json()
    row = status["members"][0]
    assert row["state"] == "member" and row["status"] == "In sync"
    assert "token" not in row and "invite" not in row


async def test_errors_come_back_as_400(site):
    panel, leader, client, _ = site
    panel.invite_error = "This kiosk leads a fleet of its own"
    r = await client.post(f"/api/members/{panel.id}/invite", json={})
    assert r.status == 400
    assert await r.json() == {"ok": False, "error": "This kiosk leads a fleet of its own"}
    r = await client.post("/api/profiles", json={"profile": {"name": ""}})
    assert r.status == 400


async def test_settings_patch(site):
    panel, leader, client, _ = site
    await client.post("/api/fleet-settings/import", json={"panel": panel.id})
    r = await client.patch("/api/fleet-settings", json={"browser.zoom": 120, "nope": 1})
    body = await r.json()
    assert body["rejected"] == ["nope"]
    assert leader.store["values"]["browser.zoom"] == 120


async def test_the_fleet_port_serves_only_the_identity(site, aiohttp_client):
    _, leader, _, identity = site
    async with aiohttp.ClientSession() as s:
        base = f"http://127.0.0.1:{identity.port}"
        async with s.get(f"{base}/api/fleet/identity") as r:
            assert r.status == 200
            assert await r.json() == {"id": leader.id, "name": "Panel Fleet", "version": "0.3.0",
                                      "leader": True, "follows": None}
        for path in ("/", "/api/devices", "/api/leader", "/api/fleet-settings", "/static/app.css"):
            async with s.get(f"{base}{path}") as r:
                assert r.status == 404, path
        async with s.post(f"{base}/api/fleet/identity") as r:
            assert r.status == 405


async def test_the_page_ships_its_home_assistant_frame_module(site):
    _, _, client, _ = site
    r = await client.get("/static/ha-frame.js")
    assert r.status == 200
    text = await r.text()
    # A temporary style only: never Home Assistant's own sidebar preference.
    assert "panel-fleet-hide-sidebar" in text
    assert "hass-dock-sidebar" not in text and "dockedSidebar =" not in text
    page = await (await client.get("/")).text()
    assert 'id="sideResults"' in page


async def test_an_apk_upload_streams_past_client_max_size(site):
    """The APK is streamed to /data, so a body far past aiohttp's 1 MB
    client_max_size goes through, and the page sees only public facts."""
    from apk_builder import build_apk

    panel, leader, client, _ = site
    data = build_apk(abis=("arm64-v8a",), payload=b"\0" * (3 * 1024 * 1024),
                     version_name="2026.9.88", version_code=290)
    r = await client.post("/api/updates/apk?name=ks-arm64.apk", data=data,
                          headers={"Content-Type": "application/vnd.android.package-archive"})
    body = await r.json()
    assert body["ok"] is True, body
    assert body["apk"]["abis"] == ["arm64-v8a"] and body["apk"]["size"] == len(data)
    view = await (await client.get("/api/updates")).json()
    assert [a["versionName"] for a in view["apks"]] == ["2026.9.88"]
    assert "file" not in view["apks"][0]
    r = await client.post("/api/updates/apk?name=x.apk", data=b"nope")
    assert r.status == 400 and "not an APK" in (await r.json())["error"]
    r = await client.delete(f"/api/updates/apk/{view['apks'][0]['id']}")
    assert (await r.json())["ok"] is True


async def test_wake_models_over_the_page(site):
    _, leader, client, _ = site
    onnx = b"\x08\x07" + b"\0" * 100
    r = await client.post("/api/wake-models/stage?name=computer.onnx", data=onnx)
    assert (await r.json())["ok"] is True
    r = await client.post("/api/wake-models/stage?name=../x.onnx", data=onnx)
    assert r.status == 400
    r = await client.post("/api/wake-models/commit", json={})
    assert (await r.json())["added"] == [{"engine": "openwakeword", "id": "computer"}]
    view = await (await client.get("/api/wake-models")).json()
    assert view["enabled"] is False and view["models"][0]["id"] == "computer"
    r = await client.post("/api/wake-models/enabled", json={"enabled": True})
    assert (await r.json())["ok"] is True and leader.wake.enabled
