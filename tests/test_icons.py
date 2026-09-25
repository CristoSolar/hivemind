import re
import unittest
from pathlib import Path

import tools.pixel_icons as px

ICONS = Path("colmena/ui/icons")


class IconsTest(unittest.TestCase):
    def test_grids_are_16x16(self):
        for grid in (px.BEE, px.HEX):
            rows = grid.strip("\n").split("\n")
            self.assertEqual(len(rows), 16)
            self.assertTrue(all(len(r) == 16 for r in rows))

    def test_committed_svgs_match_generator(self):
        self.assertEqual((ICONS / "bee.svg").read_text(), px.svg(px.BEE))
        self.assertEqual((ICONS / "colmena.svg").read_text(), px.svg(px.HEX))

    def test_svg_is_crisp_pixel_art(self):
        out = px.svg(px.BEE)
        self.assertIn('viewBox="0 0 16 16"', out)
        self.assertIn('shape-rendering="crispEdges"', out)
        self.assertTrue(re.search(r'<rect x="\d+" y="\d+" width="1" height="1"', out))

    def test_mask_shape(self):
        rows = px.mask(px.BEE).split("\n")
        self.assertEqual(len(rows), 16)
        self.assertTrue(set("".join(rows)) <= {"#", "."})


if __name__ == "__main__":
    unittest.main()
