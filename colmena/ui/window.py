import os

from gi.repository import Adw, Gtk, Pango

from colmena.ui.chat import ChatView
from colmena.ui.client import Client

_STATUS = {"idle": "Inactivo", "queued": "En cola", "working": "Trabajando",
           "waiting": "Esperando aprobación", "error": "Error"}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Colmena", default_width=1100, default_height=720)
        self.agents, self.roles, self.statuses, self.approvals = [], {}, {}, []
        self.views, self.unread = {}, {}
        self.client = Client(self._on_event, self._on_state)

        self.sidebar_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.connect("row-selected", self._select)
        self.capacity = Gtk.Label(xalign=0, margin_start=12, margin_bottom=8)
        self.capacity.add_css_class("dim-label")

        side_tb = Adw.ToolbarView()
        side_hb = Adw.HeaderBar()
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Nuevo agente")
        add.connect("clicked", self._new_agent)
        side_hb.pack_start(add)
        side_tb.add_top_bar(side_hb)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_box.append(Gtk.ScrolledWindow(vexpand=True, child=self.sidebar_list))
        side_box.append(self.capacity)
        side_tb.set_content(side_box)

        self.stack = Gtk.Stack()
        self.content_hb = Adw.HeaderBar()
        self.delete_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Borrar agente", visible=False)
        self.delete_btn.connect("clicked", self._delete_agent)
        self.content_hb.pack_end(self.delete_btn)
        self.banner = Adw.Banner(title="Daemon detenido", button_label="Iniciar")
        self.banner.connect("button-clicked", lambda *_: os.system("systemctl --user start colmena &"))
        content_tb = Adw.ToolbarView()
        content_tb.add_top_bar(self.content_hb)
        content_tb.add_top_bar(self.banner)
        content_tb.set_content(self.stack)

        split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="Colmena", child=side_tb),
            content=Adw.NavigationPage(title="Chat", child=content_tb))
        self.toast = Adw.ToastOverlay(child=split)
        self.set_content(self.toast)

        # Alt+1 = Grupo, Alt+2..9 = agents in sidebar order.
        keys = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
        for i in range(1, 10):
            keys.add_shortcut(Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string(f"<Alt>{i}"),
                action=Gtk.CallbackAction.new(lambda *_a, i=i: self._select_index(i - 1))))
        self.add_controller(keys)
        self.client.connect()

    def _select_index(self, i):
        if (row := self.sidebar_list.get_row_at_index(i)):
            self.sidebar_list.select_row(row)
        return True

    # connection -------------------------------------------------------------
    def _on_state(self, connected):
        self.banner.set_revealed(not connected)
        if connected:
            self.client.call("hello", None, self._hello)

    def _hello(self, snap, err):
        if err:
            return
        self.agents, self.roles = snap["agents"], snap["roles"]
        self.statuses, self.approvals = snap["statuses"], snap["approvals"]
        self._set_capacity(snap["capacity"])
        self._rebuild_sidebar()
        for view in self.views.values():
            view.load(self.approvals)

    def _names(self):
        return {a["id"]: a["name"] for a in self.agents}

    # sidebar ----------------------------------------------------------------
    def _row(self, thread, title, subtitle):
        row = Gtk.ListBoxRow()
        row.thread = thread
        box = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        dot = Gtk.Label(label="●")
        dot.add_css_class(f"colmena-dot-{self.statuses.get(thread, 'idle')}")
        box.append(dot)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        texts.append(Gtk.Label(label=title, xalign=0, ellipsize=Pango.EllipsizeMode.END))
        sub = Gtk.Label(label=subtitle, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        sub.add_css_class("dim-label")
        texts.append(sub)
        box.append(texts)
        if self.unread.get(thread):
            badge = Gtk.Label(label=str(self.unread[thread]))
            badge.add_css_class("accent")
            box.append(badge)
        row.set_child(box)
        return row

    def _rebuild_sidebar(self):
        selected = self.sidebar_list.get_selected_row()
        keep = selected.thread if selected else "group"
        self.sidebar_list.remove_all()
        self.sidebar_list.append(self._row("group", "Grupo", "Todos los agentes"))
        for a in self.agents:
            role = self.roles.get(a["role"], {}).get("label", a["role"])
            self.sidebar_list.append(self._row(a["id"], a["name"], f"{role} · {_STATUS[self.statuses.get(a['id'], 'idle')]}"))
        i = 0
        while (row := self.sidebar_list.get_row_at_index(i)):
            if row.thread == keep:
                self.sidebar_list.select_row(row)
            i += 1

    def _select(self, _list, row):
        if row is None:
            return
        thread = row.thread
        if thread not in self.views:
            view = ChatView(self.client, thread, self._names())
            self.views[thread] = view
            self.stack.add_named(view, thread)
            view.load(self.approvals)
        self.stack.set_visible_child_name(thread)
        self.views[thread].entry.grab_focus()
        self.delete_btn.set_visible(thread != "group")
        name = "Grupo" if thread == "group" else self._names().get(thread, "")
        self.content_hb.set_title_widget(Adw.WindowTitle(title=name))
        if self.unread.pop(thread, None):
            self._rebuild_sidebar()

    def _set_capacity(self, cap):
        self.capacity.set_label(f"{cap['running']}/{cap['max']} activos")

    # events -----------------------------------------------------------------
    def _current(self):
        row = self.sidebar_list.get_selected_row()
        return row.thread if row else None

    def _on_event(self, ev):
        t = ev["type"]
        if t == "agents":
            self.agents = ev["agents"]
            for v in self.views.values():
                v.set_names(self._names())
            self._rebuild_sidebar()
        elif t == "status":
            self.statuses[ev["agent"]] = ev["status"]
            self._rebuild_sidebar()
        elif t == "capacity":
            self._set_capacity(ev)
        elif t == "approval":
            self.approvals.append(ev["approval"])
        elif t == "approval_resolved":
            self.approvals = [a for a in self.approvals if a["id"] != ev["id"]]
        elif t == "message":
            thread = ev["message"]["thread"]
            if thread != self._current() and ev["message"]["kind"] == "text":
                self.unread[thread] = self.unread.get(thread, 0) + 1
                self._rebuild_sidebar()
        for view in self.views.values():
            view.on_event(ev)

    # dialogs ----------------------------------------------------------------
    def _new_agent(self, *_):
        dialog = Adw.AlertDialog(heading="Nuevo agente")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(placeholder_text="Nombre (sin espacios), p. ej. Dev")
        roles = list(self.roles)
        role = Gtk.DropDown.new_from_strings([self.roles[r]["label"] for r in roles])
        cwd = Gtk.Entry(placeholder_text="Carpeta de trabajo (vacío = la del rol)")
        for w in (name, role, cwd):
            box.append(w)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("create", "Crear")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def done(_d, response):
            if response != "create":
                return
            params = {"name": name.get_text().strip(), "role": roles[role.get_selected()]}
            if cwd.get_text().strip():
                params["cwd"] = cwd.get_text().strip()
            self.client.call("create_agent", params,
                             lambda res, err: err and self.toast.add_toast(Adw.Toast(title=err)))

        dialog.connect("response", done)
        dialog.present(self)

    def _delete_agent(self, *_):
        thread = self._current()
        if not thread or thread == "group":
            return
        dialog = Adw.AlertDialog(heading=f"¿Borrar a {self._names().get(thread)}?",
                                 body="Se detiene su trabajo y se borra de la lista. El historial queda guardado.")
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("delete", "Borrar")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(_d, response):
            if response == "delete":
                view = self.views.pop(thread, None)
                if view:
                    self.stack.remove(view)
                self.client.call("delete_agent", {"agent": thread})

        dialog.connect("response", done)
        dialog.present(self)
