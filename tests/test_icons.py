import re
import unittest
from pathlib import Path

import tools.pixel_icons as px

ICONS = Path("colmena/ui/icons")


class IconsTest(unittest.TestCase):
    def test_grids_are_16x16(self):
        for grid in px.FRAMES.values():
            rows = grid.strip("\n").split("\n")
            self.assertEqual(len(rows), 16)
            self.assertTrue(all(len(r) == 16 for r in rows))
            self.assertTrue(set("".join(rows)) <= {"#", "."})

    def test_low_frame_is_up_shifted_down(self):
        up = px.FRAMES["up"].strip("\n").split("\n")
        low = px.FRAMES["low"].strip("\n").split("\n")
        self.assertEqual(low, ["." * 16] + up[:-1])

    def test_committed_svgs_match_generator(self):
        for name, grid in px.FRAMES.items():
            self.assertEqual((ICONS / f"colmena-bee-{name}-symbolic.svg").read_text(), px.svg(grid))
        self.assertEqual((ICONS / "colmena-hex-symbolic.svg").read_text(), px.svg(px.HEX))
        self.assertEqual((ICONS / "colmena.svg").read_text(), px.svg(px.HEX, px.APP_COLOR))

    def test_svg_is_crisp_monochrome_pixel_art(self):
        out = px.svg(px.FRAMES["up"])
        self.assertIn('viewBox="0 0 16 16"', out)
        self.assertIn('shape-rendering="crispEdges"', out)
        self.assertEqual(len(set(re.findall(r'fill="([^"]+)"', out))), 1)


if __name__ == "__main__":
    unittest.main()
