import unittest

from hivemind.hub import Hub
from hivemind.roles import DEFAULT_ROLES, load_roles
from hivemind.runner import Turn
from hivemind.store import Store
from tests.test_hub import GB, ROLES


class BriefTest(unittest.TestCase):
    """Two agents may share a role and still work differently: the brief says how."""

    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.hub = Hub(self.store, ROLES,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                       notifier=lambda t, b: None, save_config=lambda c: None)

    def _prompt_of(self, agent, role):
        return Turn(agent, role, "hola", emit=lambda e: None, ask=None)._prompt()

    def test_brief_reaches_the_system_prompt(self):
        a = self.hub.create_agent("Ana", "dev", brief="Eres directa. Te encargas del backend.")
        text = self._prompt_of(a, ROLES["dev"])
        self.assertIn("Eres directa. Te encargas del backend.", text)
        self.assertIn("Instrucciones propias de Ana", text)
        self.assertTrue(text.startswith(ROLES["dev"]["system_prompt"]), "the role still leads")

    def test_same_role_different_briefs(self):
        a = self.hub.create_agent("Ana", "dev", brief="backend y base de datos")
        b = self.hub.create_agent("Beto", "dev", brief="interfaz y accesibilidad")
        self.assertNotEqual(self._prompt_of(a, ROLES["dev"]), self._prompt_of(b, ROLES["dev"]))

    def test_no_brief_leaves_the_prompt_untouched(self):
        a = self.hub.create_agent("Ana", "dev")
        self.assertNotIn("Instrucciones propias", self._prompt_of(a, ROLES["dev"]))

    def test_brief_is_editable_without_resetting_the_session(self):
        a = self.hub.create_agent("Ana", "dev", brief="corta")
        self.store.set_session(a["id"], "sess-1")
        self.hub.update_agent(a["id"], brief="  larga y con espacios  ")
        got = self.store.agent(a["id"])
        self.assertEqual(got["brief"], "larga y con espacios")
        self.assertEqual(got["session_id"], "sess-1", "editing the brief must not drop memory")

    def test_brief_survives_an_old_database(self):
        """A database written before briefs existed still opens, with an empty brief."""
        old = Store(":memory:")
        self.addCleanup(old.db.close)
        with old.db:
            old.db.execute("drop table agents")
            old.db.execute("create table agents(id text primary key, name text not null unique"
                           " collate nocase, role text not null, cwd text not null, session_id text,"
                           " extra_allowed text not null default '[]', created_at real not null)")
            old.db.execute("insert into agents(id, name, role, cwd, created_at)"
                           " values('a1', 'Vieja', 'dev', '/tmp', 0)")
        reopened = Store(":memory:")
        self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.create_agent("Nueva", "dev", "/tmp")["brief"], "")


class DefaultRolesTest(unittest.TestCase):
    def test_the_office_roles_ship_by_default(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            roles = load_roles(Path(d))
        for name in ("producto", "uiux", "qa", "datos", "soporte"):
            self.assertIn(name, roles)
            self.assertTrue(roles[name]["system_prompt"].strip(), name)
            self.assertTrue(roles[name]["allowed_tools"], name)

    def test_qa_may_run_tests_but_not_chained_commands(self):
        import tomllib
        from hivemind.roles import permitted
        rules = tomllib.loads(DEFAULT_ROLES["qa.toml"])["allowed_tools"]
        self.assertTrue(permitted("Bash", {"command": "pytest -q"}, rules))
        self.assertFalse(permitted("Bash", {"command": "pytest -q; rm -rf /"}, rules))
        self.assertFalse(permitted("Bash", {"command": "git push"}, rules))

    def test_advisory_roles_cannot_edit_code(self):
        """Producto, diseño, datos y soporte entregan texto: tocar código pasa por aprobación."""
        for role in ("producto", "uiux", "datos", "soporte"):
            import tomllib
            rules = tomllib.loads(DEFAULT_ROLES[f"{role}.toml"])["allowed_tools"]
            for tool in ("Edit", "Write", "Bash"):
                self.assertFalse(permitted_tool(tool, rules), f"{role} must ask before {tool}")


def permitted_tool(tool, rules):
    from hivemind.roles import permitted
    return permitted(tool, {"file_path": "/tmp/x", "command": "ls"}, rules)


if __name__ == "__main__":
    unittest.main()
