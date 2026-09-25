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


if __name__ == "__main__":
    unittest.main()
