"""Ventana principal de MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from ..audio.devices import AudioDevice, base_node_name, find_device_by_id, get_default_device
from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack, load_track
from ..audio.mpris import MprisServer
from ..config import is_device_exclusive_enabled, save_config, set_device_exclusive_enabled
from ..hires_cover import HiResCoverService
from ..music_info import MusicInfoService
from .. import __version__
from ..constants import APP_ID, APP_NAME
from ..library.db import LibraryDB
from ..library.scanner import LibraryScanner
from ..logger import get_logger
from .. import i18n
from .backdrop import DEFAULT_INTENSITY, ArtistBackdrop
from .column_browser import ColumnBrowserView
from .cover_popup import CoverPopup
from .shortcuts import build_shortcuts_dialog, handle_playback_key
from .device_popover import DeviceSelectionDialog
from .inspector_panel import InspectorPanel
from .library_setup_dialog import LibrarySetupDialog
from .mini_player import MiniPlayerWindow
from .player_bar import PlayerBar
from .style import apply_theme

# Altura por defecto (px) de los paneles Artista/Álbum sobre la lista de temas
DEFAULT_BROWSER_SPLIT = 430
# Segundos que debe sonar una pista antes de precargar sus fichas
INFO_PREFETCH_DELAY = 8

log = get_logger("ui.main_window")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, cfg: dict):
        super().__init__(application=app)
        self.set_title(f"{APP_NAME} {__version__}")
        self.set_icon_name(APP_ID)
        w = max(1200, cfg.get("window_width", 1280))
        h = max(800, cfg.get("window_height", 850))
        self.set_default_size(w, h)
        if cfg.get("window_maximized", False):
            self.maximize()

        self.cfg = cfg
        self._inhibit_cookie: int = 0
        self.play_queue: list[AudioTrack] = []
        self._pending_activation: AudioTrack | None = None
        self.mini_player: MiniPlayerWindow | None = None
        self._initial_startup_done = False

        # 1. Base de datos y escáner de biblioteca musical
        self.db = LibraryDB()
        self.scanner = LibraryScanner(self.db)

        # 2. Inicializar motor de audio a través del mezclador del sistema
        dev_id = cfg.get("audio_device_id", "default")
        ex_mode = False
        if dev_id != "default":
            ex_mode = is_device_exclusive_enabled(cfg, dev_id)
        self.engine = AudioEngine(
            device_id=dev_id,
            volume=cfg.get("software_volume", 1.0),
            exclusive=ex_mode,
        )
        self.engine.set_levels_enabled(cfg.get("oscilloscope_enabled", True))

        # 3. Servidor D-Bus MPRIS2 (control por teclas multimedia, auriculares y GNOME)
        self.mpris = MprisServer(window=self, engine=self.engine)

        # 3. Configurar vistas de UI
        self._build_ui()
        self._setup_actions_and_shortcuts()

        # 4. Cablear eventos de reproducción automática de listas
        self.engine.on_track_finished = self._on_track_finished
        self.engine.on_error = self._on_playback_error
        self.engine.add_state_listener(self._on_engine_state_changed)
        self.engine.add_track_listener(self._on_engine_track_changed)
        self.engine.add_output_listener(self._update_output_status)

        # Ajuste inteligente del panel inspector al redimensionar / maximizar
        self.connect("map", lambda *_: GLib.idle_add(self._on_window_mapped))
        self.connect("notify::maximized", lambda *_: GLib.idle_add(self._adjust_paned_position))

        # Registrar listener para cambios dinámicos de idioma y tema
        i18n.add_language_listener(self._on_language_changed)
        style_mgr = Adw.StyleManager.get_default()
        if style_mgr:
            style_mgr.connect("notify::dark", lambda *_: self._update_theme_button_ui())

        # Guardar dimensiones al cerrar
        self.connect("close-request", self._on_close_request)

        # Notificar estado inicial al inspector
        self._update_output_status()

        # Restaurar inmediatamente el estado de la sesión guardada (artista, álbum, pista, posición)
        self._restore_saved_session_state()

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

        # Título limpio en el centro con versión y sin subtítulo
        self.window_title = Adw.WindowTitle(
            title=f"{APP_NAME} {__version__}",
        )
        self.header_bar.set_title_widget(self.window_title)

        # Botón de búsqueda desplegable
        self.btn_search = Gtk.ToggleButton()
        self.btn_search.set_icon_name("system-search-symbolic")
        self.btn_search.set_tooltip_text(i18n.t("header.search_tooltip"))

        # Botón para cambiar entre modo claro y oscuro (junto a la lupa)
        self.btn_theme = Gtk.Button()
        self.btn_theme.connect("clicked", lambda *_: self._toggle_theme())
        self._update_theme_button_ui()

        # Botón para activar Mini-Reproductor
        self.btn_mini_player = Gtk.Button()
        self.btn_mini_player.set_icon_name("window-pop-out-symbolic")
        self.btn_mini_player.set_tooltip_text(i18n.t("header.mini_player"))
        self.btn_mini_player.connect("clicked", lambda *_: self._open_mini_player())

        # Botón para activar Super-Reproductor a Pantalla Completa
        self.btn_fullscreen = Gtk.Button()
        self.btn_fullscreen.set_icon_name("view-fullscreen-symbolic")
        self.btn_fullscreen.set_tooltip_text(i18n.t("header.super_player"))
        self.btn_fullscreen.connect("clicked", lambda *_: self._open_super_player())

        # Menú principal a la derecha
        self.menu_btn = Gtk.MenuButton()
        self.menu_btn.set_icon_name("open-menu-symbolic")
        self._rebuild_menu()

        # Empaquetar en el extremo derecho (orden visual LTR: Tema, Buscar, Mini-Reproductor, Super-Reproductor, Menú)
        self.header_bar.pack_end(self.menu_btn)
        self.header_bar.pack_end(self.btn_fullscreen)
        self.header_bar.pack_end(self.btn_mini_player)
        self.header_bar.pack_end(self.btn_search)
        self.header_bar.pack_end(self.btn_theme)

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
        self.browser = ColumnBrowserView(
            db=self.db,
            on_track_activate=self._on_track_activated,
            on_play_next_queue=self._on_play_next_queue,
            on_add_to_queue=self._on_add_to_queue,
        )
        # La biblioteca, con la foto del artista en reproducción desenfocada de fondo
        self.library_backdrop = ArtistBackdrop(
            self.browser,
            enabled=self.cfg.get("backdrop_enabled", False),
            intensity=self.cfg.get("backdrop_intensity", DEFAULT_INTENSITY),
        )
        self.paned.set_start_child(self.library_backdrop)

        # Panel Inspector de audio con visualizadores en tiempo real
        self.inspector = InspectorPanel(engine=self.engine)
        self.inspector.on_album_activate = self._on_album_activate_from_inspector
        self.inspector.on_visualizer_mode_changed = self._on_visualizer_mode_changed
        self.paned.set_end_child(self.inspector)

        # Barra inferior del reproductor (altura acotada a 64px)
        self.player_bar = PlayerBar(
            engine=self.engine,
            on_device_click=lambda: None,
        )
        self.player_bar.on_play_pause_clicked = self._toggle_play_pause
        self.player_bar.on_previous_clicked = self._play_previous
        self.player_bar.on_next_clicked = self._play_next
        self.player_bar.on_repeat_clicked = self._cycle_repeat_mode
        self.player_bar.on_shuffle_toggled = self._on_shuffle_toggled
        self.player_bar.on_clear_queue_clicked = self._on_clear_queue
        self.player_bar.on_queue_track_removed = self._on_remove_from_queue
        self.player_bar.on_device_selected = self._on_device_selected
        self.player_bar.on_device_exclusive_toggled = self._on_device_exclusive_toggled
        self.player_bar.is_device_exclusive_enabled_cb = lambda dev: is_device_exclusive_enabled(self.cfg, dev)
        self.player_bar.on_exclusive_toggled = self._on_exclusive_toggled
        self.player_bar.on_cover_clicked = self._toggle_cover_popup

        # Vincular el osciloscopio de la mini-portada al panel inspector
        self.inspector._player_bar = self.player_bar
        is_scope = (self.inspector.visualizer_mode == 0) and getattr(self.inspector, "_oscilloscope_enabled", True)
        self.player_bar.set_bar_oscilloscope_enabled(is_scope)

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
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.toolbar_view)

        # Portada a gran tamaño superpuesta a toda la ventana (clic en la mini carátula de la barra)
        self.cover_popup = CoverPopup()
        root_overlay = Gtk.Overlay()
        root_overlay.set_child(self.toast_overlay)
        root_overlay.add_overlay(self.cover_popup)
        self.set_content(root_overlay)
        self._setup_browser_split()

    # -------------------------------------------------------------------------
    # Altura de los paneles Artista/Álbum: fija por defecto; si el usuario mueve el divisor,
    # su posición se guarda como preferencia
    # -------------------------------------------------------------------------
    def _setup_browser_split(self):
        self._split_moved_by_user = False
        v_paned = self.browser.v_paned
        v_paned.set_position(int(self.cfg.get("browser_split_position", DEFAULT_BROWSER_SPLIT)))
        drag = Gtk.GestureDrag()
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag.connect("drag-begin", self._on_split_drag_begin)
        v_paned.add_controller(drag)

    def _on_split_drag_begin(self, _gesture, _x, y):
        # Solo cuenta si el arrastre empieza sobre el divisor (no en las listas)
        if abs(y - self.browser.v_paned.get_position()) <= 8:
            self._split_moved_by_user = True

    def _on_window_mapped(self):
        self._adjust_paned_position()
        if not self._initial_startup_done:
            self._initial_startup_done = True
            if getattr(self, "_needs_initial_setup", False):
                self._show_library_setup_dialog()
            else:
                # Escaneo RÁPIDO y transparente en segundo plano (no bloquea el inicio ni la UI)
                log.info("Iniciando escaneo rápido de inicio en segundo plano...")
                GLib.idle_add(lambda: self._trigger_library_scan(quick=True, silent=True))

    def _restore_saved_session_state(self):
        """Restaura instantáneamente el estado guardado de la sesión anterior (artista, álbum, pista, posición)."""
        configured_folders = self.cfg.get("library_folders", [])
        db_folders = self.db.get_library_folders()

        # Sincronizar si hace falta
        all_folders = list(dict.fromkeys(configured_folders + db_folders))
        valid_folders = [f for f in all_folders if os.path.isdir(f)]

        if not valid_folders:
            log.info("No hay carpetas de biblioteca configuradas.")
            self._needs_initial_setup = True
            return

        self._needs_initial_setup = False
        self.cfg["library_folders"] = valid_folders
        save_config(self.cfg)
        for f in valid_folders:
            self.db.add_library_folder(f)

        last_path = self.cfg.get("last_track_path", "")
        last_artist = self.cfg.get("last_artist", "__ALL__")
        last_album = self.cfg.get("last_album", "__ALL__")
        known_selection = last_artist and last_artist != "__ALL__" and last_album and last_album != "__ALL__"

        # Carga instantánea de los datos indexados en SQLite filtrados por el estado previo
        if known_selection or not last_path:
            self.browser.load_initial_data(initial_artist=last_artist, initial_album=last_album)
        if not last_path:
            self._show_first_track()
            return

        # La pista anterior (metadatos y portada) se lee en otro hilo: si está en una unidad de red,
        # el arranque no se congela esperando al servidor
        def load_last():
            track = None
            try:
                if os.path.exists(last_path):
                    track = load_track(last_path)
                    if track:
                        track.get_cover_image_bytes()
            except Exception as e:
                log.warning("No se pudo cargar la pista previa para restaurar estado: %s", e)
            GLib.idle_add(self._finish_session_restore, track, None if known_selection else (last_artist, last_album))

        threading.Thread(target=load_last, name="session-restore", daemon=True).start()

    def _finish_session_restore(self, last_track: AudioTrack | None, pending_selection) -> bool:
        if pending_selection is not None:
            # Si last_artist o last_album no estaban guardados, se deducen de la última pista
            last_artist, last_album = pending_selection
            if last_track:
                if (not last_artist or last_artist == "__ALL__") and last_track.artist:
                    last_artist = last_track.artist
                if (not last_album or last_album == "__ALL__") and last_track.album:
                    last_album = last_track.album
            self.browser.load_initial_data(initial_artist=last_artist, initial_album=last_album)

        if last_track is None or self.engine.current_track is not None:
            # Sin pista previa, o el usuario ya eligió otra mientras se cargaba
            if self.engine.current_track is None:
                self._show_first_track()
            return False
        try:
            log.info("Restaurando pista de sesión anterior: '%s'", last_track.title)
            self.inspector.set_track(last_track)
            self.player_bar.set_track(last_track)
            last_pos = float(self.cfg.get("last_position", 0.0))
            self.engine.load_track(last_track, play_now=False, initial_position=last_pos)
            self.browser.set_current_playing_track(last_track, is_paused=True)
            self.player_bar._on_position_updated(last_pos, last_track.duration)
            self.library_backdrop.set_artist(last_track.artist)
        except Exception as e:
            log.warning("No se pudo restaurar la reproducción de sesión previa: %s", e)
        return False

    def _show_first_track(self):
        first_track = self.browser.get_selected_or_first_track()
        if first_track and not self.inspector.current_track:
            def show():
                if not self.inspector.current_track and self.engine.current_track is None:
                    self.inspector.set_track(first_track)
                    self.player_bar.set_track(first_track)
            first_track.load_cover_async(show)

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
        menu.append(i18n.t("menu.shortcuts"), "app.shortcuts")
        menu.append(i18n.t("menu.website"), "app.website")
        menu.append(i18n.t("menu.donate"), "app.donate")
        menu.append(i18n.t("menu.about"), "app.about")
        self.menu_btn.set_menu_model(menu)

    def _on_language_changed(self, _lang: str):
        """Actualiza tooltips, búsqueda y menú al cambiar el idioma en caliente."""
        self.btn_scan.set_tooltip_text(i18n.t("header.scan_library"))
        self.btn_search.set_tooltip_text(i18n.t("header.search_tooltip"))
        self._update_theme_button_ui()
        self.btn_mini_player.set_tooltip_text(i18n.t("header.mini_player"))
        self.btn_fullscreen.set_tooltip_text(i18n.t("header.super_player"))
        self.search_entry.set_placeholder_text(i18n.t("header.search_placeholder"))
        self._rebuild_menu()
        self._update_output_status()
        self.browser.refresh_i18n()

    def _toggle_theme(self):
        """Alterna entre tema claro y oscuro al pulsar el botón de la cabecera."""
        style_manager = Adw.StyleManager.get_default()
        is_dark = style_manager.get_dark() if style_manager else True
        new_theme = "light" if is_dark else "dark"
        self.cfg["theme"] = new_theme
        save_config(self.cfg)
        apply_theme(new_theme)
        self._update_theme_button_ui()

    def _update_theme_button_ui(self):
        """Actualiza el icono y tooltip del botón de tema según el modo activo."""
        if not hasattr(self, "btn_theme"):
            return
        style_manager = Adw.StyleManager.get_default()
        is_dark = style_manager.get_dark() if style_manager else True
        if is_dark:
            self.btn_theme.set_icon_name("weather-clear-symbolic")
            self.btn_theme.set_tooltip_text(i18n.t("header.theme_to_light"))
        else:
            self.btn_theme.set_icon_name("weather-clear-night-symbolic")
            self.btn_theme.set_tooltip_text(i18n.t("header.theme_to_dark"))

    def _setup_actions_and_shortcuts(self):
        action_dev = Gio.SimpleAction.new("select_device", None)
        action_dev.connect("activate", lambda *_: self._open_device_dialog())
        self.add_action(action_dev)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_F11:
            log.debug("Atajo teclado: F11 -> super player a pantalla completa")
            self._open_super_player()
            return True
        if keyval == Gdk.KEY_Escape and self.cover_popup.is_open:
            self.cover_popup.close()
            return True
        if handle_playback_key(self, self, keyval, state):
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

    # -------------------------------------------------------------------------
    # Acciones de los atajos de teclado (ver ui/shortcuts.py)
    # -------------------------------------------------------------------------
    def shortcut_handlers(self) -> dict:
        return {
            "view-main": self.show_main_view,
            "view-mini": self.show_mini_view,
            "view-super": self.show_super_view,
            "toggle-cover-mode": self.inspector.cycle_visualizer_mode,
            "show-cover": self._shortcut_show_cover,
            "shuffle": lambda: self.player_bar.shuffle_btn.set_active(not self.player_bar.shuffle_btn.get_active()),
            "repeat": self._cycle_repeat_mode,
            "mute": self.toggle_mute,
            "exclusive": lambda: self._on_exclusive_toggled(not self.engine.exclusive),
            "shortcuts": self.show_shortcuts,
        }

    def show_main_view(self):
        if self.mini_player and self.mini_player.get_visible():
            self.mini_player.restore_main_window()
        else:
            self.present()

    def show_mini_view(self):
        if self.mini_player and self.mini_player.get_visible():
            self.mini_player.present_mini_player()
        else:
            self._open_mini_player()

    def show_super_view(self):
        if self.mini_player and self.mini_player.get_visible():
            self.mini_player.present_super_player()
        else:
            self._open_super_player()

    def _shortcut_show_cover(self):
        # La portada a gran tamaño se superpone a la ventana principal
        if self.get_visible():
            self._toggle_cover_popup()

    def show_shortcuts(self):
        parent = self.mini_player if self.mini_player and self.mini_player.get_visible() else self
        build_shortcuts_dialog().present(parent)

    def seek_relative(self, delta: float):
        if self.engine.current_track:
            duration = self.engine.get_duration()
            target = max(0.0, self.engine.position + delta)
            self.engine.seek(min(target, duration - 0.5) if duration > 0 else target)

    def set_volume(self, value: float):
        """Ajusta el volumen desde un atajo, sincronizando los controles de todas las vistas."""
        if not self.engine.volume_adjustable:
            return  # Exclusivo en un DAC sin volumen por hardware: fijo a 0 dB
        value = max(0.0, min(1.0, value))
        self.player_bar.vol_scale.set_value(value)
        if self.mini_player:
            self.mini_player.super_vol_scale.set_value(value)

    def change_volume(self, delta: float):
        self.set_volume(self.engine.volume + delta)

    def toggle_mute(self):
        if self.engine.volume > 0.0:
            self._volume_before_mute = self.engine.volume
            self.set_volume(0.0)
        else:
            self.set_volume(getattr(self, "_volume_before_mute", 0.8) or 0.8)

    def _toggle_fullscreen(self):
        """Alterna el modo de pantalla completa de la ventana principal."""
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_fullscreen_changed(self, *_):
        """Actualiza icono y tooltip del botón de pantalla completa."""
        if self.is_fullscreen():
            self.btn_fullscreen.set_icon_name("view-restore-symbolic")
            self.btn_fullscreen.set_tooltip_text(i18n.t("header.unfullscreen"))
        else:
            self.btn_fullscreen.set_icon_name("view-fullscreen-symbolic")
            self.btn_fullscreen.set_tooltip_text(i18n.t("header.fullscreen"))

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
        if not track.cover_loaded:
            # La portada se lee en otro hilo: en una unidad de red puede tardar segundos y la
            # ventana no debe congelarse. Si mientras tanto se elige otra pista, esta se descarta.
            self._pending_activation = track
            self.browser.set_current_playing_track(track, is_paused=False)
            track.load_cover_async(lambda: self._pending_activation is track and self._on_track_activated(track))
            return
        self._pending_activation = None
        self.browser.set_current_playing_track(track, is_paused=False)
        self.inspector.set_track(track)
        self.player_bar.set_track(track)
        if self.mini_player:
            self.mini_player.set_track(track)
        self.engine.load_track(track, play_now=True)
        self._prepare_gapless_next()
        self._update_output_status()

    def _on_engine_track_changed(self, track: AudioTrack):
        """Notificado cuando cambia la pista en reproducción (incluyendo encadenamiento gapless)."""
        if not track.cover_loaded:
            # Normalmente ya está precargada; si no, la interfaz se refresca cuando llegue
            track.load_cover_async(lambda: self.engine.current_track is track and self.engine.renotify_track_changed())
        is_paused = (self.engine.state == PlaybackState.PAUSED)
        self.browser.set_current_playing_track(track, is_paused=is_paused)
        self.inspector.set_track(track)
        self.player_bar.set_track(track)
        self.library_backdrop.set_artist(track.artist)
        # Precargar la portada en alta resolución para que el zoom de portada sea inmediato
        HiResCoverService.get_default().prefetch(track)
        # Las fichas (Wikipedia y Discogs) se precargan si la pista sigue sonando unos segundos:
        # así no se gastan peticiones al saltar de canción en canción
        GLib.timeout_add_seconds(INFO_PREFETCH_DELAY, self._prefetch_info, track)
        if self.mini_player:
            self.mini_player.set_track(track)
        self._prepare_gapless_next()
        self._update_output_status()
        self.cfg["last_track_path"] = track.filepath
        if hasattr(self, "browser") and self.browser:
            self.cfg["last_artist"] = self.browser.current_artist
            self.cfg["last_album"] = self.browser.current_album
        save_config(self.cfg)

    def _prefetch_info(self, track: AudioTrack) -> bool:
        if self.engine.current_track is track:
            MusicInfoService.get_default().prefetch(track, i18n.get_language())
        return False

    def _on_play_next_queue(self, track: AudioTrack):
        """Inserta la pista al principio de la cola para ser la siguiente en reproducir."""
        log.info("Pista insertada como siguiente en la cola: '%s'", track.title)
        self.play_queue.insert(0, track)
        self.player_bar.update_queue(self.play_queue)
        self._prepare_gapless_next()

    def _on_add_to_queue(self, track: AudioTrack):
        """Añade la pista al final de la cola de reproducción."""
        log.info("Pista añadida a la cola: '%s'", track.title)
        self.play_queue.append(track)
        self.player_bar.update_queue(self.play_queue)
        self._prepare_gapless_next()

    def _on_remove_from_queue(self, index: int):
        """Elimina una pista específica de la cola."""
        if 0 <= index < len(self.play_queue):
            removed = self.play_queue.pop(index)
            log.info("Pista eliminada de la cola: '%s'", removed.title)
            self.player_bar.update_queue(self.play_queue)
            self._prepare_gapless_next()

    def _on_clear_queue(self):
        """Vacía toda la cola de reproducción."""
        log.info("Vaciando cola de reproducción (%d pistas)", len(self.play_queue))
        self.play_queue.clear()
        self.player_bar.update_queue(self.play_queue)
        self._prepare_gapless_next()

    def _prepare_gapless_next(self):
        if self.play_queue:
            nxt = self.play_queue[0]
        else:
            shuffle = self.cfg.get("shuffle", False)
            repeat = self.cfg.get("repeat_mode", "none")
            nxt = self.browser.get_next_track(shuffle=shuffle, repeat_mode=repeat)
        if nxt is not None:
            nxt.load_cover_async()  # Lista antes del cambio gapless, sin leer la red en el hilo principal
        self.engine.queue_next_track(nxt)

    def _play_next(self):
        if self.play_queue:
            nxt = self.play_queue.pop(0)
            self.player_bar.update_queue(self.play_queue)
            log.info("Reproduciendo siguiente pista de la cola: '%s'", nxt.title)
            self._on_track_activated(nxt)
            return

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
        toast = Adw.Toast.new(err_msg)
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)

    def _on_engine_state_changed(self, state: PlaybackState):
        self._update_output_status()
        is_playing = (state == PlaybackState.PLAYING)
        is_paused = (state == PlaybackState.PAUSED)
        self.browser.update_playback_state(
            is_playing=is_playing or is_paused,
            is_paused=is_paused,
        )

        # Inhibidor de suspensión del sistema mientras reproduce
        app = self.get_application()
        if app:
            if is_playing and self._inhibit_cookie == 0:
                try:
                    self._inhibit_cookie = app.inhibit(
                        self,
                        Gtk.ApplicationInhibitFlags.SUSPEND | Gtk.ApplicationInhibitFlags.IDLE,
                        "Reproduciendo audio Hi-Fi en MyFlac",
                    )
                    log.info("Inhibidor de suspensión activado (cookie=%d)", self._inhibit_cookie)
                except Exception as e:
                    log.warning("No se pudo activar inhibidor de suspensión: %s", e)
            elif not is_playing and self._inhibit_cookie != 0:
                try:
                    app.uninhibit(self._inhibit_cookie)
                    log.info("Inhibidor de suspensión liberado (cookie=%d)", self._inhibit_cookie)
                except Exception as e:
                    log.warning("Error liberando inhibidor de suspensión: %s", e)
                self._inhibit_cookie = 0

    def _update_output_status(self):
        dev = self.engine.hw_device or find_device_by_id(self.engine.device_id) \
            or get_default_device(self.engine.device_id)
        info = {
            "device_name": dev.name,
            "is_playing": self.engine.state == PlaybackState.PLAYING,
            "is_paused": self.engine.state == PlaybackState.PAUSED,
        }
        self.inspector.update_dac_status(info)
        self.player_bar.update_active_device()

    def set_repeat_mode(self, mode: str):
        """Establece el modo de repetición y actualiza la UI y MPRIS."""
        self.cfg["repeat_mode"] = mode
        save_config(self.cfg)
        icons = {
            "none": "media-playlist-repeat-symbolic",
            "all": "media-playlist-repeat-symbolic",
            "one": "media-playlist-repeat-song-symbolic",
        }
        self.player_bar.repeat_btn.set_icon_name(icons.get(mode, "media-playlist-repeat-symbolic"))
        if mode != "none":
            self.player_bar.repeat_btn.add_css_class("accent")
        else:
            self.player_bar.repeat_btn.remove_css_class("accent")
        if hasattr(self, "mpris"):
            mpris_val = "Track" if mode == "one" else ("Playlist" if mode == "all" else "None")
            self.mpris.notify_property_changed({"LoopStatus": GLib.Variant("s", mpris_val)})

    def set_shuffle(self, active: bool):
        """Establece el modo aleatorio y actualiza la UI y MPRIS."""
        self.cfg["shuffle"] = active
        save_config(self.cfg)
        if active:
            self.player_bar.shuffle_btn.add_css_class("accent")
        else:
            self.player_bar.shuffle_btn.remove_css_class("accent")
        self._prepare_gapless_next()
        if hasattr(self, "mpris"):
            self.mpris.notify_property_changed({"Shuffle": GLib.Variant("b", active)})

    def _cycle_repeat_mode(self):
        curr = self.cfg.get("repeat_mode", "none")
        modes = ["none", "all", "one"]
        nxt_mode = modes[(modes.index(curr) + 1) % len(modes)]
        log.info("Ciclo de modo repetición: %s -> %s", curr, nxt_mode)
        self.set_repeat_mode(nxt_mode)

    def _on_shuffle_toggled(self, active: bool):
        log.info("Modo aleatorio (shuffle) cambiado a: %s", active)
        self.set_shuffle(active)

    def _open_device_dialog(self):
        log.info("Abriendo diálogo de selección de dispositivo de salida")
        dlg = DeviceSelectionDialog(
            current_device_id=self.engine.device_id,
            on_device_selected=self._on_device_selected,
            parent=self,
        )
        dlg.present()

    def _on_device_selected(self, dev: AudioDevice | str):
        dev_id = dev if isinstance(dev, str) else dev.id
        log.info("Usuario seleccionó dispositivo: [%s]", dev_id)
        is_ex = dev_id != "default" and is_device_exclusive_enabled(self.cfg, dev)
        self.cfg["audio_device_id"] = dev_id
        self.cfg["exclusive_mode"] = is_ex
        save_config(self.cfg)
        # Un único cambio de salida: dispositivo y modo exclusivo a la vez
        self.engine.set_output(dev_id, is_ex)
        self._update_output_status()

    def _on_device_exclusive_toggled(self, dev: AudioDevice, enabled: bool):
        log.info("Usuario cambió bit-perfect en dispositivo '%s' a: %s", dev.name, enabled)
        set_device_exclusive_enabled(self.cfg, dev, enabled)
        curr_id = self.engine.device_id
        is_current = curr_id != "default" and base_node_name(dev.id) == base_node_name(curr_id)
        if is_current:
            self.cfg["exclusive_mode"] = enabled
            save_config(self.cfg)
            self.engine.set_exclusive(enabled)
            self._update_output_status()
        elif enabled:
            # Activar bit-perfect en un DAC no seleccionado lo selecciona
            self._on_device_selected(dev)
        else:
            save_config(self.cfg)

    def apply_backdrop_settings(self):
        """Aplica al instante los ajustes del fondo del artista desde Preferencias."""
        self.library_backdrop.set_enabled(self.cfg.get("backdrop_enabled", False))
        self.library_backdrop.set_intensity(self.cfg.get("backdrop_intensity", DEFAULT_INTENSITY))

    def _on_exclusive_toggled(self, enabled: bool):
        log.info("Usuario cambió el modo exclusivo a: %s", enabled)
        if self.engine.device_id == "default" and enabled:
            log.warning("No se puede activar bit-perfect en salida por defecto")
            return
        set_device_exclusive_enabled(self.cfg, self.engine.device_id, enabled)
        self.cfg["exclusive_mode"] = enabled
        save_config(self.cfg)
        self.engine.set_exclusive(enabled)
        self._update_output_status()

    def _on_album_activate_from_inspector(self, album_name: str):
        """Disparado por doble clic en la etiqueta de álbum del inspector."""
        log.info("Activando álbum completo desde Inspector: '%s'", album_name)
        self.browser.select_album_and_play(album_name)

    def _on_visualizer_mode_changed(self, mode: int):
        """Sincroniza el cambio de modo de osciloscopio del inspector con el mini-reproductor y configuración."""
        self.cfg["visualizer_mode"] = mode
        if hasattr(self, "player_bar") and self.player_bar:
            is_scope = (mode == 0) and self.cfg.get("oscilloscope_enabled", True)
            self.player_bar.set_bar_oscilloscope_enabled(is_scope)
        if self.mini_player:
            self.mini_player.set_visualizer_mode(mode, save=False)

    def _toggle_cover_popup(self):
        if self.cover_popup.is_open:
            self.cover_popup.close()
        elif not self.cover_popup.open_for_track(self.engine.current_track):
            log.info("La pista actual no tiene portada que mostrar a gran tamaño")

    def _open_mini_player(self):
        """Activa el modo Mini-Reproductor (500x500) y oculta la ventana principal."""
        log.info("Activando modo Mini-Reproductor y ocultando ventana principal")
        if self.mini_player is None:
            self.mini_player = MiniPlayerWindow(main_window=self, engine=self.engine)
        self.mini_player.set_visualizer_mode(self.inspector.visualizer_mode, save=False)
        if self.engine.current_track:
            self.mini_player.set_track(self.engine.current_track)
        self.mini_player.present_mini_player()
        self.set_visible(False)

    def _open_super_player(self):
        """Activa el modo Super-Reproductor a pantalla completa y oculta la ventana principal."""
        log.info("Activando Super-Reproductor a pantalla completa y ocultando ventana principal")
        if self.mini_player is None:
            self.mini_player = MiniPlayerWindow(main_window=self, engine=self.engine)
        self.mini_player.set_visualizer_mode(self.inspector.visualizer_mode, save=False)
        if self.engine.current_track:
            self.mini_player.set_track(self.engine.current_track)
        self.mini_player.present_super_player()
        self.set_visible(False)

    def _on_close_request(self, _window) -> bool:
        # Guardar siempre el estado actual completo de la sesión
        if hasattr(self, "browser") and self.browser:
            self.cfg["last_artist"] = self.browser.current_artist
            self.cfg["last_album"] = self.browser.current_album
        if self.engine.current_track:
            self.cfg["last_track_path"] = self.engine.current_track.filepath
            self.cfg["last_position"] = self.engine.position
        if hasattr(self, "inspector") and self.inspector:
            self.cfg["visualizer_mode"] = self.inspector.visualizer_mode
        w, h = self.get_default_size()
        self.cfg["window_width"] = w
        self.cfg["window_height"] = h
        self.cfg["window_maximized"] = self.is_maximized()
        if self._split_moved_by_user and hasattr(self, "browser") and self.browser:
            self.cfg["browser_split_position"] = self.browser.v_paned.get_position()
        self.cfg["software_volume"] = self.engine.software_volume
        save_config(self.cfg)

        app = self.get_application()
        can_bg = getattr(app, "can_run_in_background", lambda: False)()
        if app and not getattr(app, "quitting", False) and can_bg:
            # Como Spotify: cerrar la ventana la oculta y la música sigue; se sale con "Salir"
            log.info("Ventana principal oculta; MyFlac sigue en la barra superior")
            if self.mini_player and self.mini_player.get_visible():
                self.mini_player.set_visible(False)
            self.set_visible(False)
            return True
        log.info("Cerrando aplicación...")
        # El icono de la barra superior y su ventanita no deben mantener viva la aplicación
        tray = getattr(self.get_application(), "tray", None)
        if tray is not None:
            tray.shutdown()
        if self.mini_player:
            try:
                self.mini_player.destroy_window()
            except Exception:
                pass
            self.mini_player = None
        self.scanner.stop()
        if self._inhibit_cookie != 0:
            app = self.get_application()
            if app:
                try:
                    app.uninhibit(self._inhibit_cookie)
                except Exception:
                    pass
            self._inhibit_cookie = 0
        if hasattr(self, "mpris"):
            self.mpris.stop()
        self.engine.shutdown()
        log.info("Configuración final guardada. Adiós.")
        return False
