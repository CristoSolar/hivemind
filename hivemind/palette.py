"""The colours an agent can wear.

Lives outside `hivemind.ui` because the daemon validates the choice and must never import
the interface: the hue list is data, the rendering of it is not.

The hue is fixed so a name means the same thing in every theme — "Rosa" is always pink —
while saturation and lightness come from the theme accent, so the swatches belong to the
palette the rest of the window is drawn in. That part lives in `hivemind.ui.theme`.
"""

PALETTE = [("Ámbar", 42), ("Coral", 12), ("Rosa", 330), ("Violeta", 272),
           ("Azul", 210), ("Turquesa", 178), ("Menta", 150), ("Lima", 88)]
AGENT_TINTS = len(PALETTE)


def name(tint):
    """What to call a colour in the interface; None means the window picks one."""
    return "Automático" if tint is None else PALETTE[tint][0]


def valid(tint):
    return tint is None or (isinstance(tint, int) and not isinstance(tint, bool)
                            and 0 <= tint < AGENT_TINTS)
