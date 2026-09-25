import asyncio
import json
import os
import tempfile
import unittest

from colmena.hub import Hub
from colmena.server import serve
from colmena.store import Store
from tests.test_hub import GB, ROLES, FakeTurn


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeTurn.replies, FakeTurn.log, FakeTurn.gate = {}, [], None
        self.dir = tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp"))
        self.path = self.dir.name + "/s.sock"
        self.hub = Hub(Store(":memory:"), ROLES, turn_factory=FakeTurn,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB}, notifier=lambda t, b: None)
        self.server = await serve(self.hub, self.path)
        self.r, self.w = await asyncio.open_unix_connection(self.path)
        self.n, self.events = 0, []

    async def asyncTearDown(self):
        self.w.close()
        self.server.close()
        await self.server.wait_closed()
        self.dir.cleanup()

    async def call(self, method, **params):
        self.n += 1
        self.w.write((json.dumps({"id": self.n, "method": method, "params": params}) + "\n").encode())
        while True:
            msg = json.loads(await self.r.readline())
            if "event" in msg:
                self.events.append(msg["event"]["type"])
            elif msg.get("id") == self.n:
                return msg

    async def test_round_trip(self):
        hello = await self.call("hello")
        self.assertEqual(hello["result"]["agents"], [])
        a = (await self.call("create_agent", name="Dev", role="dev"))["result"]
        self.assertEqual(a["name"], "Dev")
        bad = await self.call("create_agent", name="con espacio", role="dev")
        self.assertIn("nombre", bad["error"])
        await self.call("send", thread=a["id"], text="hola")
        await self.hub.drain()
        hist = (await self.call("history", thread=a["id"]))["result"]
        self.assertEqual([m["content"] for m in hist], ["hola", "ok"])

    async def test_unknown_method_and_bad_json(self):
        self.w.write(b"no es json\n")
        self.assertIn("error", await self.call("nada"))

    async def test_events_pushed(self):
        await self.call("hello")
        await self.call("create_agent", name="Dev", role="dev")
        self.assertEqual(self.events, ["agents"])


if __name__ == "__main__":
    unittest.main()
