"""The @mention being typed in the composer, and the agent names that complete it."""
import re

# An "@" that starts a word (not an email), followed by the name typed so far, right at the cursor.
_TYPING = re.compile(r"(?<![\w@])@([\w-]*)$")


def mention_at(text, cursor):
    """(start offset of "@", prefix typed) if the cursor is inside an unfinished mention."""
    m = _TYPING.search(text[:cursor])
    return (m.start(), m.group(1)) if m else None


def complete(names, prefix):
    p = prefix.casefold()
    return [n for n in names if n.casefold().startswith(p)]
