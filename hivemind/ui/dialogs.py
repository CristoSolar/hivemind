import os

from gi.repository import Adw, Gio, Gtk, Pango

from hivemind.ui import a11y

MODELS = [(None, "Predeterminado"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")]


def model_label(model):
    return dict(MODELS).get(model, model or "Predeterminado")


def _row(title, widget):
    box = Gtk.Box(spacing=12)
    caption = Gtk.Label(label=title, xalign=0, width_chars=10)
    box.append(caption)
    widget.set_hexpand(True)
    a11y.describes(caption, widget)
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
    brief = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, top_margin=6, bottom_margin=6,
                         left_margin=6, right_margin=6)
    brief.get_buffer().set_text(agent.get("brief", "") if editing else "")
    brief.set_size_request(-1, 90)
    box.append(_row("Estilo", Gtk.Frame(child=brief)))
    hint = Gtk.Label(xalign=0, wrap=True, label="Opcional. Cómo trabaja este agente en particular: "
                     "de qué se encarga, qué criterio usa. Dos agentes del mismo rol pueden "
                     "trabajar distinto.")
    hint.add_css_class("dim-label")
    hint.add_css_class("caption")
    box.append(hint)
    if editing:
        note = Gtk.Label(label="Cambiar la carpeta reinicia la conversación del agente.",
                         xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("ok", "Guardar" if editing else "Crear")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    def done(_d, response):
        if response != "ok":
            return
        buf = brief.get_buffer()
        params = {"model": MODELS[model.get_selected()][0],
                  "brief": buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()}
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
    hint = Gtk.Label(xalign=0, wrap=True, label="Las rutinas corren sin ti delante. Los términos de "
                     "Anthropic cubren ese uso automatizado con una API key; los límites de Pro y Max "
                     "suponen uso individual ordinario.")
    hint.add_css_class("dim-label")
    hint.add_css_class("caption")
    for w in (sub, key, entry, hint):
        box.append(w)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("ok", "Guardar")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    def done(_d, response):
        if response != "ok":
            return
        params = {"auth": "api_key" if key.get_active() else "subscription"}
        if entry.get_text().strip():
            params["api_key"] = entry.get_text().strip()
        on_done(params)

    dialog.connect("response", done)
    dialog.present(parent)


def group_dialog(parent, agents, on_done, group=None):
    """New group (group=None) or edit a group's name and members."""
    dialog = Adw.AlertDialog(heading=f"Editar «{group['name']}»" if group else "Nuevo grupo")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    name = Gtk.Entry(text=group["name"] if group else "", placeholder_text="Nombre, p. ej. Lanzamiento")
    box.append(_row("Nombre", name))
    box.append(Gtk.Label(label="Integrantes", xalign=0))
    checks = []
    for a in agents:
        check = Gtk.CheckButton(label=a["name"], active=bool(group and a["id"] in group["members"]))
        checks.append((a["id"], check))
        box.append(check)
    if group:
        note = Gtk.Label(label="Quien salga del grupo olvida esta conversación.", xalign=0, wrap=True)
        note.add_css_class("dim-label")
        box.append(note)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("ok", "Guardar" if group else "Crear")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    def done(_d, response):
        if response == "ok":
            on_done({"name": name.get_text().strip(), "members": [aid for aid, c in checks if c.get_active()]})

    dialog.connect("response", done)
    dialog.present(parent)


def confirm(parent, heading, body, action, on_yes):
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("yes", action)
    dialog.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_close_response("cancel")  # Escape cancels; a destructive action is never the default
    dialog.connect("response", lambda _d, r: r == "yes" and on_yes())
    dialog.present(parent)
