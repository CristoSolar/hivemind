"""Colmena icons in the style of Kiro's ghost: one smooth monochrome silhouette,
with eyes and stripes cut out as holes.

Every shape is a filled path (no strokes), so GTK can recolour the *-symbolic icons
from the theme, and Panel.qml tints the same files with MultiEffect. Run
`python tools/icons.py` to regenerate colmena/ui/icons/.
"""
import math
from pathlib import Path

SYMBOLIC = "#bebebe"   # GTK replaces this with the theme colour for *-symbolic icons
APP_COLOR = "#e6e6e6"  # launcher icon: neutral light, reads on dark and light menus


def _oval(cx, cy, rx, ry, deg=0, n=48):
    a = math.radians(deg)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
    return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"


def _wing(cx, cy, rx, ry, deg):
    # An outlined wing reads as translucent in a single colour.
    return _oval(cx, cy, rx, ry, deg) + " " + _oval(cx, cy, rx - 2.2, ry - 2.2, deg)


def _antenna(x0, y0, x1, y1, bend, w=0.9):
    mx, my = (x0 + x1) / 2 + bend, (y0 + y1) / 2
    return (f"M{x0 - w},{y0} Q{mx - w},{my} {x1 - w},{y1} L{x1 + w},{y1} Q{mx + w},{my} {x0 + w},{y0} Z "
            + _oval(x1, y1, 2.3, 2.3))


_BODY = ("M12,40 C12,27 22,22 34,22 C48,22 56,29 56,38 C56,48 47,53 34,53 "
         "C24,53 17,50 13,45 L7,43 Z")
_EYES = _oval(42.5, 35, 2.7, 4) + " " + _oval(49.5, 35, 2.7, 4)
_STRIPES = ("M22.6,25.2 C19.8,32 19.8,44 23.2,51.2 L26.4,51.9 C23.2,44.5 23.2,31.5 25.8,24.2 Z "
            "M29.8,23.2 C27.2,31 27.2,45 30.2,52.3 L33.4,52.6 C30.4,45 30.4,31 33,22.9 Z")
_WINGS = {
    "up": _wing(22.5, 12.5, 5.2, 9, -22) + " " + _wing(33.5, 12, 4.6, 8, 12),
    "down": _wing(14.5, 19, 8.5, 4.4, -28) + " " + _wing(27.5, 14.5, 6.5, 3.8, -58),
}


def bee(frame):
    wings, dy = ("down", 0) if frame == "down" else ("up", 2 if frame == "low" else 0)
    return (f'<g transform="translate(0,{dy})">'
            f'<path fill-rule="evenodd" d="{_BODY} {_EYES} {_STRIPES}"/>'
            f'<path fill-rule="evenodd" d="{_WINGS[wings]}"/>'
            f'<path d="{_antenna(46, 24, 50, 12, 3)}"/>'
            f'<path d="{_antenna(41, 23.5, 41, 11, -3)}"/></g>')


def _rounded_hex(cx, cy, r, rad):
    pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]

    def toward(a, b, t):
        length = math.dist(a, b)
        return b[0] + (a[0] - b[0]) * t / length, b[1] + (a[1] - b[1]) * t / length

    d = ""
    for i in range(6):
        prev, corner, nxt = pts[i - 1], pts[i], pts[(i + 1) % 6]
        s, e = toward(prev, corner, rad), toward(nxt, corner, rad)
        d += ("M" if i == 0 else "L") + f"{s[0]:.2f},{s[1]:.2f} Q{corner[0]:.2f},{corner[1]:.2f} {e[0]:.2f},{e[1]:.2f} "
    return d + "Z"


def hive():
    eyes = _oval(26, 33, 3, 4.6) + " " + _oval(38, 33, 3, 4.6)
    return f'<path fill-rule="evenodd" d="{_rounded_hex(32, 33, 27, 7)} {eyes}"/>'


FRAMES = ("up", "down", "low")


def svg(inner, color=SYMBOLIC):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="{color}">{inner}</svg>\n'


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "colmena" / "ui" / "icons"
    for old in out.glob("*.svg"):
        old.unlink()
    for name in FRAMES:
        (out / f"colmena-bee-{name}-symbolic.svg").write_text(svg(bee(name)))
    (out / "colmena-hex-symbolic.svg").write_text(svg(hive()))
    (out / "colmena.svg").write_text(svg(hive(), APP_COLOR))
    print("wrote", sorted(p.name for p in out.glob("*.svg")))
