"""Diálogo de preferencias de MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..audio.devices import AudioDevice, get_available_devices
from ..config import save_config
from ..library.db import LibraryDB
from ..library.scanner import LibraryScanner
from ..logger import get_logger
from .. import i18n
from .style import apply_theme, apply_ui_scale

log = get_logger("ui.preferences")

LANG_CODES = ["es", "en", "ca"]
LANG_LABELS = ["Español", "English", "Català"]


class PreferencesDialog(Adw.PreferencesWindow):
    def __init__(
        self,
        cfg: dict,
        db: LibraryDB | None = None,
        scanner: LibraryScanner | None = None,
        on_config_changed: Callable[[dict], None] | None = None,
        on_library_updated: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__()
        self.cfg = cfg
        self.db = db
        self.scanner = scanner
        self.on_config_changed = on_config_changed
        self.on_library_updated = on_library_updated

        self.set_title(i18n.t("prefs.title"))
        self.set_default_size(620, 540)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self._available_devices = get_available_devices()
        self._build_ui()

        # Listener para actualizar el diálogo si cambia el idioma
        i18n.add_language_listener(self._on_language_changed)

    def _build_ui(self):
        # =====================================================================
        # PÁGINA 1: GENERAL
        # =====================================================================
        self.page_general = Adw.PreferencesPage()
        self.page_general.set_title(i18n.t("prefs.general"))
        self.page_general.set_icon_name("preferences-system-symbolic")

        # Grupo: Idioma de la interfaz
        self.group_lang = Adw.PreferencesGroup(
            title=i18n.t("prefs.language"),
            description=i18n.t("prefs.language_desc"),
        )
        self.lang_row = Adw.ComboRow()
        self.lang_row.set_title(i18n.t("prefs.language"))
        self.lang_row.set_model(Gtk.StringList.new(LANG_LABELS))

        curr_lang = i18n.get_language()
        if curr_lang in LANG_CODES:
            self.lang_row.set_selected(LANG_CODES.index(curr_lang))
        else:
            self.lang_row.set_selected(0)

        self.lang_row.connect("notify::selected", self._on_lang_changed)
        self.group_lang.add(self.lang_row)
        self.page_general.add(self.group_lang)

        # Grupo: Dispositivo de Salida de Audio
        self.group_audio = Adw.PreferencesGroup(
            title=i18n.t("prefs.audio_group"),
            description=i18n.t("devices.group_desc"),
        )
        self.device_row = Adw.ComboRow()
        self.device_row.set_title(i18n.t("prefs.audio_device"))

        device_names = [d.name for d in self._available_devices]
        self.device_row.set_model(Gtk.StringList.new(device_names))

        curr_dev_id = self.cfg.get("audio_device_id", "default")
        selected_idx = 0
        for idx, dev in enumerate(self._available_devices):
            if dev.id == curr_dev_id or (curr_dev_id in dev.id and curr_dev_id != "default"):
                selected_idx = idx
                break
        self.device_row.set_selected(selected_idx)
        self.device_row.connect("notify::selected", self._on_device_changed)
        self.group_audio.add(self.device_row)
        self.page_general.add(self.group_audio)

        # Grupo: Apariencia e Interfaz
        self.group_ui = Adw.PreferencesGroup(title=i18n.t("prefs.ui_group"))

        self.theme_row = Adw.ComboRow()
        self.theme_row.set_title(i18n.t("prefs.theme"))
        self._update_theme_model()

        curr_theme = self.cfg.get("theme", "system")
        if curr_theme == "light":
            self.theme_row.set_selected(1)
        elif curr_theme == "dark":
            self.theme_row.set_selected(2)
        else:
            self.theme_row.set_selected(0)

        self.theme_row.connect("notify::selected", self._on_theme_changed)
        self.group_ui.add(self.theme_row)

        self.scale_row = Adw.SpinRow.new_with_range(75, 150, 5)
        self.scale_row.set_title(i18n.t("prefs.scale"))
        self.scale_row.set_subtitle(i18n.t("prefs.scale_desc"))
        self.scale_row.set_value(float(self.cfg.get("ui_scale", 100)))
        self.scale_row.connect("notify::value", self._on_ui_scale_changed)
        self.group_ui.add(self.scale_row)

        self.page_general.add(self.group_ui)
        self.add(self.page_general)

        # =====================================================================
        # PÁGINA 2: BIBLIOTECA MUSICAL
        # =====================================================================
        self.page_library = Adw.PreferencesPage()
        self.page_library.set_title(i18n.t("prefs.library_page"))
        self.page_library.set_icon_name("folder-music-symbolic")

        # Grupo: Carpetas de la Biblioteca
        self.group_folders = Adw.PreferencesGroup(
            title=i18n.t("prefs.library_folders_group"),
            description=i18n.t("prefs.library_folders_desc"),
        )
        self._folder_rows: list[Adw.ActionRow] = []
        self._rebuild_folder_rows()
        self.page_library.add(self.group_folders)

        # Grupo: Mantenimiento y Escaneo
        self.group_maintenance = Adw.PreferencesGroup(
            title=i18n.t("prefs.maintenance_group")
        )

        # Fila Buscar temas nuevos
        self.row_scan = Adw.ActionRow()
        self.row_scan.set_title(i18n.t("prefs.scan_new"))
        self.row_scan.set_subtitle(i18n.t("prefs.scan_new_desc"))

        self.btn_scan = Gtk.Button()
        self.btn_scan.set_valign(Gtk.Align.CENTER)
        scan_content = Adw.ButtonContent()
        scan_content.set_icon_name("view-refresh-symbolic")
        scan_content.set_label(i18n.t("prefs.scan_btn"))
        self.btn_scan.set_child(scan_content)
        self.btn_scan.connect("clicked", lambda *_: self._on_scan_now_clicked())
        self.row_scan.add_suffix(self.btn_scan)
        self.group_maintenance.add(self.row_scan)

        # Fila Restablecer base de datos
        self.row_reset = Adw.ActionRow()
        self.row_reset.set_title(i18n.t("prefs.reset_db"))
        self.row_reset.set_subtitle(i18n.t("prefs.reset_db_desc"))

        self.btn_reset = Gtk.Button()
        self.btn_reset.set_valign(Gtk.Align.CENTER)
        self.btn_reset.add_css_class("destructive-action")
        reset_content = Adw.ButtonContent()
        reset_content.set_icon_name("edit-delete-symbolic")
        reset_content.set_label(i18n.t("prefs.reset_btn"))
        self.btn_reset.set_child(reset_content)
        self.btn_reset.connect("clicked", lambda *_: self._confirm_reset_database())
        self.row_reset.add_suffix(self.btn_reset)
        self.group_maintenance.add(self.row_reset)

        self.page_library.add(self.group_maintenance)
        self.add(self.page_library)

    def _rebuild_folder_rows(self):
        # Limpiar filas existentes del grupo de carpetas
        for row in self._folder_rows:
            self.group_folders.remove(row)
        self._folder_rows.clear()

        folders = self.cfg.get("library_folders", [])
        for folder_path in folders:
            row = Adw.ActionRow()
            row.set_title(folder_path)
            row.set_icon_name("folder-symbolic")

            btn_del = Gtk.Button()
            btn_del.set_icon_name("user-trash-symbolic")
            btn_del.add_css_class("flat")
            btn_del.set_valign(Gtk.Align.CENTER)
            btn_del.set_tooltip_text(i18n.t("prefs.remove_folder"))
            # Capturar folder_path de forma segura en lambda
            btn_del.connect("clicked", lambda *_, p=folder_path: self._remove_folder(p))
            row.add_suffix(btn_del)

            self.group_folders.add(row)
            self._folder_rows.append(row)

        # Fila para añadir nueva carpeta
        self.row_add_folder = Adw.ActionRow()
        self.row_add_folder.set_title(i18n.t("prefs.add_folder"))
        self.row_add_folder.set_icon_name("list-add-symbolic")
        self.row_add_folder.set_activatable(True)
        self.row_add_folder.connect("activated", lambda *_: self._choose_new_folder())

        btn_add = Gtk.Button()
        btn_add.set_icon_name("list-add-symbolic")
        btn_add.set_valign(Gtk.Align.CENTER)
        btn_add.add_css_class("flat")
        btn_add.connect("clicked", lambda *_: self._choose_new_folder())
        self.row_add_folder.add_suffix(btn_add)

        self.group_folders.add(self.row_add_folder)
        self._folder_rows.append(self.row_add_folder)

    def _choose_new_folder(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title(i18n.t("prefs.add_folder"))

        def on_selected(dlg: Gtk.FileDialog, res):
            try:
                gfile = dlg.select_folder_finish(res)
                if gfile:
                    path = gfile.get_path()
                    if path:
                        self._add_folder(path)
            except Exception as e:
                log.debug("Selección de carpeta cancelada: %s", e)

        dialog.select_folder(self, None, on_selected)

    def _add_folder(self, folder_path: str):
        folder_path = os.path.abspath(folder_path)
        folders = self.cfg.setdefault("library_folders", [])
        if folder_path not in folders:
            folders.append(folder_path)
            save_config(self.cfg)
            if self.db:
                self.db.add_library_folder(folder_path)
            self._rebuild_folder_rows()
            if self.scanner:
                self.scanner.start_scan([folder_path], quick=False, on_finished=self._on_scan_finished)
            elif self.on_library_updated:
                self.on_library_updated()

    def _remove_folder(self, folder_path: str):
        folders = self.cfg.get("library_folders", [])
        if folder_path in folders:
            folders.remove(folder_path)
            save_config(self.cfg)
            if self.db:
                self.db.remove_library_folder(folder_path)
            self._rebuild_folder_rows()
            if self.on_library_updated:
                self.on_library_updated()

    def _on_scan_now_clicked(self):
        folders = self.cfg.get("library_folders", [])
        if self.scanner and folders:
            self.btn_scan.set_sensitive(False)
            self.scanner.start_scan(folders, quick=True, on_finished=self._on_scan_finished)

    def _confirm_reset_database(self):
        dialog = Adw.MessageDialog.new(
            self,
            i18n.t("prefs.reset_confirm_title"),
            i18n.t("prefs.reset_confirm_msg"),
        )
        dialog.add_response("cancel", i18n.t("dialog.cancel"))
        dialog.add_response("reset", i18n.t("prefs.reset_btn"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dlg, response_id):
            if response_id == "reset":
                self._do_reset_database()

        dialog.connect("response", on_response)
        dialog.present()

    def _do_reset_database(self):
        log.info("Restableciendo base de datos a petición del usuario")
        if self.db:
            self.db.clear_database()
        folders = self.cfg.get("library_folders", [])
        if self.scanner and folders:
            self.btn_scan.set_sensitive(False)
            self.scanner.start_scan(folders, quick=False, on_finished=self._on_scan_finished)
        elif self.on_library_updated:
            self.on_library_updated()

    def _on_scan_finished(self, _result: dict):
        self.btn_scan.set_sensitive(True)
        if self.on_library_updated:
            self.on_library_updated()

    def _update_theme_model(self):
        theme_names = [
            i18n.t("prefs.theme_system"),
            i18n.t("prefs.theme_light"),
            i18n.t("prefs.theme_dark"),
        ]
        self.theme_row.set_model(Gtk.StringList.new(theme_names))

    def _on_language_changed(self, _lang: str):
        self.set_title(i18n.t("prefs.title"))
        self.page_general.set_title(i18n.t("prefs.general"))
        self.group_lang.set_title(i18n.t("prefs.language"))
        self.group_lang.set_description(i18n.t("prefs.language_desc"))
        self.lang_row.set_title(i18n.t("prefs.language"))

        self.group_audio.set_title(i18n.t("prefs.audio_group"))
        self.group_audio.set_description(i18n.t("devices.group_desc"))
        self.device_row.set_title(i18n.t("prefs.audio_device"))

        self.group_ui.set_title(i18n.t("prefs.ui_group"))
        self.theme_row.set_title(i18n.t("prefs.theme"))
        self.scale_row.set_title(i18n.t("prefs.scale"))
        self.scale_row.set_subtitle(i18n.t("prefs.scale_desc"))

        self.page_library.set_title(i18n.t("prefs.library_page"))
        self.group_folders.set_title(i18n.t("prefs.library_folders_group"))
        self.group_folders.set_description(i18n.t("prefs.library_folders_desc"))
        self.group_maintenance.set_title(i18n.t("prefs.maintenance_group"))
        self.row_scan.set_title(i18n.t("prefs.scan_new"))
        self.row_scan.set_subtitle(i18n.t("prefs.scan_new_desc"))
        self.row_reset.set_title(i18n.t("prefs.reset_db"))
        self.row_reset.set_subtitle(i18n.t("prefs.reset_db_desc"))

        self._rebuild_folder_rows()
        sel = self.theme_row.get_selected()
        self._update_theme_model()
        self.theme_row.set_selected(sel)

    def _on_lang_changed(self, row: Adw.ComboRow, _param):
        idx = row.get_selected()
        if 0 <= idx < len(LANG_CODES):
            lang_code = LANG_CODES[idx]
            self.cfg["language"] = lang_code
            save_config(self.cfg)
            i18n.set_language(lang_code)
            if self.on_config_changed:
                self.on_config_changed(self.cfg)

    def _on_device_changed(self, row: Adw.ComboRow, _param):
        idx = row.get_selected()
        if 0 <= idx < len(self._available_devices):
            dev = self._available_devices[idx]
            self.cfg["audio_device_id"] = dev.id
            save_config(self.cfg)
            if self.on_config_changed:
                self.on_config_changed(self.cfg)

    def _on_theme_changed(self, row: Adw.ComboRow, _param):
        idx = row.get_selected()
        theme = "system" if idx == 0 else ("light" if idx == 1 else "dark")
        self.cfg["theme"] = theme
        apply_theme(theme)
        save_config(self.cfg)
        if self.on_config_changed:
            self.on_config_changed(self.cfg)

    def _on_ui_scale_changed(self, row: Adw.SpinRow, _param):
        val = int(row.get_value())
        self.cfg["ui_scale"] = val
        apply_ui_scale(val)
        save_config(self.cfg)
        if self.on_config_changed:
            self.on_config_changed(self.cfg)
