import unittest

from hivemind import palette
from hivemind.hub import Hub
from hivemind.store import Store
from tests.test_hub import GB, ROLES


class PaletteTest(unittest.TestCase):
    def test_names_are_unique_and_hues_distinct(self):
        names = [n for n, _ in palette.PALETTE]
        hues = [h for _, h in palette.PALETTE]
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(len(set(hues)), len(hues))

    def test_valid_accepts_a_slot_or_none(self):
        for good in [None] + list(range(palette.AGENT_TINTS)):
            self.assertTrue(palette.valid(good), good)

    def test_valid_rejects_everything_else(self):
        for bad in (-1, palette.AGENT_TINTS, "2", 1.5, True, False, [0]):
            self.assertFalse(palette.valid(bad), bad)

    def test_name_of_none_is_automatic(self):
        self.assertEqual(palette.name(None), "Automático")
        self.assertEqual(palette.name(0), palette.PALETTE[0][0])

    def test_the_daemon_never_imports_the_interface(self):
        """The palette is data: hivemind.hub must not pull GTK in to validate a colour."""
        import subprocess
        import sys
        out = subprocess.run(
            [sys.executable, "-c",
             "import hivemind.hub, sys;"
             "print(any(m.startswith('hivemind.ui') or m == 'gi' for m in sys.modules))"],
            capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


class AgentTintTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.hub = Hub(self.store, ROLES,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                       notifier=lambda t, b: None, save_config=lambda c: None)

    def test_an_agent_starts_without_a_chosen_colour(self):
        self.assertIsNone(self.hub.create_agent("Ana", "dev")["tint"])

    def test_a_chosen_colour_is_kept(self):
        a = self.hub.create_agent("Ana", "dev", tint=3)
        self.assertEqual(self.store.agent(a["id"])["tint"], 3)

    def test_the_colour_can_be_changed_and_cleared(self):
        a = self.hub.create_agent("Ana", "dev", tint=3)
        self.hub.update_agent(a["id"], tint=5)
        self.assertEqual(self.store.agent(a["id"])["tint"], 5)
        self.hub.update_agent(a["id"], tint=None)
        self.assertIsNone(self.store.agent(a["id"])["tint"])

    def test_changing_the_colour_keeps_the_agent_memory(self):
        a = self.hub.create_agent("Ana", "dev")
        self.store.set_session(a["id"], "sess-1")
        self.hub.update_agent(a["id"], tint=2)
        self.assertEqual(self.store.agent(a["id"])["session_id"], "sess-1")

    def test_a_colour_outside_the_palette_is_refused(self):
        for bad in (-1, palette.AGENT_TINTS, "rojo", 2.5):
            with self.assertRaises(ValueError, msg=bad):
                self.hub.create_agent(f"A{str(bad)[:3]}", "dev", tint=bad)

    def test_an_old_database_opens_with_no_colour(self):
        old = Store(":memory:")
        self.addCleanup(old.db.close)
        with old.db:
            old.db.execute("drop table agents")
            old.db.execute("create table agents(id text primary key, name text not null unique"
                           " collate nocase, role text not null, cwd text not null, session_id text,"
                           " extra_allowed text not null default '[]', created_at real not null)")
        reopened = Store(":memory:")
        self.addCleanup(reopened.db.close)
        self.assertIsNone(reopened.create_agent("Nueva", "dev", "/tmp")["tint"])


if __name__ == "__main__":
    unittest.main()
