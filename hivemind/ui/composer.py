import re

from gi.repository import Gdk, Gtk

from hivemind.ui import theme
from hivemind.ui.mention import complete, mention_at

MAX_HEIGHT = 150  # about six lines; beyond that the box scrolls
_MENTION = re.compile(r"(?<![\w@])@([\w-]+)")


class Composer(Gtk.Box):
    """Multi-line message box: grows downwards, Enter sends, Shift+Enter breaks the line,
    and typing "@" lists the agents that can be mentioned here."""

    def __init__(self, on_send, names=lambda: [], placeholder=""):
        super().__init__(hexpand=True)
        self.on_send, self.names = on_send, names
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False, hexpand=True,
                                 top_margin=7, bottom_margin=7, left_margin=10, right_margin=10)
        self.view.add_css_class("hivemind-composer")
        self.buffer = self.view.get_buffer()
        self.scroll = Gtk.ScrolledWindow(child=self.view, hexpand=True, propagate_natural_height=True,
                                         max_content_height=MAX_HEIGHT,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.add_css_class("hivemind-composer-frame")
        self.hint = Gtk.Label(label=placeholder, xalign=0, margin_start=12, valign=Gtk.Align.CENTER,
                              can_target=False)
        self.hint.add_css_class("dim-label")
        overlay = Gtk.Overlay(child=self.scroll, hexpand=True)
        overlay.add_overlay(self.hint)
        self.append(overlay)

        self.tag = self.buffer.create_tag("mention", weight=700,
                                          foreground=theme.colors().get("accent"))
        self.buffer.connect("changed", self._changed)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", lambda _c, keyval, _code, state: self._on_key(keyval, state))
        self.view.add_controller(keys)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", lambda _l, row: self._accept(row.name))
        self.popover = Gtk.Popover(child=self.list, autohide=False, has_arrow=False,
                                   position=Gtk.PositionType.TOP)
        self.popover.set_parent(self.view)
        self.mention = None  # (start offset, prefix) of the mention being typed

    # public ---------------------------------------------------------------------
    @property
    def text(self):
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, False)

    def grab_focus(self):
        return self.view.grab_focus()

    def send(self):
        text = self.text.strip()
        if text:
            self.buffer.set_text("")
            self.on_send(text)

    def options(self):
        out, row = [], self.list.get_first_child()
        while row:
            out.append(row.name)
            row = row.get_next_sibling()
        return out

    def highlighted(self):
        out, it = [], self.buffer.get_start_iter()
        while True:
            if it.starts_tag(self.tag):  # checked before moving: a mention can start at offset 0
                end = it.copy()
                end.forward_to_tag_toggle(self.tag)
                out.append(self.buffer.get_text(it, end, False))
                it = end
            if not it.forward_to_tag_toggle(self.tag):
                return out

    # behaviour ------------------------------------------------------------------
    def _on_key(self, keyval, state):
        if self.popover.get_visible():
            if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
                self._move(1 if keyval == Gdk.KEY_Down else -1)
                return True
            if keyval in (Gdk.KEY_Tab, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                row = self.list.get_selected_row()
                if row:
                    self._accept(row.name)
                return True
            if keyval == Gdk.KEY_Escape:
                self.popover.popdown()
                return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not state & Gdk.ModifierType.SHIFT_MASK:
            self.send()
            return True
        return False  # Shift+Enter and everything else: normal typing

    def _changed(self, *_):
        text = self.text
        self.hint.set_visible(not text)
        self._highlight(text)
        cursor = self.buffer.get_property("cursor-position")
        self.mention = mention_at(text, cursor)
        matches = complete(self.names(), self.mention[1]) if self.mention else []
        if not matches:
            self.popover.popdown()
            return
        self.list.remove_all()
        for name in matches:
            row = Gtk.ListBoxRow()
            row.name = name
            row.set_child(Gtk.Label(label="@" + name, xalign=0, margin_start=8, margin_end=8,
                                    margin_top=4, margin_bottom=4))
            self.list.append(row)
        self.list.select_row(self.list.get_row_at_index(0))
        rect = self.view.get_iter_location(self.buffer.get_iter_at_offset(self.mention[0]))
        x, y = self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x, rect.y)
        rect.x, rect.y = x, y
        self.popover.set_pointing_to(rect)
        self.popover.popup()

    def _move(self, delta):
        row = self.list.get_selected_row()
        index = (row.get_index() if row else -1) + delta
        target = self.list.get_row_at_index(max(0, min(index, len(self.options()) - 1)))
        if target:
            self.list.select_row(target)

    def _accept(self, name):
        if not self.mention:
            return
        start = self.buffer.get_iter_at_offset(self.mention[0])
        end = self.buffer.get_iter_at_offset(self.buffer.get_property("cursor-position"))
        self.buffer.delete(start, end)
        self.buffer.insert(start, f"@{name} ")
        self.popover.popdown()
        self.view.grab_focus()

    def _highlight(self, text):
        start, end = self.buffer.get_bounds()
        self.buffer.remove_tag(self.tag, start, end)
        known = {n.casefold() for n in self.names()}
        for m in _MENTION.finditer(text):
            if m.group(1).casefold() in known:
                self.buffer.apply_tag(self.tag, self.buffer.get_iter_at_offset(m.start()),
                                      self.buffer.get_iter_at_offset(m.end()))
