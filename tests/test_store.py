import sqlite3
import unittest

from colmena.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

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


if __name__ == "__main__":
    unittest.main()
