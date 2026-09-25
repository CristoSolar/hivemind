import zlib

from gi.repository import GLib, Gtk

from hivemind.ui.bee_frames import TICK_MS, frame_for

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

    def __init__(self, status="idle", seed="", size=32):
        super().__init__(pixel_size=size)
        self.offset = zlib.crc32(seed.encode()) % 28  # desynchronise bees in the same list
        self.status, self.shown = None, None
        self.set_status(status)
        self.connect("map", self._on_map)
        self.connect("unmap", lambda *_: _visible.discard(self))

    def _on_map(self, *_):
        _visible.add(self)
        if _clock["source"] is None:
            _clock["source"] = GLib.timeout_add(TICK_MS, _step)

    def set_status(self, status):
        if status == self.status:
            return
        if self.status:
            self.remove_css_class(f"hivemind-bee-{self.status}")
        self.status = status
        self.add_css_class(f"hivemind-bee-{status}")
        self.render()

    def render(self):
        frame, opacity = frame_for(self.status, _clock["tick"], self.offset)
        if (frame, opacity) != self.shown:
            self.shown = (frame, opacity)
            self.set_from_icon_name(f"hivemind-bee-{frame}-symbolic")
            self.set_opacity(opacity)
