import gc
import os
import unittest


@unittest.skipUnless(os.environ.get("GDK_BACKEND") == "broadway", "needs a display: run under gtk4-broadwayd")
class AnimatedBeeWidgetTest(unittest.TestCase):
    def test_bees_without_python_references_keep_animating(self):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib, Gtk
        from colmena.ui import theme
        from colmena.ui.bee import AnimatedBee
        seen = set()

        class App(Adw.Application):
            def do_activate(self):
                theme.install(Gdk.Display.get_default())
                win = Adw.ApplicationWindow(application=self)
                box = Gtk.Box()
                box.append(AnimatedBee("working", seed="x"))  # like the sidebar: nobody keeps a reference
                win.set_content(box)
                win.present()
                GLib.timeout_add(50, self.sample, box)
                GLib.timeout_add(1500, self.quit)

            def sample(self, box):
                gc.collect()
                seen.add(box.get_first_child().shown)
                return True

        App(application_id="com.gogema.BeeWidgetTest").run([])
        self.assertEqual(seen, {("up", 1.0), ("down", 1.0)}, seen)

    def test_unmapped_bees_are_released(self):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib, Gtk
        from colmena.ui import bee as bee_module
        from colmena.ui import theme
        counts = []

        class App(Adw.Application):
            def do_activate(self):
                theme.install(Gdk.Display.get_default())
                counts.append(len(bee_module._visible))  # bees left by other tests in this process
                win = Adw.ApplicationWindow(application=self)
                self.box = Gtk.Box()
                for i in range(3):
                    self.box.append(bee_module.AnimatedBee("idle", seed=str(i)))
                win.set_content(self.box)
                win.present()
                GLib.timeout_add(300, self.clear)

            def clear(self):
                counts.append(len(bee_module._visible))
                while (child := self.box.get_first_child()):
                    self.box.remove(child)  # what a sidebar rebuild does
                counts.append(len(bee_module._visible))
                GLib.timeout_add(300, self.quit)

        App(application_id="com.gogema.BeeWidgetTest2").run([])
        base = counts[0]
        self.assertEqual(counts[1:], [base + 3, base])


if __name__ == "__main__":
    unittest.main()
