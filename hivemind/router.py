import re

MAX_HOPS = 5
USER_NAMES = {"usuario", "user"}
CONTEXT_MESSAGES = 20
NAME_RE = re.compile(r"^[\w-]+$")
_MENTION = re.compile(r"(?<![\w@])@([\w-]+)")
_FENCE = re.compile(r"```.*?(```|$)", re.S)


def mentions(text, names, exclude=None):
    by_lower = {n.lower(): n for n in names}
    known, unknown = [], []
    for raw in _MENTION.findall(_FENCE.sub("", text)):
        name = by_lower.get(raw.rstrip("-").lower())
        if name is None and raw.lower() in USER_NAMES:
            continue  # agents address the human as @Usuario
        if name is None:
            if raw not in unknown:
                unknown.append(raw)
        elif name != exclude and name not in known:
            known.append(name)
    return known, unknown
