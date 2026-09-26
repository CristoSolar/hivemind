import asyncio
import json
import os
import tempfile
import unittest

from hivemind.hub import Hub
from hivemind.server import serve
from hivemind.store import Store
from tests.test_hub import GB, ROLES, FakeTurn


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeTurn.replies, FakeTurn.log, FakeTurn.gate = {}, [], None
        self.dir = tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp"))
        self.path = self.dir.name + "/s.sock"
        self.hub = Hub(Store(":memory:"), ROLES, turn_factory=FakeTurn,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB}, notifier=lambda t, b: None)
        self.server = await serve(self.hub, self.path)
        self.r, self.w = await asyncio.open_unix_connection(self.path, limit=16 * 1024 * 1024)
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

    async def test_huge_message_is_accepted(self):
        a = (await self.call("create_agent", name="Dev", role="dev"))["result"]
        big = "x" * 200_000
        self.assertEqual((await self.call("send", thread=a["id"], text=big))["result"], True)
        await self.hub.drain()

    async def test_non_object_json_keeps_connection(self):
        self.w.write(b"[1, 2]\n")
        self.assertIn("result", await self.call("hello"))

    async def test_settings_never_return_the_key(self):
        self.hub.save_config = lambda cfg: None
        await self.call("set_settings", auth="api_key", api_key="sk-secreto")
        got = await self.call("get_settings")
        self.assertEqual(got["result"], {"auth": "api_key", "has_api_key": True})
        self.assertNotIn("sk-secreto", json.dumps(await self.call("hello")))

    async def test_update_agent(self):
        a = (await self.call("create_agent", name="Dev", role="dev", model="opus"))["result"]
        self.assertEqual(a["model"], "opus")
        got = (await self.call("update_agent", agent=a["id"], model="haiku"))["result"]
        self.assertEqual(got["model"], "haiku")

    async def test_hello_as_panel_marks_the_client(self):
        await self.call("hello", role="panel")
        self.assertFalse(self.hub.has_window())
        r2, w2 = await asyncio.open_unix_connection(self.path)
        w2.write(b'{"id": 1, "method": "hello", "params": {}}\n')
        await r2.readline()
        self.assertTrue(self.hub.has_window())
        w2.close()

    async def test_slow_request_does_not_block_the_connection(self):
        release = asyncio.Event()

        class StuckTurn(FakeTurn):
            async def run(self):
                await release.wait()
                return {"session_id": None, "is_error": False, "text": "", "cost": 0}

            async def stop(self):
                pass  # e.g. CLI not connected yet

        self.hub.turn_factory = StuckTurn
        a = (await self.call("create_agent", name="Dev", role="dev"))["result"]
        await self.call("send", thread=a["id"], text="hola")
        self.n += 1
        self.w.write((json.dumps({"id": self.n, "method": "delete_agent", "params": {"agent": a["id"]}}) + "\n").encode())
        try:
            hello = await asyncio.wait_for(self.call("hello"), 2)
            self.assertIn("result", hello)
        finally:
            release.set()
            await self.hub.drain()

    async def test_routine_and_task_methods(self):
        r = (await self.call("create_routine", name="R", target="group", prompt="hola",
                             schedule={"daily": "09:00"}))["result"]
        self.assertEqual(r["schedule"], {"daily": "09:00"})
        self.assertIn("error", await self.call("create_routine", name="R", target="group", prompt="hola",
                                               schedule={"daily": "99:00"}))
        got = (await self.call("update_routine", routine=r["id"], enabled=False))["result"]
        self.assertFalse(got["enabled"])
        self.assertEqual(len((await self.call("list_routines"))["result"]), 1)
        await self.call("delete_routine", routine=r["id"])
        t = (await self.call("create_task", title="Landing"))["result"]
        self.assertEqual((await self.call("update_task", task=t["id"], status="done"))["result"]["status"], "done")
        self.assertEqual(len((await self.call("task_log", task=t["id"]))["result"]), 2)
        self.assertEqual(len((await self.call("list_tasks", status="done"))["result"]), 1)
        await self.call("delete_task", task=t["id"])
        self.assertEqual((await self.call("list_tasks"))["result"], [])
        self.assertIn("routines", self.events)
        self.assertIn("tasks", self.events)
    async def test_group_and_clear_methods(self):
        a = (await self.call("create_agent", name="Dev", role="dev"))["result"]
        g = (await self.call("create_group", name="Lanzamiento", members=[a["id"]]))["result"]
        self.assertEqual(g["members"], [a["id"]])
        self.assertEqual((await self.call("update_group", group=g["id"], name="Campaña"))["result"]["name"], "Campaña")
        self.assertEqual(len((await self.call("list_groups"))["result"]), 1)
        await self.call("send", thread=g["id"], text="hola")
        await self.hub.drain()
        await self.call("clear_thread", thread=g["id"])
        self.assertEqual((await self.call("history", thread=g["id"]))["result"], [])
        await self.call("delete_group", group=g["id"])
        self.assertEqual((await self.call("list_groups"))["result"], [])
        self.assertIn("thread_cleared", self.events)
        self.assertIn("groups", self.events)
    async def test_send_with_attachments(self):
        from pathlib import Path
        from unittest import mock
        from hivemind import attachments
        with mock.patch.object(attachments, "root", lambda: Path(self.dir.name) / "adjuntos"):
            a = (await self.call("create_agent", name="Dev", role="dev"))["result"]
            f = Path(self.dir.name) / "foto.png"
            f.write_bytes(b"png")
            self.assertTrue((await self.call("send", thread=a["id"], attachments=[str(f)]))["result"])
            await self.hub.drain()
            first = (await self.call("history", thread=a["id"]))["result"][0]
            self.assertEqual([x["name"] for x in first["attachments"]], ["foto.png"])
            bad = await self.call("send", thread=a["id"], text="x", attachments=["/no/existe.png"])
            self.assertIn("No encuentro", bad["error"])


if __name__ == "__main__":
    unittest.main()
