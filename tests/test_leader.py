"""The leader against a fake Kiosk Satellite panel, over real HTTP."""

import json
import stat

import pytest

import ks_rules as ks
from fake_panel import SECRET_VALUES, FakePanel
from leader import Leader


@pytest.fixture
async def rig(aiohttp_server, tmp_path):
    """A panel, and a leader whose identity site the panel can call back."""
    import main  # noqa: F401  (after conftest has set DATA_DIR)

    panel = FakePanel()
    server = await aiohttp_server(panel.app())
    devices = {panel.id: {"id": panel.id, "host": "127.0.0.1", "port": server.port,
                          "tls": False, "version": panel.version, "name": panel.name,
                          "online": True, "agent": False}}
    leader = Leader(tmp_path, fleet_port=0, password=panel.password, version="0.3.0",
                    devices=lambda: devices)
    identity = await aiohttp_server(main.build_fleet_app(leader))
    leader.fleet_port = identity.port
    leader.listening = True
    await leader.open()
    yield panel, leader, devices
    await leader.close()


async def join(panel, leader):
    assert await leader.import_from(panel.id) is None
    assert await leader.invite(panel.id) is None
    panel.accept()
    await leader.tick()


async def test_invite_accept_push_and_roster(rig):
    panel, leader, _ = rig
    assert await leader.import_from(panel.id) is None
    assert await leader.invite(panel.id) is None
    # The panel checked the invitation against the identity site.
    assert panel.invite["status"] == "pending"
    assert panel.invites[0]["leader"] == {"id": leader.id, "name": "Panel Fleet",
                                          "version": "0.3.0", "port": leader.fleet_port}
    m = leader.members[panel.id]
    assert leader.membership(m)[0] == "invited"

    await leader.tick()  # nobody has tapped yet
    assert leader.membership(m)[0] == "invited"
    assert panel.applies == []

    panel.accept()
    await leader.tick()
    assert leader.membership(m)[0] == "member"
    assert len(panel.applies) == 1
    push = panel.applies[0]
    settings = leader.payload_for(m)
    assert push["settings"] == settings
    assert push["revision"] == ks.fingerprint(settings)
    assert push["version"] == "2026.9.87+286"
    assert "ha.satellite_entity" not in settings and "device.name" not in settings
    assert "ha.token" not in settings  # not in the Default's credentials
    assert settings["sendspin.ma_token"] == SECRET_VALUES["sendspin.ma_token"]
    assert leader.sync_state(m)[0] == "synced"

    # The roster: the leader as an agent on its identity port, then the panel.
    assert len(panel.rosters) == 1
    devices = panel.rosters[0]["devices"]
    assert [d["id"] for d in devices] == sorted([leader.id, panel.id])
    me = next(d for d in devices if d["id"] == leader.id)
    assert me == {"id": leader.id, "name": "Panel Fleet", "version": "0.3.0",
                  "address": "127.0.0.1", "port": leader.fleet_port, "agent": True}
    assert "token" not in json.dumps(panel.rosters)

    # Nothing changed: the next tick neither pushes nor resends the roster.
    await leader.tick()
    assert len(panel.applies) == 1
    assert len(panel.rosters) == 1

    # A fleet setting changed: exactly this follower is pushed again.
    assert leader.patch_settings({"kiosk.enabled": False})["ok"]
    await leader.tick()
    assert len(panel.applies) == 2
    assert panel.values["kiosk.enabled"] is False

    # Drift on the panel (a synced setting changed there) is pushed back.
    panel.dirty = True
    await leader.tick()
    assert len(panel.applies) == 3


async def test_decline(rig):
    panel, leader, _ = rig
    assert await leader.invite(panel.id) is None
    panel.decline()
    await leader.tick()
    m = leader.members[panel.id]
    assert leader.membership(m) == ("declined", "Declined on the panel")
    assert panel.id not in leader.invites and panel.id not in leader.tokens


