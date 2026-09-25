import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk  # noqa: E402

from colmena.ui import theme  # noqa: E402
from colmena.ui.window import MainWindow  # noqa: E402


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.gogema.Colmena")

    def do_activate(self):
        win = self.get_active_window()
        if not win:
            theme.install(Gdk.Display.get_default())
            win = MainWindow(self)
        win.present()


def main():
    sys.exit(App().run(sys.argv))
