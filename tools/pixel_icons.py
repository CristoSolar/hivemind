"""8-bit chibi icons for Colmena, drawn as 16x16 ASCII grids.

Run `python tools/pixel_icons.py` to regenerate colmena/ui/icons/*.svg.
"""
from pathlib import Path

PALETTE = {"K": "#2b2118", "Y": "#ffd23f", "O": "#e8a200", "W": "#d8f1ff", "w": "#ffffff",
           "P": "#ff8fab", "B": "#2b2118", "H": "#f5b400", "h": "#ffe07a", "D": "#7a4a00"}

BEE = """
...K........K...
....K......K....
.....KKKKKK.....
.WW.KYYYYYYK.WW.
WwWKYYYYYYYYKWwW
WWKYYYYYYYYYYKWW
.KYYwKYYYYwKYYK.
.KYYKKYYYYKKYYK.
.KYPPYYYYYYPPYK.
.KYYYYKYYKYYYYK.
..KYYYYKKYYYYK..
...KKKKKKKKKK...
....KOOOOOOK....
....KBBBBBBK....
.....KOOOOK.....
.......KK.......
"""

HEX = """
.......DD.......
.....DDHHDD.....
...DDHHhhHHDD...
.DDHHhHHHHHHHDD.
DHHHhHHHHHHHHHHD
DHHHHHHHHHHHHHHD
DHHHHHHHHHHHHHHD
DHHHwKHHHHwKHHHD
DHHHKKHHHHKKHHHD
DHHPPHHHHHHPPHHD
DHHHHHKHHKHHHHHD
DHHHHHHKKHHHHHHD
.DDHHHHHHHHHHDD.
...DDHHHHHHDD...
.....DDHHDD.....
.......DD.......
"""


def _rows(grid):
    return grid.strip("\n").split("\n")


def svg(grid):
    rects = [f'<rect x="{x}" y="{y}" width="1" height="1" fill="{PALETTE[ch]}"/>'
             for y, row in enumerate(_rows(grid)) for x, ch in enumerate(row) if ch != "."]
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">'
            + "".join(rects) + "</svg>\n")


def mask(grid):
    return "\n".join("".join("." if ch in ".wW" else "#" for ch in row) for row in _rows(grid))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "colmena" / "ui" / "icons"
    (out / "bee.svg").write_text(svg(BEE))
    (out / "colmena.svg").write_text(svg(HEX))
    print("wrote", out / "bee.svg", out / "colmena.svg")
