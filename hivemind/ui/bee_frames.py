"""Which bee frame to show for an agent at a given animation tick.

Pure data so the GTK window and the QML bar widget (Panel.qml mirrors it) animate the same way.
Each frame is an icon from tools/icons.py; each entry is (frame, opacity).
"""
TICK_MS = 125
SLEEP_AFTER = 300  # seconds idle before the bee falls asleep

_BOB = [("up", 1.0)] * 6 + [("low", 1.0)] * 6
SEQUENCES = {
    # Floats up and down, with a quick double flap every few seconds.
    "idle": _BOB + _BOB + [("down", 1.0), ("up", 1.0), ("down", 1.0), ("up", 1.0)],
    "queued": _BOB,
    "thinking": [("think-up", 1.0)] * 3 + [("think-down", 1.0)] * 3,  # glasses on, slow beat
    "tool": [("up", 1.0), ("down", 1.0)],                              # busy, fast beat
    "waiting": [("wait", 1.0)] * 4 + [("wait", 0.35)] * 4,
    "sleeping": [("sleep-1", 1.0)] * 8 + [("sleep-2", 1.0)] * 8,
    "error": [("error", 1.0)],
}
SEQUENCES["working"] = SEQUENCES["tool"]


def animation(status, activity, idle_seconds):
    """Map an agent's status, what it is doing, and how long it has been idle to a sequence."""
    if status == "working":
        return "thinking" if activity == "thinking" else "tool"
    if status == "idle" and idle_seconds >= SLEEP_AFTER:
        return "sleeping"
    return status


def frame_for(key, tick, offset=0):
    seq = SEQUENCES.get(key)
    if seq is None:
        return ("up", 1.0)
    return seq[(tick + offset) % len(seq)]
