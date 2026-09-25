import re
import unittest
from pathlib import Path

import tools.icons as icons

ICONS = Path("colmena/ui/icons")


class IconsTest(unittest.TestCase):
    def test_committed_svgs_match_generator(self):
        for name in icons.FRAMES:
            self.assertEqual((ICONS / f"colmena-bee-{name}-symbolic.svg").read_text(), icons.svg(icons.bee(name)))
        self.assertEqual((ICONS / "colmena-hex-symbolic.svg").read_text(), icons.svg(icons.hive()))
        self.assertEqual((ICONS / "colmena.svg").read_text(), icons.svg(icons.hive(), icons.APP_COLOR))

    def test_symbolic_icons_are_single_colour_fills(self):
        for path in ICONS.glob("*-symbolic.svg"):
            text = path.read_text()
            self.assertEqual(set(re.findall(r'fill="([^"]+)"', text)), {icons.SYMBOLIC}, path.name)
            self.assertNotIn("stroke", text, path.name)  # GTK only recolours fills

    def test_frames_differ(self):
        self.assertNotEqual(icons.bee("up"), icons.bee("down"))
        self.assertIn("translate(0,2)", icons.bee("low"))


if __name__ == "__main__":
    unittest.main()
