import unittest

import re
import tempfile
from pathlib import Path

from hivemind.ui.theme import css, font_size

COLORS = {"mode": "dark", "accent": "#89b4fa", "background": "#1e1e2e", "foreground": "#cdd6f4",
          "lighter_background": "#313244", "muted": "#585b70", "red": "#f38ba8",
          "green": "#a6e3a1", "yellow": "#f9e2af"}


class ThemeTest(unittest.TestCase):
    def test_css_uses_theme_colors(self):
        out = css(COLORS)
        for key in ("#89b4fa", "#1e1e2e", "#313244", "#f38ba8", "#a6e3a1"):
            self.assertIn(key, out)
        self.assertIn(".hivemind-dot-waiting", out)

    def test_css_with_missing_keys_falls_back(self):
        out = css({"background": "#000000"})
        self.assertIn("#000000", out)

    def test_omarchy_font_square_corners_accent_borders(self):
        out = css(COLORS, size=15)
        self.assertIn('"JetBrainsMono Nerd Font"', out)
        self.assertIn("font-size: 15px", out)
        radii = set(re.findall(r"border-radius:\s*([^;]+);", out))
        self.assertEqual(radii, {"0"})
        self.assertRegex(out, r"\.hivemind-bubble-user \{[^}]*border: 2px solid #89b4fa")
        self.assertRegex(out, r"\.hivemind-bubble-agent \{[^}]*border: 2px solid #585b70")

    def test_font_size_from_shell_toml(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "shell.toml"
            self.assertEqual(font_size(f), 14)  # missing file: Omarchy default
            f.write_text("[font]\nbase-size = 17\n")
            self.assertEqual(font_size(f), 17)
            f.write_text("roto = = =")
            self.assertEqual(font_size(f), 14)


if __name__ == "__main__":
    unittest.main()