async def test_invite_refusals_are_the_panels_own_words(rig):
    panel, leader, _ = rig
    panel.invite_error = "This kiosk is not set up for a fleet"
    assert await leader.invite(panel.id) == "This kiosk is not set up for a fleet"
    assert panel.id not in leader.members
    panel.invite_error = None
    panel.leading = True  # its identity says so before any invitation
    assert "leads a fleet" in await leader.invite(panel.id)
    leader.listening = False
    assert "not answering on port" in await leader.invite(panel.id)


async def test_an_invitation_the_panel_cannot_verify_is_refused(rig):
    panel, leader, _ = rig
    leader.fleet_port = 1  # nothing answers there
    error = await leader.invite(panel.id)
    assert error == "The invitation does not match the kiosk it came from"


async def test_version_gate(rig):
    panel, leader, devices = rig
    await join(panel, leader)
    assert len(panel.applies) == 1
    m = leader.members[panel.id]
    # The panel moved on: nothing is pushed until the definitions follow.
    panel.version = devices[panel.id]["version"] = "2026.9.88+300"
    leader.patch_settings({"kiosk.enabled": False})
    await leader.tick()
    assert len(panel.applies) == 1
    assert leader.sync_state(m) == ("version", "Runs 2026.9.88: refresh the definitions", "warn")
    # A panel behind the store needs an update.
    panel.version = devices[panel.id]["version"] = "2026.9.86"
    await leader.tick()
    assert leader.sync_state(m) == ("version", "Needs update to 2026.9.87", "warn")
    assert len(panel.applies) == 1
    # Same release, another build number: in step again.
    panel.version = devices[panel.id]["version"] = "2026.9.87+290"
    await leader.tick()
    assert len(panel.applies) == 2
    assert leader.sync_state(m)[0] == "synced"


async def test_a_panel_that_left_reads_left(rig):
    panel, leader, _ = rig
    await join(panel, leader)
    panel.leave()  # Leave the fleet, on the panel
    await leader.tick()
    m = leader.members[panel.id]
    assert leader.membership(m)[0] == "left"
    assert panel.id not in leader.tokens


async def test_remove_tells_the_panel(rig):
    panel, leader, _ = rig
    await join(panel, leader)
    assert await leader.remove(panel.id) is None
    assert panel.leaves == [True]
    assert panel.leader is None
    assert panel.id not in leader.members and panel.id not in leader.tokens


async def test_import_keeps_syncable_definitions_and_real_secrets(rig):
    panel, leader, _ = rig
    assert await leader.import_from(panel.id) is None
    keys = [d["key"] for d in leader.store["definitions"]]
    assert keys == ["ha.url", "ha.token", "browser.start_url", "browser.zoom",
                    "webcontent.camera", "screensaver.mode", "screensaver.timeout",
                    "sendspin.ma_token", "kiosk.enabled"]
    assert leader.store["values"]["ha.token"] == SECRET_VALUES["ha.token"]
    assert all("value" not in d for d in leader.store["definitions"])
    mode = next(d for d in leader.store["definitions"] if d["key"] == "screensaver.mode")
    assert mode["options"] == ["clock", "black"]
    assert leader.store["version"] == "2026.9.87+286"
    assert leader.store["source"] == "Office Panel"

    view = leader.settings_view()
    token = next(d for d in view["definitions"] if d["key"] == "ha.token")
    assert token["value"] == "__set__"
    assert SECRET_VALUES["ha.token"] not in json.dumps(view)

    # An untouched secret field keeps the secret; a typed one replaces it.
    assert leader.patch_settings({"ha.token": ""})["ok"]
    assert leader.store["values"]["ha.token"] == SECRET_VALUES["ha.token"]
    assert leader.patch_settings({"ha.token": "new"})["ok"]
    assert leader.store["values"]["ha.token"] == "new"
    bad = leader.patch_settings({"browser.zoom": 900, "kiosk.enabled": "yes",
                                 "screensaver.mode": "plugin:weather:radar", "device.name": "x"})
    assert sorted(bad["rejected"]) == ["browser.zoom", "device.name", "kiosk.enabled",
                                       "screensaver.mode"]
    assert leader.patch_settings({"browser.zoom": 150.0})["ok"]
    assert leader.store["values"]["browser.zoom"] == 150
    assert isinstance(leader.store["values"]["browser.zoom"], int)


