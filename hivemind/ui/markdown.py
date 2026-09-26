import re
from html import escape

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MENTION = re.compile(r"(?<![\w@])@([\w-]+)")
_ITAL = re.compile(r"(?<![\w*])[*_](?!\s)(.+?)(?<!\s)[*_](?![\w*])")


def _highlight(part, ctx):
    names, color = ctx
    if not names:
        return part

    def paint(m):
        if m.group(1).casefold() not in names:
            return m.group(0)  # unknown name: left plain, so a typo is visible
        return f'<span foreground="{color}" weight="bold">{m.group(0)}</span>'
    return _MENTION.sub(paint, part)


def _inline(line, ctx=(None, None)):
    parts = _CODE.split(line)
    out = []
    for i, part in enumerate(parts):
        part = escape(part, quote=False)
        if i % 2:
            out.append(f"<tt>{part}</tt>")
        else:
            out.append(_ITAL.sub(r"<i>\1</i>", _BOLD.sub(r"<b>\1</b>", _highlight(part, ctx))))
    return "".join(out)


def _line(line, ctx):
    if m := re.match(r"(#{1,6})\s+(.*)", line):
        return f'<span size="large"><b>{_inline(m[2], ctx)}</b></span>'
    if m := re.match(r"\s*[-*]\s+(.*)", line):
        return "• " + _inline(m[1], ctx)
    return _inline(line, ctx)


def segments(md, mentions=None, mention_color=None):
    """Markdown subset -> [("text", pango) | ("code", lang, code)].

    `mentions`: agent names whose @Name is painted in `mention_color` (bold)."""
    ctx = ({n.casefold() for n in mentions} if mentions else None, mention_color)
    out, para, code, lang = [], [], None, ""

    def flush():
        text = "\n".join(para).strip("\n")
        if text:
            out.append(("text", text))
        para.clear()

    for line in md.split("\n"):
        if code is not None:
            if line.startswith("```"):
                out.append(("code", lang, "\n".join(code)))
                code = None
            else:
                code.append(line)
        elif line.startswith("```"):
            flush()
            code, lang = [], line[3:].strip()
        elif not line.strip():
            flush()
        else:
            para.append(_line(line, ctx))
    if code is not None:
        out.append(("code", lang, "\n".join(code)))
    flush()
    return out
