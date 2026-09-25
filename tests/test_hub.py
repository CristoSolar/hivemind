import asyncio
import os
import tempfile
import unittest

from colmena.hub import Hub
from colmena.store import Store

GB = 1024 * 1024
ROLES = {"dev": {"name": "dev", "label": "Dev", "system_prompt": "", "allowed_tools": [], "cwd": "/tmp"}}


class FakeTurn:
    """Replies with a fixed text per agent name; optionally asks for approval first."""
    replies, log, gate = {}, [], None

    def __init__(self, agent, role, prompt, emit, ask, model=None, env=None):
        self.agent, self.prompt, self.emit, self.ask = agent, prompt, emit, ask
        FakeTurn.last_env = env
        self.stopped = False

    async def run(self):
        FakeTurn.log.append((self.agent["name"], "start"))
        if self.prompt.startswith("ASK"):
            self.decision = await self.ask("Bash", {"command": "rm x"}, "Bash(rm x)")
        if FakeTurn.gate:
            await FakeTurn.gate.wait()
        text = FakeTurn.replies.get(self.agent["name"], "ok")
        self.emit({"type": "text", "text": text})
        FakeTurn.log.append((self.agent["name"], "end"))
        return {"session_id": "s-" + self.agent["name"], "is_error": False, "text": text, "cost": 0}

    async def stop(self):
        self.stopped = True
        if FakeTurn.gate:
            FakeTurn.gate.set()


class HubTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeTurn.replies, FakeTurn.log, FakeTurn.gate = {}, [], None
        self.store = Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.notes = []
        self.saved = []
        self.hub = Hub(self.store, ROLES, turn_factory=FakeTurn,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                       notifier=lambda t, b: self.notes.append(t), save_config=self.saved.append)
        self.events = []
        self.hub.subscribe(self.events.append)

    def group(self):
        return [(m["author"], m["content"]) for m in self.store.history("group")]

    def test_name_validation(self):
        self.hub.create_agent("Dev", "dev")
        for bad in ("Dev", "dev", "con espacio", ""):
            with self.assertRaises(ValueError):
                self.hub.create_agent(bad, "dev")
        with self.assertRaises(ValueError):
            self.hub.create_agent("Otro", "nope")
        with tempfile.TemporaryDirectory() as d:
            missing = d + "/no-existe"
        with self.assertRaises(ValueError):
            self.hub.create_agent("Otro", "dev", missing)
        self.assertEqual(self.hub.create_agent("Señor-Ops", "dev")["name"], "Señor-Ops")

    async def test_private_chat_stores_session(self):
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "hola")
        await self.hub.drain()
        self.assertEqual(self.store.agent(a["id"])["session_id"], "s-Dev")
        self.assertEqual([m["content"] for m in self.store.history(a["id"])], ["hola", "ok"])
        self.assertIn({"type": "status", "agent": a["id"], "status": "idle"}, self.events)

    async def test_same_agent_turns_are_serial(self):
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "uno")
        await self.hub.send(a["id"], "dos")
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [("Dev", "start"), ("Dev", "end"), ("Dev", "start"), ("Dev", "end")])

    async def test_group_without_mention_runs_everyone(self):
        self.hub.create_agent("Dev", "dev")
        self.hub.create_agent("Mkt", "dev")
        await self.hub.send("group", "hola a todos")
        await self.hub.drain()
        self.assertEqual(sorted(x[0] for x in FakeTurn.log if x[1] == "start"), ["Dev", "Mkt"])

    async def test_agent_reply_without_mention_routes_nobody(self):
        self.hub.create_agent("Dev", "dev")
        self.hub.create_agent("Mkt", "dev")
        await self.hub.send("group", "@Dev hola")
        await self.hub.drain()
        self.assertEqual([x for x in FakeTurn.log if x[1] == "start"], [("Dev", "start")])

    async def test_group_handoff_and_context(self):
        self.hub.create_agent("Dev", "dev")
        self.hub.create_agent("Mkt", "dev")
        FakeTurn.replies = {"Dev": "listo, @Mkt te toca"}
        await self.hub.send("group", "@Dev arma la landing")
        await self.hub.drain()
        self.assertEqual(self.group(), [("user", "@Dev arma la landing"),
                                        (self.store.agents()[0]["id"], "listo, @Mkt te toca"),
                                        (self.store.agents()[1]["id"], "ok")])

    async def test_hop_limit(self):
        self.hub.create_agent("A", "dev")
        self.hub.create_agent("B", "dev")
        FakeTurn.replies = {"A": "@B", "B": "@A"}
        await self.hub.send("group", "@A empieza")
        await self.hub.drain()
        starts = [x for x in FakeTurn.log if x[1] == "start"]
        self.assertEqual(len(starts), 6)  # user->A, then 5 hops
        self.assertEqual(self.store.history("group")[-1]["author"], "system")

    async def test_unknown_mention_notice(self):
        await self.hub.send("group", "@Nadie hola")
        self.assertEqual(self.group()[-1][0], "system")

    async def test_approval_flow_always(self):
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "ASK borra")
        while not self.store.approvals():
            await asyncio.sleep(0)
        ap = self.store.approvals()[0]
        self.assertEqual(self.notes, [])  # a client is subscribed, no desktop notification
        self.hub.approve(ap["id"], "always")
        await self.hub.drain()
        self.assertEqual(self.store.agent(a["id"])["extra_allowed"], ["Bash(rm x)"])
        self.assertIn({"type": "approval_resolved", "id": ap["id"], "status": "always"}, self.events)

    async def test_approval_notifies_without_clients(self):
        self.hub.unsubscribe(self.events.append)
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "ASK borra")
        while not self.store.approvals():
            await asyncio.sleep(0)
        self.assertEqual(len(self.notes), 1)
        self.hub.approve(self.store.approvals()[0]["id"], "deny")
        await self.hub.drain()

    async def test_stop_denies_pending_and_drops_queue(self):
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "ASK borra")
        await self.hub.send(a["id"], "siguiente")
        while not self.store.approvals():
            await asyncio.sleep(0)
        await self.hub.stop(a["id"])
        await self.hub.drain()
        self.assertEqual(self.store.approvals(), [])
        self.assertEqual([x for x in FakeTurn.log if x[1] == "start"], [("Dev", "start")])

    async def test_delete_running_agent(self):
        FakeTurn.gate = asyncio.Event()
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "hola")
        await asyncio.sleep(0)
        await self.hub.delete_agent(a["id"])
        await self.hub.drain()
        self.assertIsNone(self.store.agent(a["id"]))

    def test_unicode_names_unique_ignoring_case(self):
        self.hub.create_agent("Óscar", "dev")
        with self.assertRaises(ValueError):
            self.hub.create_agent("óscar", "dev")

    async def test_cancelled_approval_is_expired(self):
        a = self.hub.create_agent("Dev", "dev")
        task = asyncio.ensure_future(self.hub._ask(a["id"], "Bash", {"command": "ls"}, "Bash(ls)"))
        while not self.store.approvals():
            await asyncio.sleep(0)
        ap = self.store.approvals()[0]
        task.cancel()  # the SDK cancels can_use_tool when the CLI cancels or closes
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.store.approvals(), [])
        self.assertIn({"type": "approval_resolved", "id": ap["id"], "status": "expired"}, self.events)

    def test_model_validation(self):
        self.assertEqual(self.hub.create_agent("Dev", "dev", model="sonnet")["model"], "sonnet")
        with self.assertRaises(ValueError):
            self.hub.create_agent("Otro", "dev", model="gpt-5")

    async def test_update_model_keeps_session(self):
        a = self.hub.create_agent("Dev", "dev")
        self.store.set_session(a["id"], "s1")
        self.hub.update_agent(a["id"], model="haiku")
        got = self.store.agent(a["id"])
        self.assertEqual((got["model"], got["session_id"]), ("haiku", "s1"))
        self.assertEqual(self.events[-1]["type"], "agents")

    async def test_update_cwd_resets_session_with_notice(self):
        a = self.hub.create_agent("Dev", "dev")
        self.store.set_session(a["id"], "s1")
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            self.hub.update_agent(a["id"], cwd=d)
            got = self.store.agent(a["id"])
            self.assertEqual((got["cwd"], got["session_id"]), (d, None))
            self.assertEqual(self.store.history(a["id"])[-1]["author"], "system")
            with self.assertRaises(ValueError):
                self.hub.update_agent(a["id"], cwd=d + "/no-existe")
        with self.assertRaises(ValueError):
            self.hub.update_agent(a["id"], model="gpt-5")

    async def test_api_key_settings_and_turn_env(self):
        self.assertEqual(self.hub.settings(), {"auth": "subscription", "has_api_key": False})
        with self.assertRaises(ValueError):
            self.hub.set_settings("api_key")  # no key saved yet
        self.hub.set_settings("api_key", "sk-test")
        self.assertEqual(self.hub.settings(), {"auth": "api_key", "has_api_key": True})
        self.assertEqual(self.saved[-1]["api_key"], "sk-test")
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "hola")
        await self.hub.drain()
        self.assertEqual(FakeTurn.last_env, {"ANTHROPIC_API_KEY": "sk-test"})
        self.hub.set_settings("subscription")  # key kept for later, not used
        self.assertEqual(self.hub.settings(), {"auth": "subscription", "has_api_key": True})
        await self.hub.send(a["id"], "hola")
        await self.hub.drain()
        self.assertIsNone(FakeTurn.last_env)

    def test_expire_stale_approvals(self):
        self.store.add_approval("a1", "Bash", {}, "Bash")
        self.hub.expire_stale_approvals()
        self.assertEqual(self.store.approvals(), [])
        self.assertEqual(len(self.store.approvals("expired")), 1)

    def test_notify_without_notify_send(self):
        from unittest import mock
        from colmena import hub
        with mock.patch("subprocess.Popen", side_effect=FileNotFoundError):
            hub.notify("t", "b")  # must not raise


if __name__ == "__main__":
    unittest.main()
