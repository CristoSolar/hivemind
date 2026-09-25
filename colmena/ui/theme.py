import tomllib
from pathlib import Path

THEME_FILE = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
_FALLBACK = {"mode": "dark", "accent": "#89b4fa", "background": "#1e1e2e", "foreground": "#cdd6f4",
             "lighter_background": "#313244", "muted": "#585b70", "red": "#f38ba8",
             "green": "#a6e3a1", "yellow": "#f9e2af"}


def css(colors):
    c = {**_FALLBACK, **colors}
    return f"""
window, .colmena-root {{ background-color: {c['background']}; color: {c['foreground']}; }}
.colmena-bubble-user {{ background-color: {c['accent']}; color: {c['background']};
  border-radius: 14px; padding: 8px 12px; }}
.colmena-bubble-agent {{ background-color: {c['lighter_background']}; color: {c['foreground']};
  border-radius: 14px; padding: 8px 12px; }}
.colmena-author {{ color: {c['muted']}; font-size: smaller; }}
.colmena-system {{ color: {c['muted']}; font-style: italic; }}
.colmena-code {{ background-color: {c['background']}; border: 1px solid {c['muted']};
  border-radius: 8px; padding: 6px 8px; font-family: monospace; }}
.colmena-tool {{ color: {c['muted']}; }}
.colmena-approval {{ border: 2px solid {c['yellow']}; border-radius: 12px; padding: 10px; }}
.colmena-dot-idle {{ color: {c['muted']}; }}
.colmena-dot-queued {{ color: {c['foreground']}; }}
.colmena-dot-working {{ color: {c['green']}; }}
.colmena-dot-waiting {{ color: {c['yellow']}; }}
.colmena-dot-error {{ color: {c['red']}; }}
"""


def _read():
    try:
        return tomllib.loads(THEME_FILE.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def install(display):
    from gi.repository import Adw, Gio, Gtk

    provider = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def apply(*_):
        colors = _read()
        provider.load_from_string(css(colors))
        dark = colors.get("mode", "dark") != "light"
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)

    apply()
    # Omarchy replaces the whole theme directory on switch, so watch the parent.
    monitor = Gio.File.new_for_path(str(THEME_FILE.parent.parent)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
    monitor.connect("changed", apply)
    install.monitor = monitor  # keep a reference so it is not garbage collected
