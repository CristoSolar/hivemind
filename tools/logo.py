"""HiveMind wordmark: the hive icon plus "HiveMind" in Sora ("Hive" Bold, "Mind" Regular), outlined to SVG paths.

Dev-only tool (the generated files in docs/brand/ are committed). Needs fontTools and the
Sora variable font (OFL, https://github.com/google/fonts/tree/main/ofl/sora):

    pip install fonttools
    curl -LO "https://github.com/google/fonts/raw/main/ofl/sora/Sora%5Bwght%5D.ttf"
    python tools/logo.py "Sora[wght].ttf" docs/brand
"""
import math, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
import tools.icons as I

_cache = {}
def font(weight):  # noqa: D103
    if weight not in _cache:
        _cache[weight] = instantiateVariableFont(TTFont(FONT), {"wght": weight})
    return _cache[weight]

def text_path(text, weight, size, x0, baseline, tracking=0.0):
    """Outline `text` in Sora at `weight`; returns (svg path d, advance width)."""
    f = font(weight)
    upem = f["head"].unitsPerEm
    scale = size / upem
    cmap, gs, hmtx = f.getBestCmap(), f.getGlyphSet(), f["hmtx"]
    pen = SVGPathPen(gs)
    x = 0.0
    for ch in text:
        g = cmap[ord(ch)]
        tp = TransformPen(pen, (scale, 0, 0, -scale, x0 + x, baseline))
        gs[g].draw(tp)
        x += hmtx[g][0] * scale + tracking * size
    return pen.getCommands(), x - tracking * size

def hive_icon(x, y, size):
    s = size / 64
    return f'<g transform="translate({x},{y}) scale({s})">{I.hive()}</g>'

def logo(parts, fg, icon_color, bg=None, size=72, gap=22, pad=36):
    icon = size * 1.3
    x = pad + icon + gap
    baseline = pad + icon * 0.5 + size * 0.355
    paths, total = [], 0
    for text, weight in parts:
        d, w = text_path(text, weight, size, x + total, baseline, tracking=-0.02)
        paths.append(d)
        total += w
    W, H = x + total + pad, pad * 2 + icon
    bg_rect = f'<rect width="{W:.0f}" height="{H:.0f}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">'
            f'{bg_rect}<g fill="{icon_color}">{hive_icon(pad, pad, icon)}</g>'
            f'<path fill="{fg}" d="{" ".join(paths)}"/></svg>\n')

variants = {
    "A": [("HiveMind", 600)],
    "B": [("Hive", 700), ("Mind", 400)],
    "C": [("hivemind", 600)],
}

FONT = sys.argv[1] if len(sys.argv) > 1 else "Sora.ttf"

parts = [("Hive", 700), ("Mind", 400)]  # bold "Hive", regular "Mind"
out = sys.argv[2] if len(sys.argv) > 2 else "docs/brand"
__import__("os").makedirs(out, exist_ok=True)
files = {
    "hivemind-logo-dark.svg": logo(parts, "#f2f2f2", "#f5b400"),        # for dark backgrounds
    "hivemind-logo-light.svg": logo(parts, "#15171c", "#f5b400"),       # for light backgrounds
    "hivemind-logo-mono.svg": logo(parts, "currentColor", "currentColor"),
}
for name, svg in files.items():
    open(f"{out}/{name}", "w").write(svg)
icon = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="512" height="512"><g fill="#f5b400">{hive_icon(0, 0, 64)}</g></svg>\n'
open(f"{out}/hivemind-icon.svg", "w").write(icon)
print("wrote", out)
