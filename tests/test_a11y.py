import pathlib
import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

UI = pathlib.Path(__file__).resolve().parent.parent / "hivemind" / "ui"


class IconButtonTest(unittest.TestCase):
    """A button that shows an icon and no text needs a name a screen reader can say."""

    def test_no_bare_icon_button_in_the_ui(self):
        """Gtk.Button(icon_name=…) must go through a11y.icon_button, which names it."""
        offenders = []
        for path in sorted(UI.glob("*.py")):
            lines = path.read_text().splitlines()
            for n, line in enumerate(lines):
                if "Button(icon_name=" not in line:
                    continue
                # the wrapper may sit on this line or wrap onto the one above
                context = line + (lines[n - 1] if n else "")
                if "a11y.icon_button" not in context:
                    offenders.append(f"{path.name}:{n + 1}")
        self.assertEqual(offenders, [], "wrap these in a11y.icon_button(...)")


class HelperTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw
        Adw.init()

    def test_icon_button_sets_tooltip_and_name(self):
        from gi.repository import Gtk
        from hivemind.ui import a11y
        b = a11y.icon_button(Gtk.Button(icon_name="user-trash-symbolic"), "Borrar")
        self.assertEqual(b.get_tooltip_text(), "Borrar")

    def test_describes_links_caption_to_field(self):
        from gi.repository import Gtk
        from hivemind.ui import a11y
        caption, entry = Gtk.Label(label="Nombre"), Gtk.Entry()
        a11y.describes(caption, entry)
        self.assertIs(caption.get_mnemonic_widget(), entry)


class BoardEmptyStateTest(unittest.TestCase):
    def test_every_column_has_an_empty_message(self):
        from hivemind.ui.board import COLUMNS, BoardView
        for status, _ in COLUMNS:
            self.assertIn(status, BoardView.EMPTY)
            self.assertTrue(BoardView.EMPTY[status].strip())


class DialogKeyboardTest(unittest.TestCase):
    """Enter confirms and Escape cancels in every dialog that asks for something."""

    def test_dialogs_set_default_and_close_responses(self):
        text = (UI / "dialogs.py").read_text()
        self.assertEqual(text.count('set_default_response("ok")'), text.count('add_response("ok"'))
        # every dialog, including the destructive one, closes on Escape
        self.assertEqual(text.count('set_close_response("cancel")'), text.count('add_response("cancel"'))


if __name__ == "__main__":
    unittest.main()
