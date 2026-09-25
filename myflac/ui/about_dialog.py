"""Diálogo "Acerca de MyFlac"."""
from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from .. import __version__
from ..constants import APP_ID, APP_NAME
from .. import i18n


def build_about_dialog() -> Adw.AboutDialog:
    dialog = Adw.AboutDialog(
        application_name=APP_NAME,
        application_icon=APP_ID,
        developer_name="Miguel Angel Esteban",
        version=__version__,
        comments=i18n.t("app.comment"),
        developers=["Miguel Angel Esteban"],
        copyright="© 2026 Miguel Angel Esteban",
        license_type=Gtk.License.GPL_3_0,
    )
    return dialog
