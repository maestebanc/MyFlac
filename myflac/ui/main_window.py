"""Ventana principal de MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from ..audio.devices import AudioDevice, find_device_by_id, get_default_device
from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack
from ..config import save_config
from ..constants import APP_ID, APP_NAME
from ..library.db import LibraryDB
from ..library.scanner import LibraryScanner
from ..logger import get_logger
from .. import i18n
from .column_browser import ColumnBrowserView
from .device_popover import DeviceSelectionDialog
from .inspector_panel import InspectorPanel
from .library_setup_dialog import LibrarySetupDialog
from .player_bar import PlayerBar

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

        # 1. Base de datos y escáner de biblioteca musical
        self.db = LibraryDB()
        self.scanner = LibraryScanner(self.db)

        # 2. Inicializar motor de audio a través del mezclador del sistema
        dev_id = cfg.get("audio_device_id", "default")
        self.engine = AudioEngine(device_id=dev_id)
        self.engine.volume = cfg.get("software_volume", 1.0)

        # 3. Configurar vistas de UI
        self._build_ui()
        self._setup_actions_and_shortcuts()

        # 4. Cablear eventos de reproducción automática de listas
        self.engine.on_track_finished = self._on_track_finished
        self.engine.on_error = self._on_playback_error
        self.engine.add_state_listener(self._on_engine_state_changed)
        self.engine.add_track_listener(self._on_engine_track_changed)

        # Ajuste inteligente del panel inspector al redimensionar / maximizar
        self.connect("map", lambda *_: GLib.idle_add(self._on_window_mapped))
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

        # Indicador / Botón de escaneo a la izquierda
        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        scan_box.set_valign(Gtk.Align.CENTER)

        self.btn_scan = Gtk.Button()
        self.btn_scan.set_icon_name("view-refresh-symbolic")
        self.btn_scan.set_tooltip_text(i18n.t("header.scan_library"))
        self.btn_scan.connect("clicked", lambda *_: self._trigger_library_scan(quick=True, silent=False))
        scan_box.append(self.btn_scan)

        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        scan_box.append(self.spinner)

        self.scan_status_label = Gtk.Label(label="")
        self.scan_status_label.add_css_class("dim-label")
        self.scan_status_label.set_visible(False)
        scan_box.append(self.scan_status_label)

        self.header_bar.pack_start(scan_box)

        # Título limpio en el centro
        self.window_title = Adw.WindowTitle(
            title=APP_NAME,
            subtitle=i18n.t("app.subtitle"),
        )
        self.header_bar.set_title_widget(self.window_title)

        # Botón de búsqueda desplegable
        self.btn_search = Gtk.ToggleButton()
        self.btn_search.set_icon_name("system-search-symbolic")
        self.btn_search.set_tooltip_text(i18n.t("header.search_tooltip"))
        self.header_bar.pack_end(self.btn_search)

        # Menú principal a la derecha
        self.menu_btn = Gtk.MenuButton()
        self.menu_btn.set_icon_name("open-menu-symbolic")
        self._rebuild_menu()
        self.header_bar.pack_end(self.menu_btn)

        # Barra de búsqueda desplegable debajo de la cabecera (Gtk.SearchBar)
        self.search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(i18n.t("header.search_placeholder"))
        self.search_entry.set_size_request(340, -1)
        self.search_entry.connect(
            "search-changed",
            lambda entry: self.browser.set_search_query(entry.get_text()),
        )
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.set_key_capture_widget(self)
        self.btn_search.bind_property(
            "active",
            self.search_bar,
            "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL,
        )

        self.toolbar_view.add_top_bar(self.search_bar)

        # Panel central dividido (Paned: Navegador de biblioteca | Inspector audiófilo)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_resize_start_child(True)
        self.paned.set_resize_end_child(False)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)

        # Navegador multicolumnas estilo iTunes (Artista -> Álbum -> Tema)
        self.browser = ColumnBrowserView(db=self.db, on_track_activate=self._on_track_activated)
        self.paned.set_start_child(self.browser)

        # Panel Inspector de audio
        self.inspector = InspectorPanel()
        self.paned.set_end_child(self.inspector)

        # Barra inferior del reproductor (altura acotada a 64px)
        self.player_bar = PlayerBar(
            engine=self.engine,
            on_device_click=lambda: self._open_device_dialog(),
        )
        self.player_bar.on_play_pause_clicked = self._toggle_play_pause
        self.player_bar.on_previous_clicked = self._play_previous
        self.player_bar.on_next_clicked = self._play_next
        self.player_bar.on_repeat_clicked = self._cycle_repeat_mode
        self.player_bar.on_shuffle_toggled = self._on_shuffle_toggled

        # Contenedor inferior: Barra de progreso azul no obstructiva + Barra del reproductor
        self.bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Barra de progreso: delgada línea azul de 2px justo encima del minireproductor
        self.scan_progress_bar = Gtk.ProgressBar()
        self.scan_progress_bar.add_css_class("scan-progress-line")
        self.scan_progress_bar.set_visible(False)
        self.scan_progress_bar.set_fraction(0.0)

        self.bottom_box.append(self.scan_progress_bar)
        self.bottom_box.append(self.player_bar)

        self.toolbar_view.set_content(self.paned)
        self.toolbar_view.add_bottom_bar(self.bottom_box)
        self.set_content(self.toolbar_view)

    def _on_window_mapped(self):
        self._adjust_paned_position()
        self._check_library_and_startup()

    def _check_library_and_startup(self):
        """Verifica si hay carpetas en la biblioteca al iniciar la aplicación."""
        configured_folders = self.cfg.get("library_folders", [])
        db_folders = self.db.get_library_folders()

        # Sincronizar si hace falta
        all_folders = list(dict.fromkeys(configured_folders + db_folders))
        valid_folders = [f for f in all_folders if os.path.isdir(f)]

        if not valid_folders:
            log.info("No hay carpetas de biblioteca configuradas. Mostrando diálogo de bienvenida...")
            self._show_library_setup_dialog()
        else:
            self.cfg["library_folders"] = valid_folders
            save_config(self.cfg)
            for f in valid_folders:
                self.db.add_library_folder(f)

            # Carga instantánea de los datos ya indexados en SQLite
            self.browser.load_initial_data()

            first_track = self.browser.get_selected_or_first_track()
            if first_track and not self.inspector.current_track:
                self.inspector.set_track(first_track)
                self.player_bar.set_track(first_track)

            # Escaneo RÁPIDO y transparente en segundo plano (no bloquea)
            log.info("Iniciando escaneo rápido de inicio en segundo plano...")
            self._trigger_library_scan(quick=True, silent=True)

    def _show_library_setup_dialog(self):
        dlg = LibrarySetupDialog(parent=self, on_folder_chosen=self._on_initial_folder_chosen)
        dlg.present()

    def _on_initial_folder_chosen(self, folder_path: str):
        log.info("Carpeta inicial seleccionada: %s", folder_path)
        folders = self.cfg.setdefault("library_folders", [])
        if folder_path not in folders:
            folders.append(folder_path)
            save_config(self.cfg)
        self.db.add_library_folder(folder_path)

        # Iniciar escaneo completo de la nueva carpeta
        self._trigger_library_scan(quick=False, silent=False)

    def _trigger_library_scan(self, quick: bool = True, silent: bool = False):
        folders = self.cfg.get("library_folders", [])
        if not folders:
            self._show_library_setup_dialog()
            return

        # Mostrar línea azul sutil de progreso no obstructiva
        self.scan_progress_bar.set_fraction(0.0)
        self.scan_progress_bar.set_visible(True)

        if not silent:
            self.spinner.start()
            self.spinner.set_visible(True)
            self.scan_status_label.set_text(i18n.t("header.library_status_scanning"))
            self.scan_status_label.set_visible(True)
            self.btn_scan.set_sensitive(False)

        def _on_progress(current: int, total: int):
            if not self.scan_progress_bar.get_visible():
                self.scan_progress_bar.set_visible(True)
            if total > 0:
                fraction = min(1.0, max(0.0, current / total))
                self.scan_progress_bar.set_fraction(fraction)
            else:
                self.scan_progress_bar.pulse()

        def _on_finished(result: dict):
            self.spinner.stop()
            self.spinner.set_visible(False)
            self.btn_scan.set_sensitive(True)

            self.scan_progress_bar.set_fraction(1.0)
            GLib.timeout_add(700, lambda: self.scan_progress_bar.set_visible(False))

            if not silent:
                self.scan_status_label.set_text(i18n.t("header.library_status_done"))
                GLib.timeout_add(3000, lambda: self.scan_status_label.set_visible(False))

            # Si se añadieron, actualizaron o eliminaron temas, refrescar la interfaz
            if result.get("added_or_updated", 0) > 0 or result.get("deleted", 0) > 0 or not quick:
                self.browser.refresh_artists()
                self.browser.refresh_albums()
                self.browser.refresh_tracks()

            if not self.inspector.current_track:
                first = self.browser.get_selected_or_first_track()
                if first:
                    self.inspector.set_track(first)

        self.scanner.start_scan(folders, quick=quick, on_finished=_on_finished, on_progress=_on_progress)

    def on_library_updated(self):
        """Llamado cuando las carpetas de biblioteca se modifican desde Preferencias."""
        self.browser.refresh_artists()
        self.browser.refresh_albums()
        self.browser.refresh_tracks()

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
        menu.append(i18n.t("menu.view_log"), "app.open_log")
        menu.append(i18n.t("menu.about"), "app.about")
        self.menu_btn.set_menu_model(menu)

    def _on_language_changed(self, _lang: str):
        """Actualiza tooltips, búsqueda y menú al cambiar el idioma en caliente."""
        self.btn_scan.set_tooltip_text(i18n.t("header.scan_library"))
        self.btn_search.set_tooltip_text(i18n.t("header.search_tooltip"))
        self.search_entry.set_placeholder_text(i18n.t("header.search_placeholder"))
        self.window_title.set_subtitle(i18n.t("app.subtitle"))
        self._rebuild_menu()
        self._update_output_status()
        self.browser.refresh_i18n()

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
        if keyval in (Gdk.KEY_r, Gdk.KEY_R) and (state & Gdk.ModifierType.CONTROL_MASK):
            log.debug("Atajo teclado: Ctrl+R -> escanear biblioteca")
            self._trigger_library_scan(quick=True, silent=False)
            return True
        if keyval in (Gdk.KEY_f, Gdk.KEY_F) and (state & Gdk.ModifierType.CONTROL_MASK):
            log.debug("Atajo teclado: Ctrl+F -> activar búsqueda")
            self.btn_search.set_active(not self.btn_search.get_active())
            if self.btn_search.get_active():
                self.search_entry.grab_focus()
            return True
        return False

    def _toggle_play_pause(self):
        """Alterna reproducción y pausa. Si no hay pista activa, arranca la primera pista disponible."""
        if not self.engine.current_track:
            track = self.browser.get_selected_or_first_track()
            if track:
                log.info("Play accionado sin pista activa -> iniciando: '%s'", track.title)
                self.browser.set_current_playing_track(track)
                self._on_track_activated(track)
                return
            else:
                log.info("Play accionado pero no hay pistas cargadas en la lista")
                return
        self.engine.toggle_play_pause()

    def _on_track_activated(self, track: AudioTrack):
        log.info("Pista activada: '%s' - '%s'", track.artist, track.title)
        self.browser.set_current_playing_track(track, is_paused=False)
        self.inspector.set_track(track)
        self.player_bar.set_track(track)
        self.engine.load_track(track, play_now=True)
        self._prepare_gapless_next()
        self._update_output_status()

    def _on_engine_track_changed(self, track: AudioTrack):
        """Notificado cuando cambia la pista en reproducción (incluyendo encadenamiento gapless)."""
        is_paused = (self.engine.state == PlaybackState.PAUSED)
        self.browser.set_current_playing_track(track, is_paused=is_paused)
        self.inspector.set_track(track)
        self.player_bar.set_track(track)
        self._prepare_gapless_next()
        self._update_output_status()

    def _prepare_gapless_next(self):
        shuffle = self.cfg.get("shuffle", False)
        repeat = self.cfg.get("repeat_mode", "none")
        nxt = self.browser.get_next_track(shuffle=shuffle, repeat_mode=repeat)
        self.engine.queue_next_track(nxt)

    def _play_next(self):
        shuffle = self.cfg.get("shuffle", False)
        repeat = self.cfg.get("repeat_mode", "none")
        nxt = self.browser.get_next_track(shuffle=shuffle, repeat_mode=repeat)
        if nxt:
            log.info("Avanzando a siguiente pista: '%s'", nxt.title)
            self._on_track_activated(nxt)
        else:
            log.info("Fin de la lista de reproducción alcanzado")

    def _play_previous(self):
        prev = self.browser.get_previous_track()
        if prev:
            log.info("Retrocediendo a pista anterior: '%s'", prev.title)
            self._on_track_activated(prev)

    def _on_track_finished(self):
        log.debug("Evento de pista finalizada recibido en MainWindow")
        GLib.idle_add(self._play_next)

    def _on_playback_error(self, err_msg: str):
        log.error("Aviso de error en reproducción: %s", err_msg)

    def _on_engine_state_changed(self, state: PlaybackState):
        self._update_output_status()
        is_playing = (state == PlaybackState.PLAYING)
        is_paused = (state == PlaybackState.PAUSED)
        self.browser.update_playback_state(
            is_playing=is_playing or is_paused,
            is_paused=is_paused,
        )

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

    def _open_device_dialog(self):
        log.info("Abriendo diálogo de selección de dispositivo de salida")
        dlg = DeviceSelectionDialog(
            current_device_id=self.engine.device_id,
            on_device_selected=self._on_device_selected,
            parent=self,
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
        self.scanner.stop()
        self.engine.stop()
        w, h = self.get_default_size()
        self.cfg["window_width"] = w
        self.cfg["window_height"] = h
        self.cfg["window_maximized"] = self.is_maximized()
        self.cfg["software_volume"] = self.engine.volume
        save_config(self.cfg)
        log.info("Configuración final guardada. Adiós.")
        return False
