import os
import unittest


@unittest.skipUnless(os.environ.get("GDK_BACKEND") == "broadway", "needs a display: run under gtk4-broadwayd")
class ComposerTest(unittest.TestCase):
    def run_app(self, body):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib, Gtk
        from hivemind.ui import theme
        from hivemind.ui.composer import Composer
        result, errors = {}, []

        class App(Adw.Application):
            def do_activate(self):
                theme.install(Gdk.Display.get_default())
                win = Adw.ApplicationWindow(application=self, default_width=600, default_height=400)
                sent = []
                composer = Composer(lambda text, files: sent.append((text, files)) if files else sent.append(text),
                                    names=lambda: ["Dev", "Desarrollador", "Marketing"],
                                    placeholder="Escribe…")
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.END, vexpand=True)
                box.append(composer)
                win.set_content(box)
                win.present()

                def go():
                    try:
                        body(composer, sent, result, Gdk)
                    except Exception as e:  # report instead of hanging the main loop
                        import traceback
                        errors.append(traceback.format_exc())
                    GLib.timeout_add(100, self.quit)
                    return False
                GLib.timeout_add(400, go)

        App(application_id="com.gogema.ComposerTest").run([])
        self.assertEqual(errors, [])
        return result

    def test_grows_vertically_up_to_a_limit(self):
        def body(c, sent, r, Gdk):
            from gi.repository import GLib, Gtk

            def height():
                for _ in range(200):  # let GTK lay the new text out before measuring
                    GLib.MainContext.default().iteration(False)
                return c.scroll.measure(Gtk.Orientation.VERTICAL, 600)[1]

            r["one"] = height()
            c.buffer.set_text("línea\n" * 3)
            r["four"] = height()
            c.buffer.set_text("línea\n" * 40)
            r["many"] = height()
        r = self.run_app(body)
        self.assertGreater(r["four"], r["one"])
        self.assertLessEqual(r["many"], 200)

    def test_enter_sends_and_shift_enter_does_not(self):
        def body(c, sent, r, Gdk):
            c.buffer.set_text("hola")
            r["shift"] = c._on_key(Gdk.KEY_Return, Gdk.ModifierType.SHIFT_MASK)
            r["enter"] = c._on_key(Gdk.KEY_Return, 0)
            r["sent"], r["left"] = list(sent), c.text
        r = self.run_app(body)
        self.assertEqual((r["shift"], r["enter"]), (False, True))
        self.assertEqual((r["sent"], r["left"]), (["hola"], ""))

    def test_at_lists_agents_and_tab_completes(self):
        def body(c, sent, r, Gdk):
            c.buffer.set_text("hola @De")
            r["open"], r["options"] = c.popover.get_visible(), c.options()
            c._on_key(Gdk.KEY_Down, 0)
            c._on_key(Gdk.KEY_Tab, 0)
            r["text"], r["closed"] = c.text, not c.popover.get_visible()
        r = self.run_app(body)
        self.assertEqual((r["open"], r["options"]), (True, ["Dev", "Desarrollador"]))
        self.assertEqual((r["text"], r["closed"]), ("hola @Desarrollador ", True))

    def test_known_mentions_are_highlighted_while_typing(self):
        def body(c, sent, r, Gdk):
            c.buffer.set_text("@Dev y @nadie")
            r["tagged"] = c.highlighted()
        self.assertEqual(self.run_app(body)["tagged"], ["@Dev"])

    def test_attachment_chips(self):
        import tempfile
        d = tempfile.mkdtemp(dir=os.path.expanduser("~/.cache/tmp"))
        a, b = os.path.join(d, "a.png"), os.path.join(d, "b.pdf")
        for p in (a, b):
            open(p, "wb").write(b"x")

        def body(c, sent, r, Gdk):
            c.add_files([a, b, a])            # a duplicate is ignored
            r["chips"] = c.pending()
            c.remove_file(a)
            r["after_remove"] = c.pending()
            c.buffer.set_text("")
            c.send()                          # files only, no text
            r["sent"], r["left"] = list(sent), c.pending()
        r = self.run_app(body)
        self.assertEqual(r["chips"], [a, b])
        self.assertEqual(r["after_remove"], [b])
        self.assertEqual((r["sent"], r["left"]), ([("", [b])], []))


if __name__ == "__main__":
    unittest.main()
