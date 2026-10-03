"""Fleet updates: APKs held per ABI, streamed to each member, installed
with its fleet token, and never anything on an agent's screen."""

import logging

import pytest

import updates as upd
from apk import ApkError
from apk_builder import build_apk
from leader import Member
from rig import make_rig, panel_pair

NEW = {"version_name": "2026.9.88", "version_code": 290}


async def chunks(data, size=7000):
    for i in range(0, len(data), size):
        yield data[i:i + size]


@pytest.fixture
async def rig(aiohttp_server, tmp_path):
    panel, projector = panel_pair()
    async with make_rig(aiohttp_server, tmp_path,
                        [(panel, True, False), (projector, True, True)]) as r:
        await r.join(panel)
        await r.join(projector)
        yield r


async def store(leader, abis, **kw):
    data = build_apk(abis=abis, payload=b"x" * 50000, **{**NEW, **kw})
    return await leader.updates.receive(chunks(data), f"ks-{'-'.join(abis)}.apk")


async def test_one_apk_per_abi(tmp_path):
    leader = type("L", (), {"password": "pw", "schedule_tick": lambda self: None})()
    u = upd.FleetUpdates(leader, tmp_path)
    a64 = await u.receive(chunks(build_apk(abis=("arm64-v8a",), **NEW)), "a.apk")
    a32 = await u.receive(chunks(build_apk(abis=("armeabi-v7a",), **NEW)), "b.apk")
    assert [a["abis"] for a in u.apks] == [["arm64-v8a"], ["armeabi-v7a"]]
    assert a64["versionName"] == "2026.9.88" and a64["versionCode"] == 290
    # A newer arm64 build takes only the arm64 one's place.
    newer = await u.receive(chunks(build_apk(abis=("arm64-v8a",), version_name="2026.9.89",
                                             version_code=291)), "c.apk")
    assert {a["id"] for a in u.apks} == {a32["id"], newer["id"]}
    assert not (tmp_path / "apks" / a64["file"]).exists()
    # A universal APK covers both.
    uni = await u.receive(chunks(build_apk(abis=("arm64-v8a", "armeabi-v7a"), **NEW)), "u.apk")
    assert [a["id"] for a in u.apks] == [uni["id"]]
    # Kept across a restart.
    assert [a["id"] for a in upd.FleetUpdates(leader, tmp_path).apks] == [uni["id"]]
    # Not Kiosk Satellite, not an APK: refused, nothing left behind.
    with pytest.raises(ApkError, match="not Kiosk Satellite"):
        await u.receive(chunks(build_apk(package="com.example.other")), "x.apk")
    with pytest.raises(ApkError, match="not an APK"):
        await u.receive(chunks(b"not a zip at all"), "y.apk")
    assert sorted(p.name for p in (tmp_path / "apks").iterdir()) == \
        sorted([uni["file"], "apks.json"])


def test_behind_counts_the_fork_stamp():
    a = {"versionName": "2026.10.4-djc-2026.10.02.3", "versionCode": 302}
    behind = upd.FleetUpdates.behind
    assert behind(Member("x", version="2026.10.4-djc-2026.10.02.2"), a) is True
    assert behind(Member("x", version="2026.10.4-djc-2026.10.02.3"), a) is False
    assert behind(Member("x", version="2026.10.4-djc-2026.10.03.1"), a) is False
    assert behind(Member("x", version="2026.10.3-djc-2026.10.02.9"), a) is True
    assert behind(Member("x", version="2026.10.4"), a) is True
    assert behind(Member("x", version="2026.9.87+286"),
                  {"versionName": "2026.9.88", "versionCode": 290}) is True
    assert behind(Member("x", version=""), a) is None


def test_silent_install_reads_the_installer_as_ks_does():
    assert upd.silent_install({"nativeSilent": True}) == (True, "Android")
    assert upd.silent_install({"nativeSilent": False, "helper": "ready"}) == \
        (True, "the update helper")
    assert upd.silent_install({"nativeSilent": False, "helper": "unavailable"}) == \
        (False, "confirmation")
    assert upd.silent_install({"shizukuEnabled": True, "shizukuReady": True}) == (True, "Shizuku")
    assert upd.silent_install({"shizukuEnabled": True, "shizukuReady": False,
                               "nativeSilent": True})[0] is False
    assert upd.silent_install(None) == (False, "unknown")


async def test_each_member_gets_its_abi_and_the_agent_is_left_alone(rig):
    leader = rig.leader
    panel, projector = rig.panels
    a64 = await store(leader, ("arm64-v8a",))
    a32 = await store(leader, ("armeabi-v7a",))
    assert await leader.updates.check() == {}
    pm, jm = leader.members[panel.id], leader.members[projector.id]
    assert pm.abis == panel.abis and jm.abis == ["armeabi-v7a", "armeabi"]
    view = {r["id"]: r for r in leader.updates.view()["members"]}
    assert view[panel.id]["apk"]["id"] == a64["id"] and view[panel.id]["blocker"] is None
    assert view[projector.id]["apk"]["id"] == a32["id"]
    assert view[projector.id]["blocker"] == upd.AGENT_BLOCKED
    assert view[projector.id]["installer"] == "No silent installer"

    assert leader.updates.start() is None
    await leader.updates.wait()
    # The panel: its own ABI's APK, streamed with a length (not chunked),
    # then installed, both with its fleet token.
    assert len(panel.uploads) == 1
    up = panel.uploads[0]
    assert up["abis"] == ["arm64-v8a"] and up["version"] == "2026.9.88"
    assert up["length"] == up["size"] == a64["size"] and not up["chunked"]
    assert ("installUploadedApk", "fleet") in panel.commands
    assert len(panel.installs) == 1
    # The projector: nothing sent, nothing installed, said why.
    assert projector.uploads == [] and projector.installs == []
    assert not any(c[0] == "installUploadedApk" for c in projector.commands)
    rows = {r["id"]: r for r in leader.updates.view()["members"]}
    assert rows[panel.id]["phase"] == "installing"
    assert rows[projector.id]["phase"] == "skipped"
    assert rows[projector.id]["reason"] == upd.AGENT_BLOCKED

    # The update helper started over adb: the projector installs silently.
    projector.installer = {**projector.installer, "helper": "ready"}
    assert leader.updates.start({projector.id}) is None
    await leader.updates.wait()
    assert [u["abis"] for u in projector.uploads] == [["armeabi-v7a"]]
    assert len(projector.installs) == 1
    assert len(panel.uploads) == 1  # only the one asked for

    # The panel restarts on the new version: its row says so.
    panel.version = "2026.9.88"
    await leader.tick()
    assert {r["id"]: r for r in leader.updates.view()["members"]}[panel.id]["phase"] == "updated"


