"""Add by IP, and accepting an invitation for a panel through its admin."""

import logging

import aiohttp
import pytest

from fake_panel import FakePanel
from rig import make_rig, panel_pair


@pytest.fixture
async def rig(aiohttp_server, tmp_path):
    panel, projector = panel_pair()
    # The projector sits on another VLAN: discovery never sees it.
    async with make_rig(aiohttp_server, tmp_path,
                        [(panel, True, False), (projector, False, True)]) as r:
        assert await r.leader.import_from(panel.id) is None
        yield r


async def test_lookup_by_address(rig):
    leader = rig.leader
    _, projector = rig.panels
    assert await leader.lookup("projector.lan") == ("Enter a valid IP address.", None)
    assert (await leader.lookup("127.0.0.1", "70000"))[0] == "Enter a port from 1 to 65535."
    error, kiosk = await leader.lookup("127.0.0.1", projector.port)
    assert error is None
    assert kiosk == {"id": projector.id, "name": "Aurora Projector",
                     "version": projector.version, "address": "127.0.0.1",
                     "port": projector.port, "tls": False}
    projector.leading = True
    assert (await leader.lookup("127.0.0.1", projector.port))[0] == "That kiosk leads a fleet."


async def test_lookup_of_nothing(rig, unused_tcp_port):
    assert (await rig.leader.lookup("127.0.0.1", unused_tcp_port))[0] == \
        "That kiosk did not answer"


async def test_invite_by_address_and_accept_for_it(rig, caplog):
    leader = rig.leader
    _, projector = rig.panels
    caplog.set_level(logging.DEBUG)
    # Another kiosk at that address is not the one asked for.
    assert await leader.invite("someone-else", address="127.0.0.1", port=projector.port) == \
        "The address belongs to a different kiosk or fleet"
    assert await leader.invite(projector.id, "updates-only", address="127.0.0.1",
                               port=projector.port) is None
    m = leader.members[projector.id]
    assert (m.address, m.port, m.profile) == ("127.0.0.1", projector.port, "updates-only")
    assert projector.invite["status"] == "pending"
    # Remembered, so the Panels list polls it.
    assert rig.remembered[-1]["id"] == projector.id
    assert rig.remembered[-1]["host"] == "127.0.0.1"

    assert await leader.accept_remotely(projector.id) is None
    # fleetAccept ran under an admin session, never a fleet token.
    assert ("fleetAccept", "admin") in projector.commands
    assert leader.membership(m)[0] == "member"
    assert projector.leader["id"] == leader.id
    # Agent mode is learned from its admin, since mDNS never said.
    await leader.updates.check()
    assert m.agent is True
    # A member already: looking it up again says so.
    assert (await leader.lookup("127.0.0.1", projector.port))[0] == \
        "This kiosk already belongs to this fleet."
    # The first sync reaches it at its saved address.
    await leader.tick()
    assert projector.applies and projector.applies[-1]["settings"] == {}

    for secret in [projector.password, *leader.tokens.values(), *leader._admin_tokens.values(),
                   *leader.invites.values()]:
        assert secret not in caplog.text


async def test_accept_needs_the_right_password(rig):
    leader = rig.leader
    panel, _ = rig.panels
    assert await leader.invite(panel.id) is None
    leader.password = "wrong"
    leader._admin_tokens.clear()  # no session left from the import
    error = await leader.accept_remotely(panel.id)
    assert error == "Office Panel refused panel_password."
    assert leader.membership(leader.members[panel.id])[0] == "invited"
    assert not any(c[0] == "fleetAccept" for c in panel.commands)
    leader.password = ""
    assert "panel_password" in await leader.accept_remotely(panel.id)


async def test_another_leaders_invitation_is_never_accepted(rig):
    leader = rig.leader
    panel, _ = rig.panels
    assert await leader.invite(panel.id) is None
    # Another leader's invitation replaced ours on the panel.
    panel.invite = {"invite": "someone-elses", "status": "pending",
                    "leader": {"id": "other-leader", "name": "Other", "version": "1",
                               "address": "10.0.0.9", "port": 2324}}
    error = await leader.accept_remotely(panel.id)
    assert error == "That panel no longer holds Panel Fleet's invitation. Invite it again."
    assert not any(c[0] == "fleetAccept" for c in panel.commands)
    assert panel.invite["status"] == "pending" and panel.leader is None


async def test_accepted_on_the_screen_meanwhile(rig):
    leader = rig.leader
    panel, _ = rig.panels
    assert await leader.invite(panel.id) is None
    panel.accept()  # someone tapped Accept before Panel Fleet got to it
    assert await leader.accept_remotely(panel.id) is None
    assert not any(c[0] == "fleetAccept" for c in panel.commands)
    assert leader.membership(leader.members[panel.id])[0] == "member"


async def test_a_fleet_token_cannot_accept(rig):
    """What the fake enforces, as remote_manager.dart does: fleetAccept is
    outside a fleet token's scope, so it must go through the admin."""
    leader = rig.leader
    panel, _ = rig.panels
    assert await leader.invite(panel.id) is None
    panel.accept()
    await leader.tick()
    token = leader.tokens[panel.id]
    async with aiohttp.ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{panel.port}/api/commands/fleetAccept", json={},
                          headers={"Authorization": f"Bearer {token}"}) as r:
            assert r.status == 403 and (await r.json()) == {"error": "fleet token"}


async def test_the_page_invites_and_accepts_in_one_go(aiohttp_server, aiohttp_client, tmp_path):
    import main

    projector = FakePanel(id="projector-2", name="HY260")
    async with make_rig(aiohttp_server, tmp_path, [(projector, False, True)]) as r:
        assert await r.leader.import_from(projector.id) == \
            "That panel is not on the network right now."
        async with aiohttp.ClientSession() as session:
            client = await aiohttp_client(main.build_app(session, r.leader))
            res = await client.post("/api/members/lookup",
                                    json={"address": "127.0.0.1", "port": projector.port})
            kiosk = (await res.json())["kiosk"]
            assert kiosk["id"] == projector.id
            res = await client.post(f"/api/members/{projector.id}/invite", json={
                "profile": "updates-only", "address": "127.0.0.1", "port": projector.port,
                "accept": True})
            assert await res.json() == {"ok": True, "pending": False, "accepted": True,
                                        "acceptError": None}
            assert r.leader.membership(r.leader.members[projector.id])[0] == "member"
            text = await (await client.get("/api/leader")).text()
            assert projector.password not in text
            assert r.leader.tokens[projector.id] not in text
