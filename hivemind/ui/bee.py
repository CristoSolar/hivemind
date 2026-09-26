import time
import zlib

from gi.repository import GLib, Gtk

from hivemind.ui.bee_frames import TICK_MS, animation, frame_for

# One shared clock for every bee on screen. The set holds strong references, but only
# while a bee is mapped: sidebar rows are rebuilt often and nothing in Python keeps them,
# so a weak registry lost them and the animation never ran.
_visible = set()
_clock = {"tick": 0, "source": None}


def _step():
    _clock["tick"] += 1
    for bee in list(_visible):
        bee.render()
    if not _visible:
        _clock["source"] = None
        return False  # nothing on screen: stop until a bee is mapped again
    return True


class AnimatedBee(Gtk.Image):
    """Pixel bee that takes its colour from the theme and animates by agent status."""

    def __init__(self, status="idle", seed="", size=32, activity=None, last_active=None, tint=None):
        super().__init__(pixel_size=size)
        # The agent's colour shows while it rests; working, waiting and error keep the
        # status colours, because what it is doing matters more than which agent it is.
        if tint is not None:
            self.add_css_class(f"tint-{tint}")
        self.offset = zlib.crc32(seed.encode()) % 28  # desynchronise bees in the same list
        self.status, self.activity, self.last_active = status, activity, last_active or time.time()
        self.key, self.shown = None, None
        self.render()
        self.connect("map", self._on_map)
        self.connect("unmap", lambda *_: _visible.discard(self))

    def _on_map(self, *_):
        _visible.add(self)
        if _clock["source"] is None:
            _clock["source"] = GLib.timeout_add(TICK_MS, _step)

    def set_state(self, status=None, activity=None, last_active=None):
        self.status = status or self.status
        self.activity = activity
        if last_active:
            self.last_active = last_active
        self.render()

    def render(self):
        # The key can change with no event at all: an idle bee falls asleep after SLEEP_AFTER.
        key = animation(self.status, self.activity, time.time() - self.last_active)
        if key != self.key:
            if self.key:
                self.remove_css_class(f"hivemind-bee-{self.key}")
            self.key = key
            self.add_css_class(f"hivemind-bee-{key}")
        frame, opacity = frame_for(key, _clock["tick"], self.offset)
        if (frame, opacity) != self.shown:
            self.shown = (frame, opacity)
            self.set_from_icon_name(f"hivemind-bee-{frame}-symbolic")
            self.set_opacity(opacity)
