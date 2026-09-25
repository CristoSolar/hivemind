import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from colmena.roles import load_roles, permitted, suggested_rule


class RolesTest(unittest.TestCase):
    def test_defaults_written_and_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            roles = load_roles(Path(d))
            self.assertEqual(set(roles), {"dev", "marketing", "sysadmin"})
            self.assertIn("Read", roles["dev"]["allowed_tools"])
            self.assertTrue((Path(d) / "dev.toml").exists())

    def test_user_edit_kept_and_bad_file_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "dev.toml").write_text('label = "Mío"\nsystem_prompt = "x"\nallowed_tools = []\ncwd = "~"\n')
            (Path(d) / "roto.toml").write_text("esto no es toml = = =")
            roles = load_roles(Path(d))
            self.assertEqual(roles["dev"]["label"], "Mío")
            self.assertEqual(roles["dev"]["cwd"], str(Path.home()))
            self.assertNotIn("roto", roles)

    def test_permitted(self):
        rules = ["Read", "mcp__claude_ai_Gmail__*", "Bash(git status*)", "Edit(/home/u/repo/*)"]
        self.assertTrue(permitted("Read", {"file_path": "/x"}, rules))
        self.assertTrue(permitted("mcp__claude_ai_Gmail__search", {}, rules))
        self.assertTrue(permitted("Bash", {"command": "git status -s"}, rules))
        self.assertFalse(permitted("Bash", {"command": "rm -rf /"}, rules))
        self.assertTrue(permitted("Edit", {"file_path": "/home/u/repo/a.py"}, rules))
        self.assertFalse(permitted("Edit", {"file_path": "/etc/passwd"}, rules))
        self.assertFalse(permitted("Write", {"file_path": "/x"}, rules))

    def test_suggested_rule(self):
        sug = [NS(type="addDirectories", rules=None),
               NS(type="addRules", rules=[NS(tool_name="Bash", rule_content="touch hola.txt")])]
        self.assertEqual(suggested_rule("Bash", sug), "Bash(touch hola.txt)")
        self.assertEqual(suggested_rule("WebFetch", []), "WebFetch")


if __name__ == "__main__":
    unittest.main()
