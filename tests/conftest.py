"""Fixtures for the csLights tests.

FakeDaemon is a minimal stand-in for CSHomeMasterDaemonApp on localhost: it answers
GetHomeModel, GetModules and GetAccState like the real daemon (see
../csLights/CSHomeMasterDaemonApp/src/mastercomconnection.cpp) and records commands.
"""

import asyncio
import json

import pytest


def module(sn, typ, idx=0):
    return {"name": f"m{sn}", "sn": str(sn), "mac": f"00:00:00:00:00:{sn:02x}",
            "type": typ, "index": idx}


def accessory(acc_id, typ, svc_type, mods, name=None):
    return {
        "accessory": {"id": acc_id, "name": name or f"acc{acc_id}", "type": typ,
                      "location": {"room": "Room", "zone": "Zone", "pos_x": 0, "pos_y": 0, "pos_z": 0}},
        "services": [{"service": {"id": acc_id * 10, "role": 1, "type": svc_type}, "modules": mods}],
    }


MODEL = [
    accessory(1, 1, 2, [module(11, 2)], "Lamp"),                 # dimmable light on LBUS_WLED
    accessory(2, 3, 4, [module(12, 3, 1)], "Blind"),             # window blind
    accessory(3, 2, 1, [module(12, 3, 1)], "Relay"),             # relay
    accessory(4, 4, 1, [module(13, 3, 2), module(14, 3, 3)], "Wall"),  # wall switch
    accessory(5, 1, 1, [module(12, 3, 1)], "Spot"),              # on/off light (no brightness)
]
MODULES = [dict(module(20, 1), lbusCount=4), module(11, 2)]

STATES = {
    1: {"type": "light", "on": True, "brightness": 0.5},
    2: {"type": "blind", "currPos": 0.29, "cmdPos": 0.29, "state": "BlindIdle"},
    3: {"type": "relay", "state": True},
    4: {"type": "switch", "value": "1"},
    5: {"type": "light", "on": False, "brightness": 0.0},
}


class FakeDaemon:
    def __init__(self):
        self.accessories = json.loads(json.dumps(MODEL))
        self.modules = json.loads(json.dumps(MODULES))
        self.commands = []
        self.writers = []
        self.server = None
        self.port = None
        self.silent: set[str] = set()   # commands left unanswered

    async def start(self, port=0):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]

    def stop(self):
        if self.server:
            self.server.close()
        for w in self.writers:
            w.transport.abort()
        self.writers.clear()

    async def handle(self, reader, writer):
        self.writers.append(writer)
        buf = b""
        try:
            while data := await reader.read(65536):
                buf += data
                while b"}" in buf:
                    raw, buf = buf.split(b"}", 1)
                    cmd = json.loads(raw + b"}")
                    self.commands.append(cmd)
                    await self.reply(writer, cmd)
        except (ConnectionError, OSError):
            pass

    def send(self, rpl: dict):
        """Push a message to the connected client, like the daemon's broadcasts."""
        self.writers[-1].write(json.dumps(rpl).encode() + b"\n")

    async def reply(self, writer, cmd):
        c = cmd["command"]
        if c in self.silent:
            return
        if c == "GetHomeModel":
            rpl = {"rpl-type": "home-model", "accessories": self.accessories}
        elif c == "GetModules":
            rpl = {"rpl-type": "module-list", "modules": self.modules}
        elif c == "GetAccState":
            acc_id = int(cmd["acc-id"])
            assert acc_id in {a["accessory"]["id"] for a in self.accessories}, \
                f"GetAccState for unknown accessory {acc_id}"
            rpl = {"rpl-type": "acc-state", "acc-id": acc_id, "valid": True, **STATES[acc_id]}
        else:
            return
        writer.write(json.dumps(rpl).encode() + b"\n")
        await writer.drain()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def daemon(monkeypatch, socket_enabled):
    import pytest_socket
    pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"], allow_unix_socket=True)
    d = FakeDaemon()
    await d.start()
    import custom_components.cslab.config_flow as cf
    import custom_components.cslab.cshome_master as cm
    monkeypatch.setattr(cm, "CSMASTER_TCP_PORT", d.port)
    monkeypatch.setattr(cf, "CSMASTER_TCP_PORT", d.port)
    yield d
    d.stop()
