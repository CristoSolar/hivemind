import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class ViewContractTest(unittest.TestCase):
    """MainWindow broadcasts every event to every open view; each must accept the same calls."""

    def test_views_share_the_window_interface(self):
        from hivemind.ui.board import BoardView
        from hivemind.ui.chat import ChatView
        from hivemind.ui.routines import RoutinesView
        for view in (ChatView, RoutinesView, BoardView):
            for method in ("on_event", "set_names", "load"):
                self.assertTrue(callable(getattr(view, method, None)), f"{view.__name__}.{method}")


if __name__ == "__main__":
    unittest.main()
