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

    def __init__(
        self,
        parent: Gtk.Window,
        on_folder_chosen: Callable[[str], None],
        on_skip: Callable[[], None] | None = None,
        on_streaming_chosen: Callable[[str], None] | None = None,
        tidal_enabled: bool = False,
        qobuz_enabled: bool = False,
    ):
        super().__init__()
        self.on_folder_chosen = on_folder_chosen
        self.on_skip = on_skip
        self.on_streaming_chosen = on_streaming_chosen
        self.tidal_enabled = tidal_enabled
        self.qobuz_enabled = qobuz_enabled
        self._handled = False

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(520, 480)
        self.set_title(i18n.t("setup.welcome_title"))

        self.connect("close-request", self._on_close_request)
        self._build_ui()

    def _on_close_request(self, _window):
        if not self._handled:
            self._handled = True
            if self.on_skip:
                self.on_skip()
        return False

    def _build_ui(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(28)
        content.set_margin_bottom(28)
        content.set_margin_start(40)
        content.set_margin_end(40)
        content.set_valign(Gtk.Align.CENTER)
        content.set_halign(Gtk.Align.CENTER)

        # Icono grande de la aplicación
        icon_img = Gtk.Image.new_from_icon_name(APP_ID)
        icon_img.set_pixel_size(76)
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
        desc_lbl.set_max_width_chars(44)
        content.append(desc_lbl)

        # Botones de acción
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(8)

        # 1. Botón principal: Seleccionar carpeta local
        self.btn_choose = Gtk.Button()
        self.btn_choose.add_css_class("suggested-action")
        self.btn_choose.add_css_class("pill")

        btn_content = Adw.ButtonContent()
        btn_content.set_icon_name("folder-music-symbolic")
        btn_content.set_label(i18n.t("setup.choose_btn"))
        self.btn_choose.set_child(btn_content)
        self.btn_choose.connect("clicked", lambda *_: self._open_folder_chooser())
        btn_box.append(self.btn_choose)

        # 2. Botón para saltar directamente a TIDAL si está habilitado
        if self.tidal_enabled:
            self.btn_tidal = Gtk.Button()
            self.btn_tidal.add_css_class("pill")
            tidal_content = Adw.ButtonContent()
            tidal_content.set_icon_name("audio-x-generic-symbolic")
            tidal_content.set_label(i18n.t("setup.continue_tidal"))
            self.btn_tidal.set_child(tidal_content)
            self.btn_tidal.connect("clicked", lambda *_: self._choose_streaming("tidal"))
            btn_box.append(self.btn_tidal)

        # 3. Botón para saltar directamente a Qobuz si está habilitado
        if self.qobuz_enabled:
            self.btn_qobuz = Gtk.Button()
            self.btn_qobuz.add_css_class("pill")
            qobuz_content = Adw.ButtonContent()
            qobuz_content.set_icon_name("network-server-symbolic")
            qobuz_content.set_label(i18n.t("setup.continue_qobuz"))
            self.btn_qobuz.set_child(qobuz_content)
            self.btn_qobuz.connect("clicked", lambda *_: self._choose_streaming("qobuz"))
            btn_box.append(self.btn_qobuz)

        # 4. Botón secundario plano: Omitir por ahora
        self.btn_skip = Gtk.Button(label=i18n.t("setup.skip_btn"))
        self.btn_skip.add_css_class("flat")
        self.btn_skip.add_css_class("pill")
        self.btn_skip.connect("clicked", lambda *_: self._skip())
        btn_box.append(self.btn_skip)

        content.append(btn_box)

        # HeaderBar estándar de Adwaita con control de cierre
        header = Adw.HeaderBar()
        header.set_show_title(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.append(header)
        main_box.append(content)

        self.set_content(main_box)

    def _choose_streaming(self, service: str):
        if self._handled:
            return
        self._handled = True
        self.close()
        if self.on_streaming_chosen:
            self.on_streaming_chosen(service)

    def _skip(self):
        if self._handled:
            return
        self._handled = True
        self.close()
        if self.on_skip:
            self.on_skip()

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
                        self._handled = True
                        self.close()
                        self.on_folder_chosen(folder_path)
            except Exception as e:
                log.debug("Selección de carpeta cancelada: %s", e)

        dialog.select_folder(self, None, on_selected)
