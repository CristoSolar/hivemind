"""Which bee frame to show for an agent status at a given animation tick.

Pure data so the GTK window and the QML bar widget (Panel.qml mirrors it) animate the same way.
Frames: "up" (wings up), "down" (wings back, the other half of a flap), "low" (up, one pixel lower).
"""
TICK_MS = 125

_BOB = [("up", 1.0)] * 6 + [("low", 1.0)] * 6
SEQUENCES = {
    # Floats up and down, with a quick double flap every few seconds.
    "idle": _BOB + _BOB + [("down", 1.0), ("up", 1.0), ("down", 1.0), ("up", 1.0)],
    "queued": _BOB,
    "working": [("up", 1.0), ("down", 1.0)],
    "waiting": [("up", 1.0)] * 4 + [("up", 0.35)] * 4,
    "error": [("up", 1.0)],
}


def frame_for(status, tick, offset=0):
    seq = SEQUENCES.get(status, SEQUENCES["error"])
    return seq[(tick + offset) % len(seq)]
