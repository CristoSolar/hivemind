import asyncio
import os
import tempfile
import unittest

from hivemind.hub import Hub
from hivemind.store import Store

GB = 1024 * 1024
ROLES = {"dev": {"name": "dev", "label": "Dev", "system_prompt": "", "allowed_tools": [], "cwd": "/tmp"}}


class FakeTurn:
    """Replies with a fixed text per agent name; optionally asks for approval first."""
    replies, log, gate = {}, [], None

    def __init__(self, agent, role, prompt, emit, ask, model=None, env=None, **kw):
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
        self.assertEqual(self.store.session(a["id"], a["id"]), "s-Dev")
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
        self.store.save_session(a["id"], a["id"], "s1")
        self.hub.update_agent(a["id"], model="haiku")
        self.assertEqual((self.store.agent(a["id"])["model"], self.store.session(a["id"], a["id"])), ("haiku", "s1"))
        self.assertEqual(self.events[-1]["type"], "agents")

    async def test_update_cwd_resets_session_with_notice(self):
        a = self.hub.create_agent("Dev", "dev")
        self.store.save_session(a["id"], a["id"], "s1")
        self.store.save_session(a["id"], "group", "g1")
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            self.hub.update_agent(a["id"], cwd=d)
            got = self.store.agent(a["id"])
            self.assertEqual(got["cwd"], d)
            self.assertEqual((self.store.session(a["id"], a["id"]), self.store.session(a["id"], "group")), (None, None))
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

    async def test_panel_client_does_not_silence_notifications(self):
        self.hub.unsubscribe(self.events.append)
        panel = lambda ev: None
        panel.panel = True  # the bar widget stays connected all the time
        self.hub.subscribe(panel)
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "ASK borra")
        while not self.store.approvals():
            await asyncio.sleep(0)
        self.assertEqual(len(self.notes), 1)
        self.hub.approve(self.store.approvals()[0]["id"], "deny")
        await self.hub.drain()

    async def test_activity_and_last_active(self):
        class BusyTurn(FakeTurn):
            async def run(self):
                self.emit({"type": "activity", "kind": "tool"})
                self.emit({"type": "activity", "kind": "tool"})  # repeated: broadcast once
                self.emit({"type": "activity", "kind": "thinking"})
                return await super().run()

        self.hub.turn_factory = BusyTurn
        a = self.hub.create_agent("Dev", "dev")
        before = self.hub.snapshot()["last_active"][a["id"]]
        await self.hub.send(a["id"], "hola")
        await self.hub.drain()
        acts = [e["activity"] for e in self.events if e["type"] == "activity" and e["agent"] == a["id"]]
        self.assertEqual(acts, ["thinking", "tool", "thinking", None])
        snap = self.hub.snapshot()
        self.assertIsNone(snap["activities"].get(a["id"]))
        self.assertGreaterEqual(snap["last_active"][a["id"]], before)

    def test_last_active_restored_from_history(self):
        a = self.store.create_agent("Old", "dev", "/tmp")
        m = self.store.add_message(a["id"], a["id"], "text", "hola")
        hub = Hub(self.store, ROLES, turn_factory=FakeTurn, meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                  notifier=lambda t, b: None, save_config=lambda c: None)
        self.assertEqual(hub.snapshot()["last_active"][a["id"]], m["ts"])
        b = self.store.create_agent("New", "dev", "/tmp")
        hub2 = Hub(self.store, ROLES, turn_factory=FakeTurn, meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                   notifier=lambda t, b: None, save_config=lambda c: None)
        self.assertEqual(hub2.snapshot()["last_active"][b["id"]], b["created_at"])

    def test_expire_stale_approvals(self):
        self.store.add_approval("a1", "Bash", {}, "Bash")
        self.hub.expire_stale_approvals()
        self.assertEqual(self.store.approvals(), [])
        self.assertEqual(len(self.store.approvals("expired")), 1)

    def test_notify_without_notify_send(self):
        from unittest import mock
        from hivemind import hub
        with mock.patch("subprocess.Popen", side_effect=FileNotFoundError):
            hub.notify("t", "b")  # must not raise

    async def test_turn_gets_board_server(self):
        seen = {}

        class SpyTurn(FakeTurn):
            def __init__(self, *a, mcp_servers=None, **kw):
                seen["servers"] = mcp_servers
                super().__init__(*a, **kw)

        self.hub.turn_factory = SpyTurn
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "hola")
        await self.hub.drain()
        self.assertEqual(list(seen["servers"]), ["tablero"])
    def make(self, *names):
        return [self.hub.create_agent(n, "dev") for n in names]

    async def test_custom_group_routes_only_to_members(self):
        dev, mkt, ops = self.make("Dev", "Mkt", "Ops")
        g = self.hub.create_group("Lanzamiento", [dev["id"], mkt["id"]])
        await self.hub.send(g["id"], "hola equipo")
        await self.hub.drain()
        self.assertEqual(sorted(x[0] for x in FakeTurn.log if x[1] == "start"), ["Dev", "Mkt"])
        self.assertEqual({m["thread"] for m in self.store.history(g["id"])}, {g["id"]})

    async def test_mentioning_a_non_member_gives_notice(self):
        dev, ops = self.make("Dev", "Ops")
        g = self.hub.create_group("Solo dev", [dev["id"]])
        await self.hub.send(g["id"], "@Ops ayuda")
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [])
        self.assertIn("no está en este grupo", self.store.history(g["id"])[-1]["content"])

    async def test_group_prompt_has_thread_and_private_bridge_only(self):
        prompts = {}

        class SpyTurn(FakeTurn):
            def __init__(self, agent, role, prompt, *a, **kw):
                prompts.setdefault(agent["name"], []).append(prompt)
                super().__init__(agent, role, prompt, *a, **kw)

        self.hub.turn_factory = SpyTurn
        dev, = self.make("Dev")
        g1 = self.hub.create_group("Uno", [dev["id"]])
        g2 = self.hub.create_group("Dos", [dev["id"]])
        await self.hub.send(dev["id"], "avance: la API ya está lista")
        await self.hub.drain()
        await self.hub.send(g1["id"], "secreto del grupo uno")
        await self.hub.drain()
        await self.hub.send(g2["id"], "¿cómo va el desarrollo?")
        await self.hub.drain()
        last = prompts["Dev"][-1]
        self.assertIn("¿cómo va el desarrollo?", last)
        self.assertIn("Tu chat privado reciente con el usuario", last)
        self.assertIn("la API ya está lista", last)
        self.assertNotIn("secreto del grupo uno", last)

    async def test_sessions_are_per_conversation(self):
        dev, = self.make("Dev")
        seen = []

        class SessionTurn(FakeTurn):
            async def run(self):
                seen.append(self.agent["session_id"])
                return {**await super().run(), "session_id": "s-" + self.prompt[:5]}

        self.hub.turn_factory = SessionTurn
        await self.hub.send(dev["id"], "priv1")
        await self.hub.drain()
        await self.hub.send("group", "@Dev grupo")
        await self.hub.drain()
        await self.hub.send(dev["id"], "priv2")
        await self.hub.drain()
        self.assertEqual(seen, [None, None, "s-priv1"])
        self.assertEqual(self.store.session(dev["id"], dev["id"]), "s-priv2")
        self.assertTrue(self.store.session(dev["id"], "group").startswith("s-"))

    async def test_hops_are_per_thread(self):
        a, b = self.make("A", "B")
        FakeTurn.replies = {"A": "@B", "B": "@A"}
        g = self.hub.create_group("AB", [a["id"], b["id"]])
        await self.hub.send(g["id"], "@A empieza")
        await self.hub.drain()
        self.assertEqual(len([x for x in FakeTurn.log if x[1] == "start"]), 6)
        self.assertEqual(self.store.history(g["id"])[-1]["author"], "system")
        self.assertEqual(self.store.history("group"), [])

    async def test_clear_thread_stops_its_turns_and_forgets_only_that_conversation(self):
        FakeTurn.gate = asyncio.Event()
        dev, = self.make("Dev")
        self.store.save_session(dev["id"], dev["id"], "private")
        self.store.save_session(dev["id"], "group", "old-group")
        await self.hub.send("group", "@Dev tema viejo")
        await asyncio.sleep(0)  # the turn is running and waiting on the gate
        await self.hub.clear_thread("group")
        await self.hub.drain()
        self.assertEqual(self.store.history("group"), [])  # nothing reappears after the stop
        self.assertIsNone(self.store.session(dev["id"], "group"))
        self.assertEqual(self.store.session(dev["id"], dev["id"]), "private")
        self.assertIn({"type": "thread_cleared", "thread": "group"}, self.events)

    async def test_new_conversation_clears_private_chat(self):
        dev, = self.make("Dev")
        await self.hub.send(dev["id"], "hola")
        await self.hub.drain()
        self.store.save_session(dev["id"], "group", "keep")
        await self.hub.clear_thread(dev["id"])
        self.assertEqual(self.store.history(dev["id"]), [])
        self.assertIsNone(self.store.session(dev["id"], dev["id"]))
        self.assertEqual(self.store.session(dev["id"], "group"), "keep")

    async def test_group_crud_validation_and_cascades(self):
        dev, mkt = self.make("Dev", "Mkt")
        for bad in (("", [dev["id"]]), ("X", []), ("X", ["nadie"])):
            with self.assertRaises(ValueError):
                self.hub.create_group(*bad)
        g = self.hub.create_group("Campaña", [dev["id"], mkt["id"]])
        self.store.save_session(mkt["id"], g["id"], "s")
        await self.hub.update_group(g["id"], members=[dev["id"]])  # removing a member forgets their group memory
        self.assertIsNone(self.store.session(mkt["id"], g["id"]))
        r = self.hub.routines.create("R", g["id"], "hola", {"every_hours": 1})
        await self.hub.delete_group(g["id"])
        self.assertIsNone(self.store.group(g["id"]))
        self.assertFalse(self.store.routine(r["id"])["enabled"])
        self.assertIn({"type": "groups", "groups": []}, self.events)

    def test_snapshot_lists_groups(self):
        dev, = self.make("Dev")
        self.hub.create_group("G", [dev["id"]])
        self.assertEqual([g["name"] for g in self.hub.snapshot()["groups"]], ["G"])
    async def test_stopped_turn_does_not_hand_off_after_clear(self):
        FakeTurn.gate = asyncio.Event()
        a, b = self.make("A", "B")
        FakeTurn.replies = {"A": "@B sigue"}
        g = self.hub.create_group("AB", [a["id"], b["id"]])
        await self.hub.send(g["id"], "@A empieza")
        await asyncio.sleep(0)  # A is mid-turn, waiting on the gate
        await self.hub.clear_thread(g["id"])
        FakeTurn.gate = None
        await self.hub.drain()
        self.assertEqual(self.store.history(g["id"]), [])
        self.assertIsNone(self.store.session(b["id"], g["id"]))
        self.assertEqual([x for x in FakeTurn.log if x == ("B", "start")], [])

    async def test_removed_member_mid_turn_is_stopped_and_forgets(self):
        FakeTurn.gate = asyncio.Event()
        a, b = self.make("A", "B")
        g = self.hub.create_group("AB", [a["id"], b["id"]])
        await self.hub.send(g["id"], "@B hola")
        await asyncio.sleep(0)  # B is mid-turn in the group
        await self.hub.update_group(g["id"], members=[a["id"]])
        FakeTurn.gate = None
        await self.hub.drain()
        self.assertIsNone(self.store.session(b["id"], g["id"]))
        self.assertEqual([m for m in self.store.history(g["id"]) if m["author"] == b["id"]], [])


if __name__ == "__main__":
    unittest.main()
