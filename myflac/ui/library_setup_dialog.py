"""Diálogo de bienvenida y configuración inicial de biblioteca musical."""
from __future__ import annotations

from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from ..constants import APP_ID
from ..logger import get_logger
from .. import i18n

log = get_logger("ui.library_setup")


class LibrarySetupDialog(Adw.Window):
    """Diálogo modal presentado en la primera ejecución si no hay biblioteca definida."""

    def __init__(self, parent: Gtk.Window, on_folder_chosen: Callable[[str], None]):
        super().__init__()
        self.on_folder_chosen = on_folder_chosen
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(520, 420)
        self.set_title(i18n.t("setup.welcome_title"))

        self._build_ui()

    def _build_ui(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(36)
        content.set_margin_bottom(36)
        content.set_margin_start(40)
        content.set_margin_end(40)
        content.set_valign(Gtk.Align.CENTER)
        content.set_halign(Gtk.Align.CENTER)

        # Icono grande de la aplicación
        icon_img = Gtk.Image.new_from_icon_name(APP_ID)
        icon_img.set_pixel_size(84)
        content.append(icon_img)

        # Título
        title_lbl = Gtk.Label(label=i18n.t("setup.welcome_title"))
        title_lbl.add_css_class("title-1")
        content.append(title_lbl)

        # Subtítulo explicativo
        desc_lbl = Gtk.Label(label=i18n.t("setup.welcome_subtitle"))
        desc_lbl.add_css_class("body")
        desc_lbl.add_css_class("dim-label")
        desc_lbl.set_wrap(True)
        desc_lbl.set_justify(Gtk.Justification.CENTER)
        desc_lbl.set_max_width_chars(42)
        content.append(desc_lbl)

        # Botón de selección de carpeta
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)

        self.btn_choose = Gtk.Button()
        self.btn_choose.add_css_class("suggested-action")
        self.btn_choose.add_css_class("pill")
        self.btn_choose.set_margin_top(12)

        btn_content = Adw.ButtonContent()
        btn_content.set_icon_name("folder-music-symbolic")
        btn_content.set_label(i18n.t("setup.choose_btn"))
        self.btn_choose.set_child(btn_content)
        self.btn_choose.connect("clicked", lambda *_: self._open_folder_chooser())
        btn_box.append(self.btn_choose)

        content.append(btn_box)

        # HeaderBar minimalista sin botón de cerrar obligatorio
        header = Adw.HeaderBar()
        header.set_show_title(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.append(header)
        main_box.append(content)

        self.set_content(main_box)

    def _open_folder_chooser(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title(i18n.t("setup.choose_title"))

        def on_selected(dlg: Gtk.FileDialog, res):
            try:
                gfile = dlg.select_folder_finish(res)
                if gfile:
                    folder_path = gfile.get_path()
                    if folder_path:
                        log.info("Carpeta inicial de biblioteca elegida: %s", folder_path)
                        self.close()
                        self.on_folder_chosen(folder_path)
            except Exception as e:
                log.debug("Selección de carpeta cancelada: %s", e)

        dialog.select_folder(self, None, on_selected)