async def test_an_agent_whose_helper_stops_mid_upload_is_not_asked_to_install(rig):
    leader = rig.leader
    _, projector = rig.panels
    await store(leader, ("armeabi-v7a",))
    projector.installer = {**projector.installer, "helper": "ready"}
    projector.on_upload = lambda: projector.installer.update(helper="unavailable")
    assert leader.updates.start({projector.id}) is None
    await leader.updates.wait()
    assert len(projector.uploads) == 1
    assert not any(c[0] == "installUploadedApk" for c in projector.commands)
    row = {r["id"]: r for r in leader.updates.view()["members"]}[projector.id]
    assert row["phase"] == "skipped" and row["reason"] == upd.AGENT_BLOCKED


async def test_an_agent_on_shizuku_installs(rig):
    leader = rig.leader
    _, projector = rig.panels
    await store(leader, ("armeabi-v7a",))
    projector.installer = {**projector.installer, "shizukuEnabled": True, "shizukuReady": True}
    leader.updates.start({projector.id})
    await leader.updates.wait()
    assert len(projector.installs) == 1


async def test_refusals_are_the_members_own_words(rig):
    leader = rig.leader
    panel, _ = rig.panels
    await store(leader, ("arm64-v8a",))
    panel.upload_error = "Not enough free space: the APK is 0.1 MB ..."
    leader.updates.start({panel.id})
    await leader.updates.wait()
    row = {r["id"]: r for r in leader.updates.view()["members"]}[panel.id]
    assert row["phase"] == "skipped" and row["reason"].startswith("Not enough free space")
    assert panel.installs == []

    panel.upload_error = None
    panel.install_error = "an install is already running"
    leader.updates.start({panel.id})
    await leader.updates.wait()
    row = {r["id"]: r for r in leader.updates.view()["members"]}[panel.id]
    assert row["phase"] == "failed" and row["reason"] == "an install is already running"

    # A member already on the APK's version is not sent it.
    panel.install_error = None
    panel.version = "2026.9.88"
    uploads = len(panel.uploads)
    leader.updates.start({panel.id})
    await leader.updates.wait()
    row = {r["id"]: r for r in leader.updates.view()["members"]}[panel.id]
    assert row["phase"] == "current" and len(panel.uploads) == uploads


async def test_no_apk_for_a_32_bit_android_means_none_is_sent(rig):
    leader = rig.leader
    _, projector = rig.panels
    projector.installer = {**projector.installer, "helper": "ready"}
    await store(leader, ("arm64-v8a",))
    leader.updates.start({projector.id})
    await leader.updates.wait()
    assert projector.uploads == []
    row = {r["id"]: r for r in leader.updates.view()["members"]}[projector.id]
    assert row["reason"] == "No uploaded APK runs on armeabi-v7a, armeabi"


async def test_without_the_password_the_abi_is_unknown(rig):
    leader = rig.leader
    panel, _ = rig.panels
    leader.password = ""
    await store(leader, ("arm64-v8a",))
    m = leader.members[panel.id]
    assert m.abis == []
    assert "panel_password" in leader.updates.apk_for(m)[1]
    # A universal APK runs anywhere, so it can go without knowing.
    await store(leader, ("arm64-v8a", "armeabi-v7a"))
    assert leader.updates.apk_for(m)[0]["abis"] == ["arm64-v8a", "armeabi-v7a"]


async def test_keep_members_on_this_version(rig):
    leader = rig.leader
    panel, projector = rig.panels
    await store(leader, ("arm64-v8a",))
    await leader.updates.check()
    await leader.tick()
    await leader.updates.wait()
    assert panel.uploads == []  # off by default
    leader.updates.set_keep(True)
    await leader.tick()
    await leader.updates.wait()
    assert len(panel.installs) == 1
    assert leader.updates.run["auto"] is True
    # Once per APK: the next tick does not send it again.
    await leader.tick()
    await leader.updates.wait()
    assert len(panel.uploads) == 1
    # The projector, an agent with no APK for its ABI, was never sent one.
    assert projector.uploads == []


async def test_no_token_is_logged(rig, caplog):
    leader = rig.leader
    panel, projector = rig.panels
    caplog.set_level(logging.DEBUG)
    await store(leader, ("arm64-v8a",))
    await store(leader, ("armeabi-v7a",))
    leader.updates.start()
    await leader.updates.wait()
    for secret in [panel.password, *leader.tokens.values(), *leader._admin_tokens.values()]:
        assert secret not in caplog.text
