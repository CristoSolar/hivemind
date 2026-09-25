import sqlite3
import unittest

from hivemind.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.addCleanup(self.s.db.close)

    def test_agent_round_trip(self):
        a = self.s.create_agent("Dev", "dev", "/tmp")
        self.assertEqual(self.s.agent(a["id"])["name"], "Dev")
        self.s.set_session(a["id"], "sess-1")
        self.s.allow_always(a["id"], "Bash(git status)")
        self.s.allow_always(a["id"], "Bash(git status)")
        got = self.s.agent(a["id"])
        self.assertEqual(got["session_id"], "sess-1")
        self.assertEqual(got["extra_allowed"], ["Bash(git status)"])
        self.s.delete_agent(a["id"])
        self.assertIsNone(self.s.agent(a["id"]))

    def test_names_unique_case_insensitive(self):
        self.s.create_agent("Dev", "dev", "/tmp")
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.create_agent("dev", "dev", "/tmp")

    def test_history_chronological_and_paged(self):
        for i in range(5):
            self.s.add_message("group", "user", "text", f"m{i}")
        self.s.add_message("other", "user", "text", "x")
        last2 = self.s.history("group", limit=2)
        self.assertEqual([m["content"] for m in last2], ["m3", "m4"])
        older = self.s.history("group", before=last2[0]["id"], limit=10)
        self.assertEqual([m["content"] for m in older], ["m0", "m1", "m2"])

    def test_approvals(self):
        ap = self.s.add_approval("a1", "Bash", {"command": "ls"}, "Bash(ls)")
        self.assertEqual(self.s.approvals()[0]["input"], {"command": "ls"})
        self.s.resolve_approval(ap["id"], "allow")
        self.assertEqual(self.s.approvals(), [])

    def test_kv(self):
        self.assertIsNone(self.s.get("k"))
        self.s.set("k", "1")
        self.assertEqual(self.s.get("k"), "1")

    def test_model_and_update(self):
        a = self.s.create_agent("Dev", "dev", "/tmp", model="sonnet")
        self.assertEqual(a["model"], "sonnet")
        self.s.update_agent(a["id"], model=None, cwd="/var", session_id=None)
        got = self.s.agent(a["id"])
        self.assertEqual((got["model"], got["cwd"]), (None, "/var"))

    def test_migrates_old_database_without_model_column(self):
        import os, tempfile
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            path = d + "/old.db"
            old = sqlite3.connect(path)
            old.execute("create table agents(id text primary key, name text not null unique collate nocase,"
                        " role text not null, cwd text not null, session_id text,"
                        " extra_allowed text not null default '[]', created_at real not null)")
            old.execute("insert into agents values('a1', 'Hori', 'marketing', '/tmp', 's1', '[]', 1)")
            old.commit(); old.close()
            s = Store(path)
            self.assertEqual(s.agent("a1")["model"], None)
            self.assertEqual(s.agent("a1")["session_id"], "s1")
            s.db.close()

    def test_routines(self):
        r = self.s.create_routine("Resumen", "group", "resume", {"daily": "09:00"}, 100.0)
        self.assertEqual((r["schedule"], r["enabled"], r["last_run"]), ({"daily": "09:00"}, True, None))
        self.s.update_routine(r["id"], enabled=False, last_run=50.0, next_run=200.0, schedule={"every_hours": 2})
        got = self.s.routine(r["id"])
        self.assertEqual((got["enabled"], got["last_run"], got["next_run"], got["schedule"]),
                         (False, 50.0, 200.0, {"every_hours": 2}))
        self.assertEqual(len(self.s.routines()), 1)
        with self.assertRaises(ValueError):
            self.s.update_routine(r["id"], nope=1)
        self.s.delete_routine(r["id"])
        self.assertEqual(self.s.routines(), [])

    def test_tasks_and_log(self):
        t = self.s.create_task("Landing", "hero nuevo", None, "user")
        self.assertEqual((t["status"], t["assignee"], t["created_by"]), ("todo", None, "user"))
        self.s.update_task(t["id"], status="doing", assignee="a1")
        got = self.s.task(t["id"])
        self.assertEqual((got["status"], got["assignee"]), ("doing", "a1"))
        self.assertGreaterEqual(got["updated_at"], got["created_at"])
        self.assertEqual([x["id"] for x in self.s.tasks("doing")], [t["id"]])
        self.assertEqual(self.s.tasks("done"), [])
        self.s.add_task_log(t["id"], "user", "creó la tarea")
        self.assertEqual([x["text"] for x in self.s.task_log(t["id"])], ["creó la tarea"])
        with self.assertRaises(ValueError):
            self.s.update_task(t["id"], created_by="x")
        self.s.delete_task(t["id"])
        self.assertIsNone(self.s.task(t["id"]))
        self.assertEqual(self.s.task_log(t["id"]), [])
    def test_last_activity(self):
        a = self.s.create_agent("Dev", "dev", "/tmp")
        self.assertIsNone(self.s.last_activity(a["id"]))
        self.s.add_message("group", a["id"], "text", "hola grupo")
        m = self.s.add_message(a["id"], "user", "text", "hola")
        self.assertEqual(self.s.last_activity(a["id"]), m["ts"])

    def test_sessions_per_thread(self):
        a = self.s.create_agent("Dev", "dev", "/tmp")
        self.assertIsNone(self.s.session(a["id"], "group"))
        self.s.save_session(a["id"], "group", "g1")
        self.s.save_session(a["id"], a["id"], "p1")
        self.s.save_session(a["id"], "group", "g2")  # replaces
        self.assertEqual((self.s.session(a["id"], "group"), self.s.session(a["id"], a["id"])), ("g2", "p1"))
        self.s.delete_sessions(thread="group")
        self.assertEqual((self.s.session(a["id"], "group"), self.s.session(a["id"], a["id"])), (None, "p1"))
        self.s.delete_sessions(agent_id=a["id"])
        self.assertIsNone(self.s.session(a["id"], a["id"]))
        with self.assertRaises(ValueError):
            self.s.delete_sessions()

    def test_groups_and_members(self):
        a = self.s.create_agent("Dev", "dev", "/tmp")
        b = self.s.create_agent("Mkt", "dev", "/tmp")
        g = self.s.create_group("Lanzamiento")
        self.assertTrue(g["id"].startswith("g-"))
        self.s.set_members(g["id"], [a["id"], b["id"]])
        self.assertEqual(set(self.s.group(g["id"])["members"]), {a["id"], b["id"]})
        self.s.rename_group(g["id"], "Campaña")
        self.assertEqual(self.s.groups()[0]["name"], "Campaña")
        self.s.delete_agent(b["id"])
        self.assertEqual(self.s.group(g["id"])["members"], [a["id"]])
        self.s.delete_group(g["id"])
        self.assertIsNone(self.s.group(g["id"]))

    def test_delete_messages_of_one_thread(self):
        self.s.add_message("group", "user", "text", "a")
        self.s.add_message("g-1", "user", "text", "b")
        self.s.delete_messages("group")
        self.assertEqual([m["content"] for m in self.s.history("group")], [])
        self.assertEqual([m["content"] for m in self.s.history("g-1")], ["b"])

    def test_migration_moves_private_memory_once(self):
        import os, tempfile
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            path = d + "/old.db"
            old = Store(path)
            a = old.create_agent("Dev", "dev", "/tmp")
            old.set_session(a["id"], "legacy")  # pre-sessions memory lived on the agent row
            old.db.execute("delete from sessions")
            old.db.execute("delete from kv")    # a database from before the sessions table
            old.db.commit()
            old.db.close()
            for _ in range(2):  # idempotent
                s = Store(path)
                self.assertEqual(s.session(a["id"], a["id"]), "legacy")
                self.assertIsNone(s.session(a["id"], "group"))
                self.assertEqual(s.db.execute("select count(*) from sessions").fetchone()[0], 1)
                s.db.close()
    def test_cleared_memory_stays_cleared_after_restart(self):
        import os, tempfile
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            path = d + "/old.db"
            old = Store(path)
            a = old.create_agent("Dev", "dev", "/tmp")
            old.set_session(a["id"], "legacy")
            old.db.execute("delete from sessions")
            old.db.execute("delete from kv")
            old.db.commit()
            old.db.close()
            s = Store(path)                      # upgrade: legacy memory becomes the private session
            s.delete_sessions(agent_id=a["id"])  # the user picks «Nueva conversación»
            s.db.close()
            s = Store(path)                      # daemon restart
            self.assertIsNone(s.session(a["id"], a["id"]))
            s.db.close()


if __name__ == "__main__":
    unittest.main()
