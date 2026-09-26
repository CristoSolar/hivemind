import colorsys
import tomllib
from pathlib import Path

THEME_FILE = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
SHELL_FILE = Path.home() / ".config/omarchy/shell.toml"
_FALLBACK = {"mode": "dark", "accent": "#89b4fa", "background": "#1e1e2e", "foreground": "#cdd6f4",
             "lighter_background": "#313244", "dark_background": "#161622",
             "darker_background": "#101019", "muted": "#585b70", "red": "#f38ba8",
             "green": "#a6e3a1", "yellow": "#f9e2af"}


AGENT_TINTS = 8  # distinct colours before two agents share one; the name still tells them apart


def tints(accent, n=AGENT_TINTS):
    """`n` hues spread around the wheel, keeping the theme accent's saturation and lightness.

    Derived from the theme instead of hardcoded, so the tints follow an Omarchy theme switch and
    stay as readable as the accent itself. None of them lands on the accent: that one means "you".
    """
    try:
        r, g, b = (int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (ValueError, IndexError, TypeError):  # a theme file may hold anything
        r, g, b = (int(_FALLBACK["accent"][i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    out = []
    for i in range(n):
        hue = (h + (i + 1) / (n + 1)) % 1.0
        rr, gg, bb = colorsys.hls_to_rgb(hue, lightness, saturation)
        out.append("#%02x%02x%02x" % (round(rr * 255), round(gg * 255), round(bb * 255)))
    return out


def font_size(path=SHELL_FILE):
    """Omarchy's UI font size ([font] base-size in shell.toml), 14 if unset."""
    try:
        return int(tomllib.loads(path.read_text())["font"]["base-size"])
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError):
        return 14


def css(colors, size=14):
    c = {**_FALLBACK, **colors}
    return f"""
/* Omarchy look: JetBrains Mono, square corners, 2px accent borders, flat. */
* {{ font-family: "JetBrainsMono Nerd Font", monospace; border-radius: 0; }}
window, .hivemind-root {{ background-color: {c['background']}; color: {c['foreground']};
  font-size: {size}px; }}

headerbar {{ background: {c['background']}; box-shadow: inset 0 -1px {c['muted']}; min-height: 48px;
  margin: 0; padding-top: 0; padding-bottom: 0; }}
headerbar .title {{ font-weight: bold; }}

.navigation-sidebar {{ background: {c['background']}; }}
.navigation-sidebar > row {{ margin: 0; padding: 2px 4px; border-radius: 0; }}
.navigation-sidebar > row:hover {{ background: {c['dark_background']}; }}
.navigation-sidebar > row:selected {{ background: {c['lighter_background']};
  box-shadow: inset 2px 0 {c['accent']}; }}

.hivemind-bubble-user {{ background: transparent; color: {c['foreground']};
  border: 2px solid {c['accent']}; border-radius: 0; padding: 6px 10px; }}
.hivemind-bubble-agent {{ background: transparent; color: {c['foreground']};
  border: 2px solid {c['muted']}; border-radius: 0; padding: 6px 10px; }}
.hivemind-author {{ color: {c['accent']}; font-weight: bold; font-size: smaller; }}
.hivemind-system {{ color: {c['muted']}; font-style: italic; }}
.hivemind-code {{ background-color: {c['darker_background']}; color: {c['foreground']};
  border: none; border-radius: 0; padding: 6px 8px; }}
.hivemind-tool {{ color: {c['muted']}; }}
.hivemind-approval {{ border: 2px solid {c['yellow']}; border-radius: 0; padding: 10px;
  background: {c['dark_background']}; }}

entry {{ background: {c['dark_background']}; border: 2px solid {c['muted']}; border-radius: 0;
  box-shadow: none; outline: none; min-height: 34px; }}
entry:focus-within {{ border-color: {c['accent']}; }}
.hivemind-attachment {{ background: {c['dark_background']}; border: 2px solid {c['muted']}; border-radius: 0; padding: 2px 8px; }}
.hivemind-composer-frame {{ background: {c['dark_background']}; border: 2px solid {c['muted']}; border-radius: 0; }}
/* Attach, stop and send sit beside the composer: same box, same bottom edge. */
.hivemind-composer-button {{ padding: 0; }}
.hivemind-composer-frame:focus-within {{ border-color: {c['accent']}; }}
textview.hivemind-composer, textview.hivemind-composer text {{ background: {c['dark_background']}; color: {c['foreground']}; }}

button {{ border-radius: 0; box-shadow: none; background: transparent;
  border: 2px solid {c['muted']}; padding: 4px 12px; }}
button:hover {{ border-color: {c['accent']}; }}
headerbar button {{ border-color: transparent; }}
button.suggested-action {{ background: {c['accent']}; color: {c['background']}; border-color: {c['accent']};
  font-weight: bold; }}
button.destructive-action {{ color: {c['red']}; border-color: {c['red']}; }}

.hivemind-card {{ border: 2px solid {c['muted']}; border-radius: 0; padding: 8px; background: {c['dark_background']}; }}
.hivemind-cards > row {{ border-bottom: 1px solid {c['muted']}; }}
list.hivemind-cards {{ background: transparent; }}
.hivemind-cards > row {{ background: {c['dark_background']}; }}

switch {{ border-radius: 0; background-color: {c['lighter_background']}; }}
switch:checked {{ background-color: {c['accent']}; }}
switch > slider {{ border-radius: 0; background-color: {c['foreground']}; }}

dialog.alert sheet, dialog.alert .dialog-contents {{ background-color: {c['dark_background']}; }}
dialog.alert sheet {{ border: 2px solid {c['accent']}; border-radius: 0; box-shadow: none; }}
dropdown > button {{ background: transparent; }}
popover > contents {{ background-color: {c['dark_background']}; border: 2px solid {c['muted']}; border-radius: 0; }}
.hivemind-bee {{ color: {c['foreground']}; }}
.hivemind-bee-idle {{ color: {c['muted']}; }}
.hivemind-bee-queued {{ color: {c['foreground']}; }}
.hivemind-bee-working, .hivemind-bee-tool, .hivemind-bee-thinking {{ color: {c['accent']}; }}
.hivemind-bee-sleeping {{ color: {c['muted']}; opacity: 0.8; }}
.hivemind-bee-waiting {{ color: {c['yellow']}; }}
.hivemind-bee-error {{ color: {c['red']}; }}
.hivemind-dot {{ font-size: 10px; text-shadow: 0 0 2px {c['background']}; }}
.hivemind-dot-idle {{ color: {c['muted']}; }}
.hivemind-dot-queued {{ color: {c['foreground']}; }}
.hivemind-dot-working {{ color: {c['green']}; }}
.hivemind-dot-waiting {{ color: {c['yellow']}; }}
.hivemind-dot-error {{ color: {c['red']}; }}

/* One tint per agent, so a glance tells you who is speaking. */
{_tint_css(c['accent'])}
"""


def _tint_css(accent):
    rules = []
    for i, colour in enumerate(tints(accent)):
        rules.append(f".hivemind-bubble-agent.tint-{i} {{ border-color: {colour}; }}")
        rules.append(f".hivemind-author.tint-{i} {{ color: {colour}; }}")
        rules.append(f".hivemind-bee.tint-{i} {{ color: {colour}; }}")
    return "\n".join(rules)


def _read():
    try:
        return tomllib.loads(THEME_FILE.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def colors():
    """The current Omarchy theme colours, with fallbacks for missing keys."""
    return {**_FALLBACK, **_read()}


def install(display):
    from gi.repository import Adw, Gio, Gtk

    from hivemind.ui.window_icons import ICONS
    Gtk.IconTheme.get_for_display(display).add_search_path(str(ICONS))  # hivemind-*-symbolic icons
    provider = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def apply(*_):
        colors = _read()
        provider.load_from_string(css(colors, font_size()))
        dark = colors.get("mode", "dark") != "light"
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)

    apply()
    # Omarchy replaces the whole theme directory on switch, so watch the parent.
    monitor = Gio.File.new_for_path(str(THEME_FILE.parent.parent)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
    monitor.connect("changed", apply)
    install.monitor = monitor  # keep a reference so it is not garbage collected
