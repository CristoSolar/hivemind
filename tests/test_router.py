import unittest

from colmena.router import NAME_RE, mentions

NAMES = ["Dev", "Marketing", "Señor-Ops"]


class RouterTest(unittest.TestCase):
    def test_basic_case_insensitive_dedup_order(self):
        self.assertEqual(mentions("@marketing y @Dev, luego @DEV", NAMES), (["Marketing", "Dev"], []))

    def test_unicode_and_dash(self):
        self.assertEqual(mentions("hola @señor-ops.", NAMES), (["Señor-Ops"], []))

    def test_exclude_self(self):
        self.assertEqual(mentions("@Dev @Marketing", NAMES, exclude="Dev"), (["Marketing"], []))

    def test_unknown(self):
        self.assertEqual(mentions("@Nadie @Dev", NAMES), (["Dev"], ["Nadie"]))

    def test_email_ignored(self):
        self.assertEqual(mentions("escribe a soporte@dev.com", NAMES), ([], []))

    def test_code_block_ignored(self):
        self.assertEqual(mentions("mira:\n```\n@Dev\n```\nlisto", NAMES), ([], []))

    def test_unicode_case_insensitive(self):
        self.assertEqual(mentions("@óscar hola", ["Óscar"]), (["Óscar"], []))

    def test_name_validation(self):
        self.assertTrue(NAME_RE.match("Señor-Ops"))
        self.assertFalse(NAME_RE.match("con espacio"))
        self.assertFalse(NAME_RE.match(""))

    def test_user_mention_is_not_unknown(self):
        self.assertEqual(mentions("@Usuario ¿apruebas? @Dev", NAMES), (["Dev"], []))


if __name__ == "__main__":
    unittest.main()
