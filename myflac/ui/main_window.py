"""Ventana principal de MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..audio.devices import AudioDevice, find_device_by_id, get_default_device
from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack, load_track
from ..config import save_config
from ..constants import APP_ID, APP_NAME, SUPPORTED_EXTENSIONS
from ..logger import get_logger
from .. import i18n
from .about_dialog import build_about_dialog
from .device_popover import DeviceSelectionDialog
from .inspector_panel import InspectorPanel
from .player_bar import PlayerBar
from .track_list import TrackListView

log = get_logger("ui.main_window")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, cfg: dict):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_icon_name(APP_ID)
        w = max(1200, cfg.get("window_width", 1280))
        h = max(800, cfg.get("window_height", 850))
        self.set_default_size(w, h)
        if cfg.get("window_maximized", False):
            self.maximize()

        self.cfg = cfg

        # 1. Inicializar motor de audio a través del mezclador del sistema
        dev_id = cfg.get("audio_device_id", "default")
        self.engine = AudioEngine(device_id=dev_id)
        self.engine.volume = cfg.get("software_volume", 1.0)

        # 2. Configurar vistas de UI
        self._build_ui()
        self._setup_actions_and_shortcuts()

        # 3. Cablear eventos de reproducción automática de listas
        self.engine.on_track_finished = self._on_track_finished
        self.engine.on_error = self._on_playback_error
        self.engine.add_state_listener(self._on_engine_state_changed)

        # Ajuste inteligente del panel inspector al redimensionar / maximizar
        self.connect("map", lambda *_: GLib.idle_add(self._adjust_paned_position))
        self.connect("notify::maximized", lambda *_: GLib.idle_add(self._adjust_paned_position))

        # Registrar listener para cambios dinámicos de idioma
        i18n.add_language_listener(self._on_language_changed)

        # Guardar dimensiones al cerrar
        self.connect("close-request", self._on_close_request)

        # Notificar estado inicial al inspector
        self._update_output_status()

    def _build_ui(self):
        self.toolbar_view = Adw.ToolbarView()

        # HeaderBar
        self.header_bar = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(self.header_bar)

        # Botones de apertura a la izquierda
        open_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.btn_open_folder = Gtk.Button()
        self.btn_open_folder.set_icon_name("folder-open-symbolic")
        self.btn_open_folder.set_tooltip_text(i18n.t("header.open_folder"))
        self.btn_open_folder.connect("clicked", lambda *_: self._choose_folder())
        open_box.append(self.btn_open_folder)

        self.btn_open_files = Gtk.Button()
        self.btn_open_files.set_icon_name("document-open-symbolic")
        self.btn_open_files.set_tooltip_text(i18n.t("header.open_files"))
        self.btn_open_files.connect("clicked", lambda *_: self._choose_files())
        open_box.append(self.btn_open_files)

        self.btn_clear = Gtk.Button()
        self.btn_clear.set_icon_name("edit-clear-all-symbolic")
        self.btn_clear.set_tooltip_text(i18n.t("header.clear_playlist"))
        self.btn_clear.connect("clicked", lambda *_: self._clear_playlist())
        open_box.append(self.btn_clear)

        self.header_bar.pack_start(open_box)

        # Búsqueda en el centro
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(i18n.t("header.search_placeholder"))
        self.search_entry.set_size_request(240, -1)
        self.search_entry.connect("search-changed", lambda entry: self.track_list.set_search_query(entry.get_text()))
        self.header_bar.set_title_widget(self.search_entry)

        # Menú principal a la derecha
        self.menu_btn = Gtk.MenuButton()
        self.menu_btn.set_icon_name("open-menu-symbolic")
        self._rebuild_menu()
        self.header_bar.pack_end(self.menu_btn)

        # Panel central dividido (Paned: Lista de pistas | Inspector audiófilo)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # Asignar todo el crecimiento a la lista de canciones para que no se estire el inspector
        self.paned.set_resize_start_child(True)
        self.paned.set_resize_end_child(False)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)

        # Vista de canciones
        self.track_list = TrackListView(on_track_activate=self._on_track_activated)
        self.paned.set_start_child(self.track_list)

        # Panel Inspector de audio
        self.inspector = InspectorPanel()
        self.paned.set_end_child(self.inspector)

        # Barra inferior del reproductor (altura acotada a 64px)
        self.player_bar = PlayerBar(
            engine=self.engine,
            on_device_click=lambda: self._open_device_dialog()
        )
        self.player_bar.on_play_pause_clicked = self._toggle_play_pause
        self.player_bar.on_previous_clicked = self._play_previous
        self.player_bar.on_next_clicked = self._play_next
        self.player_bar.on_repeat_clicked = self._cycle_repeat_mode
        self.player_bar.on_shuffle_toggled = self._on_shuffle_toggled

        self.toolbar_view.set_content(self.paned)
        self.toolbar_view.add_bottom_bar(self.player_bar)
        self.set_content(self.toolbar_view)

    def _adjust_paned_position(self):
        """Mantiene el panel inspector acotado a ~340px al redimensionar o maximizar."""
        w = self.get_width()
        if w > 650:
            target_pos = max(400, w - 340)
            self.paned.set_position(target_pos)
            log.debug("Ajustada posición del Paned a %d (ancho ventana: %d)", target_pos, w)

    def _rebuild_menu(self):
        """Construye el menú de la aplicación con los textos traducidos."""
        menu = Gio.Menu()
        menu.append(i18n.t("menu.preferences"), "app.preferences")
        menu.append(i18n.t("menu.devices"), "win.select_device")
        menu.append(i18n.t("menu.view_log"), "app.open_log")
        menu.append(i18n.t("menu.about"), "app.about")
        self.menu_btn.set_menu_model(menu)

    def _on_language_changed(self, _lang: str):
        """Actualiza tooltips, búsqueda y menú al cambiar el idioma en caliente."""
        self.btn_open_folder.set_tooltip_text(i18n.t("header.open_folder"))
        self.btn_open_files.set_tooltip_text(i18n.t("header.open_files"))
        self.btn_clear.set_tooltip_text(i18n.t("header.clear_playlist"))
        self.search_entry.set_placeholder_text(i18n.t("header.search_placeholder"))
        self._rebuild_menu()
        self._update_output_status()

    def _setup_actions_and_shortcuts(self):
        action_dev = Gio.SimpleAction.new("select_device", None)
        action_dev.connect("activate", lambda *_: self._open_device_dialog())
        self.add_action(action_dev)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_space:
            focus = self.get_focus()
            if not isinstance(focus, (Gtk.Entry, Gtk.SearchEntry, Gtk.Editable)):
                log.debug("Atajo teclado: Espacio -> toggle play/pause")
                self._toggle_play_pause()
                return True
        if keyval in (Gdk.KEY_o, Gdk.KEY_O) and (state & Gdk.ModifierType.CONTROL_MASK):
            if state & Gdk.ModifierType.SHIFT_MASK:
                log.debug("Atajo teclado: Ctrl+Shift+O -> abrir archivos")
                self._choose_files()
            else:
                log.debug("Atajo teclado: Ctrl+O -> abrir carpeta")
                self._choose_folder()
            return True
        return False

    def _toggle_play_pause(self):
        """Alterna reproducción y pausa. Si no hay pista activa, arranca la primera pista disponible."""
        if not self.engine.current_track:
            track = self.track_list.get_selected_or_first_track()
            if track:
                log.info("Play accionado sin pista activa -> iniciando reproducción de: '%s'", track.title)
                self.track_list.set_current_playing_track(track)
                self._on_track_activated(track)
                return
            else:
                log.info("Play accionado pero no hay pistas cargadas en la lista")
                return
        self.engine.toggle_play_pause()

    def _on_track_activated(self, track: AudioTrack):
        log.info("Pista activada por usuario: '%s' - '%s'", track.artist, track.title)
        self.inspector.set_track(track)
        self.engine.load_track(track, play_now=True)
        self._prepare_gapless_next()
        self._update_output_status()

    def _prepare_gapless_next(self):
        shuffle = self.cfg.get("shuffle", False)
        repeat = self.cfg.get("repeat_mode", "none")
        nxt = self.track_list.get_next_track(shuffle=shuffle, repeat_mode=repeat)
        self.engine.queue_next_track(nxt)

    def _play_next(self):
        shuffle = self.cfg.get("shuffle", False)
        repeat = self.cfg.get("repeat_mode", "none")
        nxt = self.track_list.get_next_track(shuffle=shuffle, repeat_mode=repeat)
        if nxt:
            log.info("Avanzando a siguiente pista: '%s'", nxt.title)
            self.track_list.set_current_playing_track(nxt)
            self._on_track_activated(nxt)
        else:
            log.info("Fin de la lista de reproducción alcanzado")

    def _play_previous(self):
        prev = self.track_list.get_previous_track()
        if prev:
            log.info("Retrocediendo a pista anterior: '%s'", prev.title)
            self.track_list.set_current_playing_track(prev)
            self._on_track_activated(prev)

    def _on_track_finished(self):
        log.debug("Evento de pista finalizada recibido en MainWindow")
        GLib.idle_add(self._play_next)

    def _on_playback_error(self, err_msg: str):
        log.error("Aviso de error en reproducción: %s", err_msg)

    def _on_engine_state_changed(self, state: PlaybackState):
        self._update_output_status()

    def _update_output_status(self):
        dev = find_device_by_id(self.engine.device_id) or get_default_device(self.engine.device_id)
        info = {
            "device_name": dev.name,
            "is_playing": self.engine.state == PlaybackState.PLAYING,
            "is_paused": self.engine.state == PlaybackState.PAUSED,
        }
        self.inspector.update_dac_status(info)
        self.player_bar.update_active_device()

    def _cycle_repeat_mode(self):
        curr = self.cfg.get("repeat_mode", "none")
        modes = ["none", "all", "one"]
        nxt_mode = modes[(modes.index(curr) + 1) % len(modes)]
        log.info("Ciclo de modo repetición: %s -> %s", curr, nxt_mode)
        self.cfg["repeat_mode"] = nxt_mode
        save_config(self.cfg)
        icons = {
            "none": "media-playlist-repeat-symbolic",
            "all": "media-playlist-repeat-symbolic",
            "one": "media-playlist-repeat-song-symbolic",
        }
        self.player_bar.repeat_btn.set_icon_name(icons.get(nxt_mode, "media-playlist-repeat-symbolic"))
        if nxt_mode != "none":
            self.player_bar.repeat_btn.add_css_class("accent")
        else:
            self.player_bar.repeat_btn.remove_css_class("accent")

    def _on_shuffle_toggled(self, active: bool):
        log.info("Modo aleatorio (shuffle) cambiado a: %s", active)
        self.cfg["shuffle"] = active
        save_config(self.cfg)
        self._prepare_gapless_next()

    def _clear_playlist(self):
        log.info("Vaciando lista de canciones")
        self.engine.stop()
        self.track_list.add_tracks([], clear=True)
        self.inspector.set_track(None)
        self._update_output_status()

    def _choose_folder(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title(i18n.t("dialog.open_folder_title"))
        last_dir = self.cfg.get("last_directory")
        if last_dir and os.path.isdir(last_dir):
            dialog.set_initial_folder(Gio.File.new_for_path(last_dir))

        def on_folder_selected(dlg: Gtk.FileDialog, res):
            try:
                gfile = dlg.select_folder_finish(res)
                if gfile:
                    folder_path = gfile.get_path()
                    log.info("Carpeta seleccionada por usuario: %s", folder_path)
                    self.cfg["last_directory"] = folder_path
                    save_config(self.cfg)
                    self._load_directory(folder_path)
            except Exception as e:
                log.debug("Selección de carpeta cancelada o fallida: %s", e)

        dialog.select_folder(self, None, on_folder_selected)

    def _choose_files(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title(i18n.t("dialog.open_files_title"))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f_audio = Gtk.FileFilter()
        f_audio.set_name(i18n.t("dialog.filter_audio"))
        for ext in SUPPORTED_EXTENSIONS:
            f_audio.add_pattern(f"*{ext}")
            f_audio.add_pattern(f"*{ext.upper()}")
        filters.append(f_audio)
        dialog.set_filters(filters)

        def on_files_selected(dlg: Gtk.FileDialog, res):
            try:
                files_list = dlg.open_multiple_finish(res)
                loaded = []
                for i in range(files_list.get_n_items()):
                    f = files_list.get_item(i)
                    p = f.get_path()
                    if p:
                        t = load_track(p)
                        if t:
                            loaded.append(t)
                if loaded:
                    log.info("Cargadas %d pistas individuales seleccionadas", len(loaded))
                    loaded.sort(key=lambda x: ((x.disc_number or 1) * 100000 + (x.track_number or 99999), x.filename))
                    self.track_list.add_tracks(loaded, clear=False)
            except Exception as e:
                log.debug("Selección de archivos cancelada o fallida: %s", e)

        dialog.open_multiple(self, None, on_files_selected)

    def _load_directory(self, folder_path: str):
        log.info("Escaneando directorio de música: %s", folder_path)
        loaded = []
        for root, _, files in os.walk(folder_path):
            for file in sorted(files):
                if file.lower().endswith(SUPPORTED_EXTENSIONS):
                    full_p = os.path.join(root, file)
                    t = load_track(full_p)
                    if t:
                        loaded.append(t)

        log.info("Total de pistas encontradas en %s: %d", folder_path, len(loaded))
        if loaded:
            loaded.sort(key=lambda x: ((x.disc_number or 1) * 100000 + (x.track_number or 99999), x.filename))
            self.track_list.add_tracks(loaded, clear=True)
            first_track = loaded[0]
            self.inspector.set_track(first_track)

    def _open_device_dialog(self):
        log.info("Abriendo diálogo de selección de dispositivo de salida")
        dlg = DeviceSelectionDialog(
            current_device_id=self.engine.device_id,
            on_device_selected=self._on_device_selected,
            parent=self
        )
        dlg.present()

    def _on_device_selected(self, dev: AudioDevice):
        log.info("Usuario seleccionó dispositivo: '%s' [%s]", dev.name, dev.id)
        self.cfg["audio_device_id"] = dev.id
        save_config(self.cfg)
        self.engine.set_device(dev.id)
        self._update_output_status()

    def _on_close_request(self, _window) -> bool:
        log.info("Cerrando aplicación...")
        self.engine.stop()
        w, h = self.get_default_size()
        self.cfg["window_width"] = w
        self.cfg["window_height"] = h
        self.cfg["window_maximized"] = self.is_maximized()
        self.cfg["software_volume"] = self.engine.volume
        save_config(self.cfg)
        log.info("Configuración final guardada. Adiós.")
        return False
