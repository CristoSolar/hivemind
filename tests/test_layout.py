import os
import unittest


@unittest.skipUnless(os.environ.get("GDK_BACKEND") == "broadway", "needs a display: run under gtk4-broadwayd")
class LayoutTest(unittest.TestCase):
    def test_sidebar_and_chat_header_bars_line_up(self):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib
        from hivemind.ui import theme
        from hivemind.ui.window import MainWindow
        bounds = []

        class App(Adw.Application):
            def do_activate(self):
                theme.install(Gdk.Display.get_default())
                self.win = MainWindow(self)
                self.win.set_default_size(1100, 720)
                self.win.present()
                GLib.timeout_add(1200, self.measure)

            def measure(self):
                def walk(w):
                    if type(w).__name__ == "HeaderBar":
                        ok, b = w.compute_bounds(self.win)
                        bounds.append((b.get_y(), b.get_height()))
                    c = w.get_first_child()
                    while c:
                        walk(c)
                        c = c.get_next_sibling()
                walk(self.win)
                self.quit()

        App(application_id="com.gogema.LayoutTest").run([])
        self.assertEqual(len(bounds), 2)
        self.assertEqual(bounds[0], bounds[1])


if __name__ == "__main__":
    unittest.main()
