import unittest

from hivemind.ui.mention import complete, mention_at


class MentionAtTest(unittest.TestCase):
    def test_finds_the_word_being_typed(self):
        self.assertEqual(mention_at("hola @De", 8), (5, "De"))
        self.assertEqual(mention_at("@", 1), (0, ""))
        self.assertEqual(mention_at("@Señor-O y más", 8), (0, "Señor-O"))

    def test_ignores_everything_else(self):
        self.assertIsNone(mention_at("hola", 4))
        self.assertIsNone(mention_at("hola @Dev ", 10))       # already finished with a space
        self.assertIsNone(mention_at("soporte@dev", 11))      # an email, not a mention
        self.assertIsNone(mention_at("hola @Dev", 3))         # cursor is not on the mention

    def test_complete_filters_case_insensitively_and_keeps_order(self):
        names = ["Dev", "Desarrollador", "Marketing"]
        self.assertEqual(complete(names, "de"), ["Dev", "Desarrollador"])
        self.assertEqual(complete(names, ""), names)
        self.assertEqual(complete(names, "zz"), [])


if __name__ == "__main__":
    unittest.main()
