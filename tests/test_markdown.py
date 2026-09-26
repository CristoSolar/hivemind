import unittest

from hivemind.ui.markdown import segments


class MarkdownTest(unittest.TestCase):
    def test_inline(self):
        self.assertEqual(segments("hola **mundo** y *tú* con `x<y` & _z_"),
                         [("text", "hola <b>mundo</b> y <i>tú</i> con <tt>x&lt;y</tt> &amp; <i>z</i>")])

    def test_code_block_and_paragraphs(self):
        md = "antes\n\n```py\nif a < b:\n    pass\n```\ndespués"
        self.assertEqual(segments(md), [("text", "antes"), ("code", "py", "if a < b:\n    pass"), ("text", "después")])

    def test_lists_and_headings(self):
        self.assertEqual(segments("# Título\n- uno\n* dos\n1. tres"),
                         [("text", '<span size="large"><b>Título</b></span>\n• uno\n• dos\n1. tres')])

    def test_unclosed_fence(self):
        self.assertEqual(segments("```\ncódigo sin cerrar"), [("code", "", "código sin cerrar")])

    def test_stars_inside_code_untouched(self):
        self.assertEqual(segments("`**no**`"), [("text", "<tt>**no**</tt>")])

    def test_known_mentions_are_highlighted(self):
        out = segments("hola @Dev y @nadie, `@Dev` no", mentions={"Dev"}, mention_color="#89b4fa")
        self.assertEqual(out, [("text", 'hola <span foreground="#89b4fa" weight="bold">@Dev</span> y @nadie, '
                                        '<tt>@Dev</tt> no')])

    def test_mentions_match_case_insensitively(self):
        out = segments("@dev listo", mentions={"Dev"}, mention_color="#fff")
        self.assertEqual(out, [("text", '<span foreground="#fff" weight="bold">@dev</span> listo')])

    def test_emails_are_not_mentions(self):
        self.assertEqual(segments("soporte@Dev.cl", mentions={"Dev"}, mention_color="#fff"),
                         [("text", "soporte@Dev.cl")])


if __name__ == "__main__":
    unittest.main()
