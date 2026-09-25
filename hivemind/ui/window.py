import os

from gi.repository import Adw, Gtk, Pango

from hivemind.ui.board import BoardView
from hivemind.ui.chat import ChatView
from hivemind.ui.client import Client
from hivemind.ui.dialogs import agent_dialog, model_label, preferences_dialog
from hivemind.ui.routines import RoutinesView
from hivemind.ui.bee import AnimatedBee


_STATUS = {"idle": "Inactivo", "queued": "En cola", "working": "Trabajando",
           "waiting": "Esperando aprobación", "error": "Error"}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="HiveMind", default_width=1100, default_height=720)
        self.agents, self.roles, self.statuses, self.approvals = [], {}, {}, []
        self.routines, self.tasks = [], []
        self.activities, self.last_active, self.bees = {}, {}, {}
        self.views, self.unread = {}, {}
        self.client = Client(self._on_event, self._on_state)

        self.sidebar_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.connect("row-selected", self._select)
        self.capacity = Gtk.Label(xalign=0, margin_start=12, margin_bottom=8)
        self.capacity.add_css_class("dim-label")

        side_tb = Adw.ToolbarView()
        side_hb = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Nuevo agente")
        add.connect("clicked", self._new_agent)
        side_hb.pack_start(add)
        prefs = Gtk.Button(icon_name="open-menu-symbolic", tooltip_text="Preferencias")
        prefs.connect("clicked", self._preferences)
        side_hb.pack_end(prefs)
        side_tb.add_top_bar(side_hb)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side_box.append(Gtk.ScrolledWindow(vexpand=True, child=self.sidebar_list))
        side_box.append(self.capacity)
        side_tb.set_content(side_box)

        self.stack = Gtk.Stack()
        self.content_hb = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        self.delete_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Borrar agente", visible=False)
        self.delete_btn.connect("clicked", self._delete_agent)
        self.content_hb.pack_end(self.delete_btn)
        self.settings_btn = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Ajustes del agente",
                                       visible=False)
        self.settings_btn.connect("clicked", self._edit_agent)
        self.content_hb.pack_end(self.settings_btn)
        self.banner = Adw.Banner(title="Daemon detenido", button_label="Iniciar")
        self.banner.connect("button-clicked", lambda *_: os.system("systemctl --user start hivemind &"))
        content_tb = Adw.ToolbarView()
        content_tb.add_top_bar(self.content_hb)
        # The banner lives above the content, not in the top bar: a hidden banner there still
        # pushed the header bar down and misaligned it with the sidebar's.
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(self.banner)
        self.stack.set_vexpand(True)
        content_box.append(self.stack)
        content_tb.set_content(content_box)

        split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="HiveMind", child=side_tb),
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
        self.routines, self.tasks = snap.get("routines", []), snap.get("tasks", [])
        self.activities, self.last_active = snap.get("activities", {}), snap.get("last_active", {})
        self._set_capacity(snap["capacity"])
        self._rebuild_sidebar()
        for thread, view in self.views.items():
            if thread == "routines":
                view.load(self.routines)
            elif thread == "board":
                view.load(self.tasks)
            else:
                view.load(self.approvals)

    def _names(self):
        return {a["id"]: a["name"] for a in self.agents}

    # sidebar ----------------------------------------------------------------
    def _row(self, thread, title, subtitle):
        row = Gtk.ListBoxRow()
        row.thread = thread
        box = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        if thread in ("routines", "board"):
            avatar = Gtk.Image(icon_name="alarm-symbolic" if thread == "routines" else "view-grid-symbolic",
                               pixel_size=24, width_request=32)
        elif thread == "group":
            avatar = Gtk.Image(icon_name="hivemind-hex-symbolic", pixel_size=32)
        else:
            avatar = AnimatedBee(self.statuses.get(thread, "idle"), seed=thread,
                                 activity=self.activities.get(thread), last_active=self.last_active.get(thread))
            self.bees[thread] = avatar
        box.append(avatar)
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
        self.bees = {}
        self.sidebar_list.append(self._row("group", "Grupo", "Todos los agentes"))
        self.sidebar_list.append(self._row("routines", "Rutinas", f"{len(self.routines)} programadas"))
        self.sidebar_list.append(self._row("board", "Tablero", f"{sum(t['status'] != 'done' for t in self.tasks)} abiertas"))
        for a in self.agents:
            role = self.roles.get(a["role"], {}).get("label", a["role"])
            status = _STATUS[self.statuses.get(a["id"], "idle")]
            self.sidebar_list.append(self._row(a["id"], a["name"], f"{role} · {model_label(a.get('model'))} · {status}"))
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
            if thread == "routines":
                view = RoutinesView(self)
                view.load(self.routines)
            elif thread == "board":
                view = BoardView(self)
                view.load(self.tasks)
            else:
                view = ChatView(self.client, thread, self._names())
                view.load(self.approvals)
            self.views[thread] = view
            self.stack.add_named(view, thread)
        self.stack.set_visible_child_name(thread)
        if hasattr(self.views[thread], "entry"):
            self.views[thread].entry.grab_focus()
        special = thread in ("group", "routines", "board")
        self.delete_btn.set_visible(not special)
        self.settings_btn.set_visible(not special)
        name = {"group": "Grupo", "routines": "Rutinas", "board": "Tablero"}.get(thread) or self._names().get(thread, "")
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
        elif t == "activity":
            if ev["activity"]:
                self.activities[ev["agent"]] = ev["activity"]
            else:
                self.activities.pop(ev["agent"], None)
            if ev.get("last_active"):
                self.last_active[ev["agent"]] = ev["last_active"]
            if (bee := self.bees.get(ev["agent"])):  # update in place: no sidebar rebuild per tool call
                bee.set_state(activity=ev["activity"], last_active=ev.get("last_active"))
        elif t == "status":
            self.statuses[ev["agent"]] = ev["status"]
            self._rebuild_sidebar()
        elif t == "routines":
            self.routines = ev["routines"]
            self._rebuild_sidebar()
        elif t == "tasks":
            self.tasks = ev["tasks"]
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
    def _toast_error(self, res, err):
        if err:
            self.toast.add_toast(Adw.Toast(title=err))

    def _new_agent(self, *_):
        agent_dialog(self, self.roles, lambda p: self.client.call("create_agent", p, self._toast_error))

    def _edit_agent(self, *_):
        agent = next((a for a in self.agents if a["id"] == self._current()), None)
        if agent:
            agent_dialog(self, self.roles, lambda p: self.client.call(
                "update_agent", {"agent": agent["id"], **p}, self._toast_error), agent)

    def _preferences(self, *_):
        def opened(settings, err):
            if err:
                return self._toast_error(None, err)
            preferences_dialog(self, settings, lambda p: self.client.call("set_settings", p, lambda res, e: (
                self._toast_error(res, e) if e else self.toast.add_toast(Adw.Toast(title="Preferencias guardadas")))))
        self.client.call("get_settings", None, opened)

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
