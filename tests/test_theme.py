import unittest

import re
import tempfile
from pathlib import Path

from hivemind.ui.theme import AGENT_TINTS, css, font_size, tints

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

    def test_lists_switches_and_dialogs_follow_the_theme(self):
        out = css(COLORS)
        self.assertRegex(out, r"switch:checked \{\{?[^}]*background(-color)?: #89b4fa")
        self.assertRegex(out, r"list\.hivemind-cards \{[^}]*background: transparent")
        self.assertRegex(out, r"dialog\.alert[^{]*\{[^}]*border: 2px solid #89b4fa")


if __name__ == "__main__":
    unittest.main()


class TintTest(unittest.TestCase):
    """One colour per agent, derived from the theme so a theme switch carries it along."""

    def test_one_distinct_tint_per_slot(self):
        got = tints(COLORS["accent"])
        self.assertEqual(len(got), AGENT_TINTS)
        self.assertEqual(len(set(got)), AGENT_TINTS, "two agents would look the same")

    def test_no_tint_collides_with_the_accent(self):
        """The accent means "you": an agent must never wear it."""
        self.assertNotIn(COLORS["accent"].lower(), [t.lower() for t in tints(COLORS["accent"])])

    def test_tints_follow_the_theme(self):
        self.assertNotEqual(tints("#89b4fa"), tints("#f38ba8"))

    def test_every_tint_is_a_hex_colour(self):
        for t in tints(COLORS["accent"]):
            self.assertRegex(t, r"^#[0-9a-f]{6}$")

    def test_a_broken_accent_does_not_crash_the_ui(self):
        for bad in ("", "nope", "#12", "#gggggg", None, 42):
            self.assertEqual(len(tints(bad)), AGENT_TINTS)

    def test_css_carries_a_class_per_tint(self):
        out = css(COLORS)
        for i in range(AGENT_TINTS):
            self.assertIn(f".hivemind-bubble-agent.tint-{i}", out)
            self.assertIn(f".hivemind-author.tint-{i}", out)