async def test_refresh_keeps_values_and_follows_the_definitions(rig):
    panel, leader, devices = rig
    assert await leader.import_from(panel.id) is None
    leader.patch_settings({"browser.zoom": 150})
    panel.version = devices[panel.id]["version"] = "2026.9.88"
    panel.rows = [r for r in panel.rows if r["key"] != "kiosk.enabled"] + [
        {"key": "lockdown.enabled", "type": "boolean", "title": "Lockdown", "description": "",
         "category": "Lockdown", "default": False, "value": True, "secret": False}]
    panel.values["lockdown.enabled"] = True
    # An expired admin session is logged in again.
    panel.admin_tokens.clear()
    logins = panel.logins
    assert await leader.refresh_definitions() is None
    assert panel.logins == logins + 1
    assert leader.store["version"] == "2026.9.88"
    assert leader.store["values"]["browser.zoom"] == 150
    assert "kiosk.enabled" not in leader.store["values"]
    assert leader.store["values"]["lockdown.enabled"] is True


async def test_import_needs_the_password(rig):
    panel, leader, _ = rig
    leader.password = "wrong"
    assert await leader.import_from(panel.id) == "That panel refused panel_password."
    leader.password = ""
    assert "panel_password" in await leader.import_from(panel.id)


async def test_tokens_live_only_in_a_private_secrets_file(rig, tmp_path):
    panel, leader, _ = rig
    await join(panel, leader)
    token = leader.tokens[panel.id]
    secrets_file = tmp_path / "secrets.json"
    assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "fleet_settings.json").stat().st_mode) == 0o600
    for name in ("members.json", "profiles.json", "fleet_settings.json", "leader.json"):
        assert token not in (tmp_path / name).read_text()
    # A new leader over the same files still leads the same fleet.
    again = Leader(tmp_path, fleet_port=leader.fleet_port, password="", version="0.3.0")
    assert again.id == leader.id and again.tokens[panel.id] == token


async def test_profiles(rig):
    panel, leader, _ = rig
    await join(panel, leader)
    error, pid = leader.set_profile({"name": "Hallway", "categories": ["Kiosk"]})
    assert error is None
    assert leader.set_profile({"name": "hallway", "categories": []})[0] == \
        "A profile named hallway exists"
    assert leader.set_profile({"id": "updates-only", "name": "x", "categories": []})[0]
    assert leader.assign_profile(panel.id, pid) is None
    m = leader.members[panel.id]
    assert leader.payload_for(m) == {"kiosk.enabled": True}
    await leader.tick()
    assert panel.applies[-1]["settings"] == {"kiosk.enabled": True}
    assert leader.delete_profile(pid) is None
    assert leader.profile_for(m)["id"] == "default"
    assert leader.delete_profile("default") == "The Default profile stays"
    assert leader.assign_profile(panel.id, "updates-only") is None
    assert leader.payload_for(m) == {}


async def test_each_panel_is_given_the_leader_address_it_reaches(rig, monkeypatch):
    """The host is on several networks and replies follow the default route,
    so a panel is told the address the route to it leaves from: the IoT
    address for a panel on the IoT network, the main one for the rest."""
    import leader as leader_mod

    panel, leader, _ = rig
    monkeypatch.setattr(leader_mod, "local_address",
                        lambda target: "10.2.4.6" if target == "127.0.0.1" else "10.2.3.6")
    await join(panel, leader)
    me = next(d for d in panel.rosters[-1]["devices"] if d["id"] == leader.id)
    assert me["address"] == "10.2.4.6"
    assert leader.roster("10.2.3.6") != leader.roster("10.2.4.6")
