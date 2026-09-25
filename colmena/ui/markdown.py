import re
from html import escape

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![\w*])[*_](?!\s)(.+?)(?<!\s)[*_](?![\w*])")


def _inline(line):
    parts = _CODE.split(line)
    out = []
    for i, part in enumerate(parts):
        part = escape(part, quote=False)
        if i % 2:
            out.append(f"<tt>{part}</tt>")
        else:
            out.append(_ITAL.sub(r"<i>\1</i>", _BOLD.sub(r"<b>\1</b>", part)))
    return "".join(out)


def _line(line):
    if m := re.match(r"(#{1,6})\s+(.*)", line):
        return f'<span size="large"><b>{_inline(m[2])}</b></span>'
    if m := re.match(r"\s*[-*]\s+(.*)", line):
        return "• " + _inline(m[1])
    return _inline(line)


def segments(md):
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
            para.append(_line(line))
    if code is not None:
        out.append(("code", lang, "\n".join(code)))
    flush()
    return out
