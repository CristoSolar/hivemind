"""Accessible names for the widgets that show an icon and no text.

GTK maps a tooltip to the accessible *description*; the accessible *name* of an
icon-only button still falls back to the icon name, which is what a screen reader
reads out ("user-trash-symbolic"). These helpers set both from one string.
"""
from gi.repository import Gtk


def label(widget, text):
    """Give a widget an accessible name. Returns it, so it can wrap a constructor."""
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])
    return widget


def icon_button(button, text):
    """Tooltip and accessible name from the same words: they never drift apart."""
    button.set_tooltip_text(text)
    return label(button, text)


def describes(caption, widget):
    """Tie a visible caption to its field, the way <label for=…> does on the web.

    GtkLabel sets the labelled-by relation itself from the mnemonic widget, so this
    is the whole association: a screen reader reads "Nombre, entrada de texto".
    """
    caption.set_mnemonic_widget(widget)
    return widget
