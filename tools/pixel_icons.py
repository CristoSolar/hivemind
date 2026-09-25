"""8-bit Colmena icons as 16x16 grids: '#' is ink, '.' is transparent.

The bee frames are monochrome GTK "symbolic" icons, so the window recolours them from the
theme; Panel.qml draws the same grids with the shell's colours. Run
`python tools/pixel_icons.py` to regenerate colmena/ui/icons/.
"""
from pathlib import Path

UP = """
................
.....##..##.....
....#..##..#....
....#..##..#....
.....#.##.#.....
......####...#.#
....########..#.
..##.#.#.####.#.
.###.#.#.##.###.
####.#.#.######.
.###.#.#.#####..
..##.#.#.####...
....########....
.....#...#......
................
................
"""

DOWN = """
................
................
................
..####..........
.#....##........
.#......##...#.#
..##....####..#.
....########..#.
..##.#.#.####.#.
.###.#.#.##.###.
####.#.#.######.
.###.#.#.#####..
..##.#.#.####...
....########....
.....#...#......
................
"""

HEX = """
.......##.......
.....##..##.....
...##......##...
.##..........##.
#..............#
#...##....##...#
#...##....##...#
#..............#
#.....#..#.....#
#......##......#
#..............#
#..............#
.##..........##.
...##......##...
.....##..##.....
.......##.......
"""


def _rows(grid):
    return grid.strip("\n").split("\n")


def _shift_down(grid):
    rows = _rows(grid)
    return "\n" + "\n".join(["." * 16] + rows[:-1]) + "\n"


FRAMES = {"up": UP, "down": DOWN, "low": _shift_down(UP)}
SYMBOLIC = "#bebebe"   # GTK replaces this with the theme colour for *-symbolic icons
APP_COLOR = "#e6e6e6"  # launcher icon: neutral light, reads on dark and light menus


def svg(grid, color=SYMBOLIC):
    rects = "".join(f'<rect x="{x}" y="{y}" width="1" height="1"/>'
                    for y, row in enumerate(_rows(grid)) for x, ch in enumerate(row) if ch == "#")
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges"'
            f' fill="{color}">{rects}</svg>\n')


def mask(grid):
    return "\n".join(_rows(grid))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "colmena" / "ui" / "icons"
    for old in out.glob("*.svg"):
        old.unlink()
    for name, grid in FRAMES.items():
        (out / f"colmena-bee-{name}-symbolic.svg").write_text(svg(grid))
    (out / "colmena-hex-symbolic.svg").write_text(svg(HEX))
    (out / "colmena.svg").write_text(svg(HEX, APP_COLOR))
    print("wrote", sorted(p.name for p in out.glob("*.svg")))
