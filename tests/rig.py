"""A leader with fake panels over real local HTTP, for the fleet tests."""

import contextlib

from fake_panel import FakePanel
from leader import Leader


class Rig:
    def __init__(self, leader, devices, panels, remembered):
        self.leader, self.devices, self.panels, self.remembered = (
            leader, devices, panels, remembered)

    async def join(self, panel, accept_on_screen=True):
        if not self.leader.store_version:
            assert await self.leader.import_from(self.panels[0].id) is None
        assert await self.leader.invite(panel.id) is None
        if accept_on_screen:
            panel.accept()
        await self.leader.tick()
        await self.leader.updates.wait()


@contextlib.asynccontextmanager
async def make_rig(aiohttp_server, tmp_path, specs):
    """specs: [(FakePanel, discovered, agent)]; an undiscovered panel is not
    in the leader's device list, as one on another VLAN."""
    import main

    devices, panels, remembered = {}, [], []
    for panel, discovered, agent in specs:
        server = await aiohttp_server(panel.app())
        panel.port = server.port
        panel.agent = agent
        panels.append(panel)
        if discovered:
            devices[panel.id] = {"id": panel.id, "host": "127.0.0.1", "port": server.port,
                                 "tls": False, "version": panel.version, "name": panel.name,
                                 "online": True, "agent": agent}
    leader = Leader(tmp_path, fleet_port=0, password=panels[0].password, version="0.4.0",
                    devices=lambda: devices, remember=remembered.append)
    identity = await aiohttp_server(main.build_fleet_app(leader))
    leader.fleet_port = identity.port
    leader.listening = True
    await leader.open()
    try:
        yield Rig(leader, devices, panels, remembered)
    finally:
        await leader.close()


def panel_pair():
    """A wall panel (arm64) and a projector agent (32-bit, no silent
    installer: Android would ask on its screen)."""
    panel = FakePanel()
    projector = FakePanel(id="projector-1", name="Aurora Projector")
    projector.abis = ["armeabi-v7a", "armeabi"]
    projector.installer = {"nativeSilent": False, "shizukuReady": False, "helper": "unavailable",
                           "shizukuEnabled": False, "startCommand": "adb shell ..."}
    return panel, projector
