import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class _Window:
    """The bits RoutinesView reads off MainWindow."""
    def __init__(self, auth):
        self.auth, self.client = auth, None
        self.agents, self.groups = [], []

    def _names(self):
        return {}

    def _group(self, _id):
        return None


class AccountNoticeTest(unittest.TestCase):
    """Routines are automated use: warn on a subscription, stay quiet on an API key."""

    def _view(self, auth):
        import gi
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        Adw.init()
        from hivemind.ui.routines import RoutinesView
        return RoutinesView(_Window(auth))

    def _routine(self):
        return {"id": "r1", "name": "Resumen", "target": "group", "prompt": "resume",
                "schedule": {"daily": "09:00"}, "next_run": 0, "enabled": False}

    def test_subscription_with_routines_warns(self):
        view = self._view("subscription")
        view.load([self._routine()])
        self.assertTrue(view.notice.get_revealed())

    def test_api_key_stays_quiet(self):
        view = self._view("api_key")
        view.load([self._routine()])
        self.assertFalse(view.notice.get_revealed())

    def test_no_routines_no_warning(self):
        view = self._view("subscription")
        view.load([])
        self.assertFalse(view.notice.get_revealed())


if __name__ == "__main__":
    unittest.main()
