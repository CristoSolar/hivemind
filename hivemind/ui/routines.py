from gi.repository import Adw, Gtk

from hivemind.schedule import DAYS, describe, short_when

KINDS = [("every_hours", "Cada N horas"), ("daily", "Todos los días"), ("weekly", "Días de la semana")]


class RoutinesView(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window, self.client = window, window.client
        bar = Gtk.Box(spacing=8, margin_top=10, margin_bottom=6, margin_start=16, margin_end=16)
        title = Gtk.Label(label="Tareas que se repiten solas", xalign=0, hexpand=True)
        title.add_css_class("dim-label")
        add = Gtk.Button(label="+ Rutina")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._dialog())
        bar.append(title)
        bar.append(add)
        self.append(bar)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_start=16, margin_end=16)
        self.list.add_css_class("hivemind-cards")
        self.append(Gtk.ScrolledWindow(vexpand=True, child=self.list, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.routines = []

    def _target_name(self, target):
        return "Grupo" if target == "group" else self.window._names().get(target, "?")

    def load(self, routines):
        self.routines = routines
        self.list.remove_all()
        if not routines:
            empty = Gtk.Label(label="Aún no hay rutinas. Crea una con «+ Rutina».", margin_top=24)
            empty.add_css_class("dim-label")
            self.list.append(empty)
        for r in routines:
            self.list.append(self._row(r))

    def _row(self, r):
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        name = Gtk.Label(label=r["name"], xalign=0)
        name.add_css_class("heading")
        texts.append(name)
        sub = Gtk.Label(xalign=0, wrap=True, label=f"{describe(r['schedule'])} · {self._target_name(r['target'])}"
                        f" · próxima: {short_when(r['next_run']) if r['enabled'] else 'pausada'}")
        sub.add_css_class("dim-label")
        texts.append(sub)
        box.append(texts)
        switch = Gtk.Switch(active=r["enabled"], valign=Gtk.Align.CENTER, tooltip_text="Activa o pausa")
        switch.connect("notify::active", lambda s, _p: self.client.call(
            "update_routine", {"routine": r["id"], "enabled": s.get_active()}, self.window._toast_error))
        box.append(switch)
        for icon, tip, fn in (("media-playback-start-symbolic", "Correr ahora",
                               lambda *_: self.client.call("run_routine_now", {"routine": r["id"]},
                                                           self.window._toast_error)),
                              ("document-edit-symbolic", "Editar", lambda *_: self._dialog(r)),
                              ("user-trash-symbolic", "Borrar", lambda *_: self.client.call(
                                  "delete_routine", {"routine": r["id"]}, self.window._toast_error))):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER)
            b.connect("clicked", fn)
            box.append(b)
        return box

    def set_names(self, names):
        pass  # names are read from the window on every load

    def on_event(self, ev):
        if ev["type"] == "routines":
            self.load(ev["routines"])
        elif ev["type"] == "agents":
            self.load(self.routines)

    def _dialog(self, r=None):
        dialog = Adw.AlertDialog(heading="Editar rutina" if r else "Nueva rutina")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(text=r["name"] if r else "", placeholder_text="Nombre, p. ej. Resumen de anuncios")
        targets = [("group", "Grupo")] + [(a["id"], a["name"]) for a in self.window.agents]
        target = Gtk.DropDown.new_from_strings([label for _, label in targets])
        if r:
            target.set_selected(next((i for i, (t, _) in enumerate(targets) if t == r["target"]), 0))
        prompt = Gtk.Entry(text=r["prompt"] if r else "", placeholder_text="Instrucción, p. ej. revisa los anuncios y resume")
        kind = Gtk.DropDown.new_from_strings([label for _, label in KINDS])
        hours = Gtk.SpinButton.new_with_range(1, 168, 1)
        time_entry = Gtk.Entry(text="09:00", max_width_chars=6, placeholder_text="HH:MM")
        days_box = Gtk.Box(spacing=4)
        day_buttons = [Gtk.ToggleButton(label=d[:2]) for d in DAYS]
        for b in day_buttons:
            days_box.append(b)
        s = r["schedule"] if r else {"daily": "09:00"}
        if "every_hours" in s:
            kind.set_selected(0)
            hours.set_value(s["every_hours"])
        elif "daily" in s:
            kind.set_selected(1)
            time_entry.set_text(s["daily"])
        else:
            kind.set_selected(2)
            time_entry.set_text(s["weekly"]["time"])
            for d in s["weekly"]["days"]:
                day_buttons[d].set_active(True)

        def sync(*_):
            k = KINDS[kind.get_selected()][0]
            hours.set_visible(k == "every_hours")
            time_entry.set_visible(k != "every_hours")
            days_box.set_visible(k == "weekly")

        kind.connect("notify::selected", sync)
        sync()
        for w in (name, target, prompt, kind, hours, time_entry, days_box):
            box.append(w)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("ok", "Guardar")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def done(_d, response):
            if response != "ok":
                return
            k = KINDS[kind.get_selected()][0]
            if k == "every_hours":
                schedule = {"every_hours": int(hours.get_value())}
            elif k == "daily":
                schedule = {"daily": time_entry.get_text().strip()}
            else:
                schedule = {"weekly": {"days": [i for i, b in enumerate(day_buttons) if b.get_active()],
                                       "time": time_entry.get_text().strip()}}
            params = {"name": name.get_text(), "target": targets[target.get_selected()][0],
                      "prompt": prompt.get_text(), "schedule": schedule}
            if r:
                self.client.call("update_routine", {"routine": r["id"], **params}, self.window._toast_error)
            else:
                self.client.call("create_routine", params, self.window._toast_error)

        dialog.connect("response", done)
        dialog.present(self.window)
