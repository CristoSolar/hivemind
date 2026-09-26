import json
from pathlib import Path

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from hivemind.ui import theme
from hivemind.ui.composer import Composer
from hivemind.ui.markdown import segments



def _label(markup, css=None):
    lbl = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0, selectable=True, max_width_chars=90)
    lbl.set_markup(markup)
    if css:
        lbl.add_css_class(css)
    return lbl


def _bubble(text, css, mentions=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class(css)
    for seg in segments(text, mentions=mentions, mention_color=theme.colors()["accent"]):
        if seg[0] == "text":
            box.append(_label(seg[1]))
        else:
            code = Gtk.Label(label=seg[2], xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.CHAR)
            code.add_css_class("hivemind-code")
            box.append(code)
    return box


def _size(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _open(path, widget):
    Gtk.FileLauncher(file=Gio.File.new_for_path(path)).launch(widget.get_root(), None, None)


def _attachment(entry):
    """A thumbnail for images, a chip (icon, name, size) for everything else; click opens it."""
    path, box = entry["path"], Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    button = Gtk.Button(tooltip_text=f"Abrir {entry['name']}", halign=Gtk.Align.START)
    button.add_css_class("flat")
    button.connect("clicked", lambda b: _open(path, b))
    thumb = None
    if entry["kind"] == "imagen":
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 240, 240, True)
            thumb = Gtk.Picture(paintable=Gdk.Texture.new_for_pixbuf(pixbuf), can_shrink=False)
        except GLib.Error:
            thumb = None  # missing or unreadable image: fall back to the chip
    if thumb:
        button.set_child(thumb)
    else:
        chip = Gtk.Box(spacing=8)
        content_type, _ = Gio.content_type_guess(entry["name"], None)
        chip.append(Gtk.Image(gicon=Gio.content_type_get_icon(content_type), pixel_size=24))
        chip.append(Gtk.Label(label=entry["name"], ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=32))
        size = Gtk.Label(label=_size(entry.get("size") or 0))
        size.add_css_class("dim-label")
        chip.append(size)
        button.set_child(chip)
        button.add_css_class("hivemind-attachment")
    box.append(button)
    if entry.get("transcript"):
        text = Gtk.Label(label=entry["transcript"], wrap=True, xalign=0, selectable=True)
        box.append(Gtk.Expander(label="Transcripción", child=text))
    return box


class ChatView(Gtk.Box):
    def __init__(self, client, thread, names, members=None, on_error=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_error = on_error or (lambda res, err: None)
        self.attachment_widgets = []
        self.client, self.thread, self.names = client, thread, names
        self.members = members or (lambda: [])  # names that "@" can complete in this conversation
        self.is_group = thread == "group" or thread.startswith("g-")
        self.tools = {}       # tool_use_id -> Gtk.Expander
        self.cards = {}       # approval_id -> widget
        self.live = None      # label receiving deltas

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                            margin_top=12, margin_bottom=12, margin_start=16, margin_end=16)
        self.scroll = Gtk.ScrolledWindow(vexpand=True, child=self.list, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.append(self.scroll)

        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=10, margin_start=16, margin_end=16,
                      valign=Gtk.Align.END)
        self.entry = Composer(self._send_text, names=self.members if self.is_group else (lambda: []),
                              placeholder=("Escribe a todos… o usa @Nombre para uno solo" if self.is_group
                                           else "Escribe una tarea…  (Shift+Enter: nueva línea)"))
        bar.append(self.entry)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)  # drag files onto the chat
        drop.connect("drop", lambda _t, files, _x, _y: (
            self.entry.add_files([f.get_path() for f in files.get_files() if f.get_path()]), True)[1])
        self.add_controller(drop)
        if not self.is_group:
            self.stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text="Detener")
            self.stop_btn.connect("clicked", lambda *_: client.call("stop", {"agent": thread}))
            bar.append(self.stop_btn)
        send = Gtk.Button(icon_name="mail-send-symbolic", tooltip_text="Enviar")
        send.add_css_class("suggested-action")
        send.connect("clicked", self._send)
        bar.append(send)
        self.append(bar)

    def set_names(self, names):
        self.names = names

    def load(self, approvals=()):
        # Loads can overlap (selecting a chat, then a hello snapshot): only the latest one
        # fills the list, and it clears the list when its answer arrives.
        self.generation = getattr(self, "generation", 0) + 1
        generation = self.generation

        def loaded(res, err):
            if generation != self.generation:
                return
            child = self.list.get_first_child()
            while child:
                self.list.remove(child)
                child = self.list.get_first_child()
            self.tools, self.cards, self.live = {}, {}, None
            self.attachment_widgets = []
            for m in res or []:
                self._message(m)
            for ap in approvals:
                if ap["agent_id"] == self.thread:
                    self._approval(ap)

        self.client.call("history", {"thread": self.thread, "limit": 200}, loaded)

    def _scroll_end(self):
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def _message(self, m):
        if m["kind"] == "tool":
            self._tool(json.loads(m["content"]))
            return
        if self.live is not None:
            self.list.remove(self.live)
        self.live = None
        if m["kind"] == "system":
            self.list.append(_label(GLib.markup_escape_text(m["content"]), "hivemind-system"))
        elif m["author"] == "user":
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.END)
            if m["content"]:
                col.append(_bubble(m["content"], "hivemind-bubble-user", self.names.values()))
            self._attachments(col, m, Gtk.Align.END)
            self.list.append(col)
        else:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.START)
            if self.is_group:
                who = Gtk.Box(spacing=6)
                bee = Gtk.Image(icon_name="hivemind-bee-up-symbolic", pixel_size=22)
                bee.add_css_class("hivemind-bee-queued")
                who.append(bee)
                who.append(_label(GLib.markup_escape_text(self.names.get(m["author"], "?")), "hivemind-author"))
                col.append(who)
            if m["content"]:
                col.append(_bubble(m["content"], "hivemind-bubble-agent", self.names.values()))
            self._attachments(col, m, Gtk.Align.START)
            self.list.append(col)
        self._scroll_end()

    def _attachments(self, col, m, align):
        for entry in m.get("attachments") or []:
            widget = _attachment(entry)
            widget.set_halign(align)
            self.attachment_widgets.append(widget)
            col.append(widget)

    def _tool(self, ev):
        if ev["type"] == "tool":
            summary = ev["input"].get("command") or ev["input"].get("file_path") or json.dumps(ev["input"], ensure_ascii=False)
            exp = Gtk.Expander(label_widget=Gtk.Label(label=f"⚙ {ev['name']}: {summary[:120]}",
                                                      ellipsize=Pango.EllipsizeMode.END, xalign=0))
            exp.add_css_class("hivemind-tool")
            self.tools[ev["id"]] = exp
            self.list.append(exp)
        elif (exp := self.tools.get(ev["id"])):
            out = Gtk.Label(label=ev["content"] or "(sin salida)", xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
            out.add_css_class("hivemind-code")
            exp.set_child(out)
            if ev["is_error"]:
                title = exp.get_label_widget()
                title.set_label(title.get_label() + "  ✗")
        self._scroll_end()

    def _approval(self, ap):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("hivemind-approval")
        detail = ap["input"].get("command") or ap["input"].get("file_path") or json.dumps(ap["input"], ensure_ascii=False)
        card.append(_label(f"<b>Quiere usar {GLib.markup_escape_text(ap['tool'])}</b>"))
        card.append(_label(GLib.markup_escape_text(detail[:600]), "hivemind-code"))
        card.append(_label("«Permitir siempre» guardará: <tt>" + GLib.markup_escape_text(ap["rule"] or ap["tool"]) + "</tt>",
                           "hivemind-system"))
        row = Gtk.Box(spacing=6)
        for text, decision, css in (("Permitir", "allow", "suggested-action"),
                                    ("Denegar", "deny", "destructive-action"),
                                    ("Permitir siempre para este agente", "always", None)):
            btn = Gtk.Button(label=text)
            if css:
                btn.add_css_class(css)
            btn.connect("clicked", lambda _b, d=decision: self.client.call(
                "approve", {"approval": ap["id"], "decision": d}))
            row.append(btn)
        card.append(row)
        self.cards[ap["id"]] = card
        self.list.append(card)
        self._scroll_end()

    def on_event(self, ev):
        t = ev["type"]
        if t == "message" and ev["message"]["thread"] == self.thread:
            self._message(ev["message"])
        elif t == "delta" and ev["thread"] == self.thread:
            if self.live is None:
                self.live = Gtk.Label(wrap=True, xalign=0, halign=Gtk.Align.START)
                self.live.add_css_class("hivemind-bubble-agent")
                self.list.append(self.live)
            self.live.set_label(self.live.get_label() + ev["text"])
            self._scroll_end()
        elif t == "status" and ev["agent"] == self.thread and ev["status"] != "working" and self.live:
            self.list.remove(self.live)
            self.live = None
        elif t == "approval" and ev["approval"]["agent_id"] == self.thread:
            self._approval(ev["approval"])
        elif t == "approval_resolved" and (card := self.cards.pop(ev["id"], None)):
            self.list.remove(card)

    def _send(self, *_):
        self.entry.send()

    def _send_text(self, text, files=()):
        params = {"thread": self.thread, "text": text}
        if files:
            params["attachments"] = list(files)
        self.client.call("send", params, self.on_error)
