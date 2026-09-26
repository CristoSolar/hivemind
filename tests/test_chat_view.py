import os
import unittest


@unittest.skipUnless(os.environ.get("GDK_BACKEND") == "broadway", "needs a display: run under gtk4-broadwayd")
class ChatViewTest(unittest.TestCase):
    def test_overlapping_loads_do_not_duplicate_history(self):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib
        from hivemind.ui.chat import ChatView

        class SlowClient:
            """Answers history calls later, in order, like the socket does."""
            def __init__(self):
                self.pending = []

            def call(self, method, params=None, callback=None):
                self.pending.append(callback)

        counts = []

        class App(Adw.Application):
            def do_activate(self):
                client = SlowClient()
                view = ChatView(client, "group", {})
                msgs = [{"id": i, "thread": "group", "author": "user", "kind": "text", "content": f"m{i}", "ts": 0}
                        for i in range(3)]
                view.load()
                view.load()  # e.g. selecting the chat and then the hello snapshot arriving
                for cb in client.pending:
                    cb(msgs, None)
                n, child = 0, view.list.get_first_child()
                while child:
                    n += 1
                    child = child.get_next_sibling()
                counts.append(n)
                GLib.idle_add(self.quit)

        App(application_id="com.gogema.ChatViewTest").run([])
        self.assertEqual(counts, [3])

    def test_attachments_render_as_thumbnail_and_chip(self):
        import tempfile
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib, Gtk
        from hivemind.ui.chat import ChatView
        d = tempfile.mkdtemp(dir=os.path.expanduser("~/.cache/tmp"))
        png = os.path.join(d, "foto.png")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 8, 8)
        pix.fill(0xf5b400ff)
        pix.savev(png, "png", [], [])  # a real PNG, so the thumbnail can be decoded
        found = {}

        def walk(w, types):
            types.add(type(w).__name__)
            c = w.get_first_child()
            while c:
                walk(c, types)
                c = c.get_next_sibling()

        class OneShotClient:
            def call(self, method, params=None, callback=None):
                if callback:
                    callback([{"id": 1, "thread": "a1", "author": "user", "kind": "text", "content": "",
                               "ts": 0, "attachments": [
                                   {"name": "foto.png", "path": png, "kind": "imagen", "size": 70, "transcript": None},
                                   {"name": "informe.pdf", "path": os.path.join(d, "informe.pdf"), "kind": "documento",
                                    "size": 2048, "transcript": None},
                                   {"name": "nota.m4a", "path": os.path.join(d, "nota.m4a"), "kind": "audio",
                                    "size": 10, "transcript": "hola equipo"}]}], None)

        class App(Adw.Application):
            def do_activate(self):
                view = ChatView(OneShotClient(), "a1", {"a1": "Dev"})
                view.load()
                types = set()
                walk(view.list, types)
                found["types"] = types
                found["chips"] = len(view.attachment_widgets)
                GLib.idle_add(self.quit)

        App(application_id="com.gogema.ChatViewTest2").run([])
        self.assertIn("Picture", found["types"])
        self.assertIn("Expander", found["types"])     # the audio transcript
        self.assertEqual(found["chips"], 3)


if __name__ == "__main__":
    unittest.main()
