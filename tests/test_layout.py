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

    def test_sidebar_lists_custom_groups_after_grupo(self):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib
        from hivemind.ui import theme
        from hivemind.ui.window import MainWindow
        threads = []

        class App(Adw.Application):
            def do_activate(self):
                theme.install(Gdk.Display.get_default())
                self.win = MainWindow(self)
                self.win.present()
                self.win.agents = [{"id": "a1", "name": "Dev", "role": "dev", "model": None}]
                self.win.groups = [{"id": "g-1", "name": "Lanzamiento", "members": ["a1"]}]
                self.win._rebuild_sidebar()
                i = 0
                while (row := self.win.sidebar_list.get_row_at_index(i)):
                    threads.append(row.thread)
                    i += 1
                GLib.idle_add(self.quit)

        App(application_id="com.gogema.LayoutTest2").run([])
        self.assertEqual(threads, ["group", "g-1", "routines", "board", "a1"])
    def test_deleting_the_open_group_falls_back_to_grupo(self):
        import sys, traceback
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib
        from hivemind.ui import theme
        from hivemind.ui.window import MainWindow
        out, errors = [], []
        hook, sys.excepthook = sys.excepthook, lambda *a: errors.append("".join(traceback.format_exception(*a)))

        class App(Adw.Application):
            def do_activate(self):
                try:
                    theme.install(Gdk.Display.get_default())
                    w = MainWindow(self)
                    w.present()
                    w.agents = [{"id": "a1", "name": "Dev", "role": "dev", "model": None}]
                    w.groups = [{"id": "g-1", "name": "Lanzamiento", "members": ["a1"]}]
                    w._rebuild_sidebar()
                    w._select_index(1)
                    w._on_event({"type": "groups", "groups": []})   # the open group is deleted
                    out.append((w._current(), w.settings_btn.get_visible(), w.delete_btn.get_visible()))
                    w._edit_current(); w._clear_current(); w._delete_current()  # must not raise
                except Exception:
                    errors.append(traceback.format_exc())
                finally:
                    GLib.idle_add(self.quit)

        App(application_id="com.gogema.LayoutTest3").run([])
        sys.excepthook = hook
        self.assertEqual(out, [("group", False, False)])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
