import unittest

from colmena.ui.theme import css

COLORS = {"mode": "dark", "accent": "#89b4fa", "background": "#1e1e2e", "foreground": "#cdd6f4",
          "lighter_background": "#313244", "muted": "#585b70", "red": "#f38ba8",
          "green": "#a6e3a1", "yellow": "#f9e2af"}


class ThemeTest(unittest.TestCase):
    def test_css_uses_theme_colors(self):
        out = css(COLORS)
        for key in ("#89b4fa", "#1e1e2e", "#313244", "#f38ba8", "#a6e3a1"):
            self.assertIn(key, out)
        self.assertIn(".colmena-dot-waiting", out)

    def test_css_with_missing_keys_falls_back(self):
        out = css({"background": "#000000"})
        self.assertIn("#000000", out)


if __name__ == "__main__":
    unittest.main()
