from gi.repository import Adw, GLib, Gtk, Pango


COLUMNS = [("todo", "Por hacer"), ("doing", "En curso"), ("done", "Listo")]
ORDER = [c for c, _ in COLUMNS]


class BoardView(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window, self.client = window, window.client
        bar = Gtk.Box(spacing=8, margin_top=10, margin_bottom=6, margin_start=16, margin_end=16)
        hint = Gtk.Label(label="Los agentes también mueven estas tareas", xalign=0, hexpand=True)
        hint.add_css_class("dim-label")
        add = Gtk.Button(label="+ Tarea")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._new())
        bar.append(hint)
        bar.append(add)
        self.append(bar)
        cols = Gtk.Box(spacing=12, homogeneous=True, vexpand=True,
                       margin_start=16, margin_end=16, margin_bottom=12)
        self.columns = {}
        for status, label in COLUMNS:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            head = Gtk.Label(label=label.upper(), xalign=0)
            head.add_css_class("hivemind-author")
            col.append(head)
            cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            col.append(Gtk.ScrolledWindow(vexpand=True, child=cards, hscrollbar_policy=Gtk.PolicyType.NEVER))
            self.columns[status] = cards
            cols.append(col)
        self.append(cols)
        self.tasks = []

    def load(self, tasks):
        self.tasks = tasks
        for cards in self.columns.values():
            while (child := cards.get_first_child()):
                cards.remove(child)
        for t in tasks:
            self.columns[t["status"]].append(self._card(t))

    def _move(self, t, delta):
        i = ORDER.index(t["status"]) + delta
        if 0 <= i < len(ORDER):
            self.client.call("update_task", {"task": t["id"], "status": ORDER[i]}, self.window._toast_error)

    def _card(self, t):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("hivemind-card")
        title = Gtk.Button(child=Gtk.Label(label=t["title"], xalign=0, wrap=True,
                                           wrap_mode=Pango.WrapMode.WORD_CHAR))
        title.add_css_class("flat")
        title.connect("clicked", lambda *_: self._details(t))
        card.append(title)
        row = Gtk.Box(spacing=6)
        who = Gtk.Box(spacing=4, hexpand=True)
        if t["assignee_name"]:
            who.append(Gtk.Image(icon_name="hivemind-bee-up-symbolic", pixel_size=16))
        who.append(Gtk.Label(label=t["assignee_name"] or "sin asignar", xalign=0))
        row.append(who)
        for text, delta in (("◀", -1), ("▶", 1)):
            b = Gtk.Button(label=text, sensitive=0 <= ORDER.index(t["status"]) + delta < len(ORDER))
            b.connect("clicked", lambda _b, d=delta: self._move(t, d))
            row.append(b)
        menu = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Asignar o borrar")
        pop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        for agent_id, label in [(None, "Sin asignar")] + [(a["id"], a["name"]) for a in self.window.agents]:
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, a=agent_id: (menu.popdown(), self.client.call(
                "update_task", {"task": t["id"], "assignee": a or ""}, self.window._toast_error)))
            pop.append(b)
        delete = Gtk.Button(label="Borrar tarea")
        delete.add_css_class("destructive-action")
        delete.connect("clicked", lambda *_: (menu.popdown(), self.client.call(
            "delete_task", {"task": t["id"]}, self.window._toast_error)))
        pop.append(delete)
        menu.set_popover(Gtk.Popover(child=pop))
        row.append(menu)
        card.append(row)
        return card

    def _new(self):
        dialog = Adw.AlertDialog(heading="Nueva tarea")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        title = Gtk.Entry(placeholder_text="Título")
        desc = Gtk.Entry(placeholder_text="Descripción (opcional)")
        people = [(None, "Sin asignar")] + [(a["id"], a["name"]) for a in self.window.agents]
        who = Gtk.DropDown.new_from_strings([label for _, label in people])
        for w in (title, desc, who):
            box.append(w)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("ok", "Crear")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _d, resp: resp == "ok" and self.client.call("create_task", {
            "title": title.get_text(), "description": desc.get_text(),
            "assignee": people[who.get_selected()][0]}, self.window._toast_error))
        dialog.present(self.window)

    def _details(self, t):
        def show(log, err):
            lines = "\n".join(f"• {GLib.markup_escape_text(e['text'])}" for e in (log or []))
            body = (GLib.markup_escape_text(t["description"] or "Sin descripción.") + "\n\n<b>Historial</b>\n" + lines)
            dialog = Adw.AlertDialog(heading=t["title"], body=body, body_use_markup=True)
            dialog.add_response("ok", "Cerrar")
            dialog.present(self.window)
        self.client.call("task_log", {"task": t["id"]}, show)

    def set_names(self, names):
        pass  # names are read from the window on every load

    def on_event(self, ev):
        if ev["type"] == "tasks":
            self.load(ev["tasks"])
        elif ev["type"] == "agents":
            self.load(self.tasks)
