import re
import unittest
from pathlib import Path

import tools.icons as icons

ICONS = Path("hivemind/ui/icons")


class IconsTest(unittest.TestCase):
    def test_committed_svgs_match_generator(self):
        for name in icons.FRAMES:
            self.assertEqual((ICONS / f"hivemind-bee-{name}-symbolic.svg").read_text(), icons.svg(icons.bee(name)))
        self.assertEqual((ICONS / "hivemind-hex-symbolic.svg").read_text(), icons.svg(icons.hive()))
        self.assertEqual((ICONS / "hivemind.svg").read_text(), icons.svg(icons.hive(), icons.APP_COLOR))

    def test_symbolic_icons_are_single_colour_fills(self):
        for path in ICONS.glob("*-symbolic.svg"):
            text = path.read_text()
            self.assertEqual(set(re.findall(r'fill="([^"]+)"', text)), {icons.SYMBOLIC}, path.name)
            self.assertNotIn("stroke", text, path.name)  # GTK only recolours fills

    def test_frames_differ(self):
        self.assertEqual(len({icons.bee(f) for f in icons.FRAMES}), len(icons.FRAMES))
        self.assertIn("translate(0,2)", icons.bee("low"))

    def test_every_animation_frame_has_an_icon(self):
        from hivemind.ui.bee_frames import SEQUENCES
        used = {frame for seq in SEQUENCES.values() for frame, _ in seq}
        self.assertLessEqual(used, set(icons.FRAMES))


if __name__ == "__main__":
    unittest.main()
