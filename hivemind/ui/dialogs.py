import os

from gi.repository import Adw, Gio, Gtk, Pango

MODELS = [(None, "Predeterminado"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")]


def model_label(model):
    return dict(MODELS).get(model, model or "Predeterminado")


def _row(title, widget):
    box = Gtk.Box(spacing=12)
    box.append(Gtk.Label(label=title, xalign=0, width_chars=10))
    widget.set_hexpand(True)
    box.append(widget)
    return box


class FolderButton(Gtk.Button):
    """Button that shows a folder path and opens the system folder chooser."""

    def __init__(self, parent, path=None):
        super().__init__()
        self.parent, self.path = parent, path
        self.label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.START)
        self.set_child(self.label)
        self._show()
        self.connect("clicked", self._pick)

    def _show(self):
        home = os.path.expanduser("~")
        shown = self.path.replace(home, "~", 1) if self.path else "La del rol"
        self.label.set_label(f"📁 {shown}")

    def _pick(self, *_):
        dialog = Gtk.FileDialog(title="Elige la carpeta del proyecto", modal=True)
        if self.path and os.path.isdir(self.path):
            dialog.set_initial_folder(Gio.File.new_for_path(self.path))
        dialog.select_folder(self.parent, None, self._picked)

    def _picked(self, dialog, res):
        try:
            folder = dialog.select_folder_finish(res)
        except Exception:  # cancelled
            return
        if folder and folder.get_path():
            self.path = folder.get_path()
            self._show()


def agent_dialog(parent, roles, on_done, agent=None):
    """New agent (agent=None) or edit an existing agent's model and folder."""
    editing = agent is not None
    dialog = Adw.AlertDialog(heading=f"Ajustes de {agent['name']}" if editing else "Nuevo agente")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    if not editing:
        name = Gtk.Entry(placeholder_text="Sin espacios, p. ej. Dev")
        role_ids = list(roles)
        role = Gtk.DropDown.new_from_strings([roles[r]["label"] for r in role_ids])
        box.append(_row("Nombre", name))
        box.append(_row("Rol", role))
    model = Gtk.DropDown.new_from_strings([label for _, label in MODELS])
    current = agent.get("model") if editing else None
    model.set_selected([m for m, _ in MODELS].index(current) if current in dict(MODELS) else 0)
    box.append(_row("Modelo", model))
    folder = FolderButton(parent, agent["cwd"] if editing else None)
    box.append(_row("Proyecto", folder))
    if editing:
        note = Gtk.Label(label="Cambiar la carpeta reinicia la conversación del agente.",
                         xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("ok", "Guardar" if editing else "Crear")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

    def done(_d, response):
        if response != "ok":
            return
        params = {"model": MODELS[model.get_selected()][0]}
        if folder.path:
            params["cwd"] = folder.path
        if not editing:
            params.update(name=name.get_text().strip(), role=role_ids[role.get_selected()])
        on_done(params)

    dialog.connect("response", done)
    dialog.present(parent)


def preferences_dialog(parent, settings, on_done):
    dialog = Adw.AlertDialog(heading="Preferencias",
                             body="Cuenta con la que trabajan todos los agentes.")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    sub = Gtk.CheckButton(label="Sesión de Claude en Omarchy (tu suscripción)")
    key = Gtk.CheckButton(label="API key de Anthropic", group=sub)
    (key if settings["auth"] == "api_key" else sub).set_active(True)
    entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text=(
        "Guardada. Déjala vacía para mantenerla" if settings["has_api_key"] else "sk-ant-…"))
    entry.set_sensitive(key.get_active())
    key.connect("toggled", lambda b: entry.set_sensitive(b.get_active()))
    for w in (sub, key, entry):
        box.append(w)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("ok", "Guardar")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

    def done(_d, response):
        if response != "ok":
            return
        params = {"auth": "api_key" if key.get_active() else "subscription"}
        if entry.get_text().strip():
            params["api_key"] = entry.get_text().strip()
        on_done(params)

    dialog.connect("response", done)
    dialog.present(parent)
