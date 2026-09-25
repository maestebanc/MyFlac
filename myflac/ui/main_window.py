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
from .about_dialog import build_about_dialog
from .device_popover import DeviceSelectionDialog
from .inspector_panel import InspectorPanel
from .player_bar import PlayerBar
from .preferences_dialog import PreferencesDialog
from .track_list import TrackListView


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, cfg: dict):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(cfg.get("window_width", 1280), cfg.get("window_height", 820))
        if cfg.get("window_maximized", False):
            self.maximize()

        self.cfg = cfg

        # 1. Inicializar motor de audio
        dev_id = cfg.get("audio_device_id", "auto")
        bp_mode = cfg.get("bitperfect_mode", True)
        vol_bp = cfg.get("volume_bypass", True)
        self.engine = AudioEngine(device_id=dev_id, bitperfect=bp_mode, volume_bypass=vol_bp)
        self.engine.volume = cfg.get("software_volume", 1.0)

        # 2. Configurar vistas de UI
        self._build_ui()
        self._setup_actions_and_shortcuts()

        # 3. Cablear eventos de reproducción automática de listas
        self.engine.on_track_finished = self._on_track_finished
        self.engine.on_error = self._on_playback_error
        self.engine.on_bitperfect_status = self._on_bitperfect_audit

        # Guardar dimensiones al cerrar
        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        self.toolbar_view = Adw.ToolbarView()

        # HeaderBar
        self.header_bar = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(self.header_bar)

        # Botones de apertura a la izquierda
        open_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        btn_open_folder = Gtk.Button()
        btn_open_folder.set_icon_name("folder-open-symbolic")
        btn_open_folder.set_tooltip_text("Abrir álbum o carpeta de música (Ctrl+O)")
        btn_open_folder.connect("clicked", lambda *_: self._choose_folder())
        open_box.append(btn_open_folder)

        btn_open_files = Gtk.Button()
        btn_open_files.set_icon_name("document-open-symbolic")
        btn_open_files.set_tooltip_text("Añadir pistas individuales (Ctrl+Shift+O)")
        btn_open_files.connect("clicked", lambda *_: self._choose_files())
        open_box.append(btn_open_files)

        btn_clear = Gtk.Button()
        btn_clear.set_icon_name("edit-clear-all-symbolic")
        btn_clear.set_tooltip_text("Vaciar lista de reproducción")
        btn_clear.connect("clicked", lambda *_: self._clear_playlist())
        open_box.append(btn_clear)

        self.header_bar.pack_start(open_box)

        # Búsqueda en el centro
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Buscar en la lista...")
        self.search_entry.set_size_request(240, -1)
        self.search_entry.connect("search-changed", lambda entry: self.track_list.set_search_query(entry.get_text()))
        self.header_bar.set_title_widget(self.search_entry)

        # Menú principal y acceso rápido a dispositivos a la derecha
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Preferencias", "app.preferences")
        menu.append("Dispositivos de Audio", "win.select_device")
        menu.append("Acerca de MyFlac", "app.about")
        menu_btn.set_menu_model(menu)
        self.header_bar.pack_end(menu_btn)

        # Panel central dividido (Paned: Lista de pistas | Inspector audiófilo)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)

        # Vista de canciones
        self.track_list = TrackListView(on_track_activate=self._on_track_activated)
        self.paned.set_start_child(self.track_list)

        # Panel Inspector de audio
        self.inspector = InspectorPanel()
        self.paned.set_end_child(self.inspector)
        self.paned.set_position(840)

        # Barra inferior del reproductor
        self.player_bar = PlayerBar(
            engine=self.engine,
            on_device_click=lambda: self._open_device_dialog()
        )
        self.player_bar.on_previous_clicked = self._play_previous
        self.player_bar.on_next_clicked = self._play_next
        self.player_bar.on_repeat_clicked = self._cycle_repeat_mode
        self.player_bar.on_shuffle_toggled = self._on_shuffle_toggled

        self.toolbar_view.set_content(self.paned)
        self.toolbar_view.add_bottom_bar(self.player_bar)
        self.set_content(self.toolbar_view)

    def _setup_actions_and_shortcuts(self):
        # Acción seleccionar dispositivo
        action_dev = Gio.SimpleAction.new("select_device", None)
        action_dev.connect("activate", lambda *_: self._open_device_dialog())
        self.add_action(action_dev)

        # Controlador de teclas para atajos globales
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        # Espacio para play/pause si el foco no es un campo de texto
        if keyval == Gdk.KEY_space:
            focus = self.get_focus()
            if not isinstance(focus, (Gtk.Entry, Gtk.SearchEntry, Gtk.Editable)):
                self.engine.toggle_play_pause()
                return True
        # Ctrl+O abrir álbum
        if keyval in (Gdk.KEY_o, Gdk.KEY_O) and (state & Gdk.ModifierType.CONTROL_MASK):
            if state & Gdk.ModifierType.SHIFT_MASK:
                self._choose_files()
            else:
                self._choose_folder()
            return True
        return False

    def _on_track_activated(self, track: AudioTrack):
        self.inspector.set_track(track)
        self.engine.load_track(track, play_now=True)
        # Pre-cargar la siguiente para reproducción continua gapless
        self._prepare_gapless_next()

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
            self.track_list.set_current_playing_track(nxt)
            self._on_track_activated(nxt)

    def _play_previous(self):
        prev = self.track_list.get_previous_track()
        if prev:
            self.track_list.set_current_playing_track(prev)
            self._on_track_activated(prev)

    def _on_track_finished(self):
        GLib.idle_add(self._play_next)

    def _on_playback_error(self, err_msg: str):
        toast = Adw.Toast.new(f"Aviso de audio: {err_msg}")
        toast.set_timeout(4)
        toast_overlay = getattr(self, "toast_overlay", None)
        if not toast_overlay:
            # Crear toast overlay si aún no existe
            pass

    def _on_bitperfect_audit(self, info: dict):
        self.player_bar._on_bitperfect_status(info)
        self.inspector.update_dac_status(info)

    def _cycle_repeat_mode(self):
        curr = self.cfg.get("repeat_mode", "none")
        modes = ["none", "all", "one"]
        nxt_mode = modes[(modes.index(curr) + 1) % len(modes)]
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
        self.cfg["shuffle"] = active
        save_config(self.cfg)
        self._prepare_gapless_next()

    def _clear_playlist(self):
        self.engine.stop()
        self.track_list.add_tracks([], clear=True)
        self.inspector.set_track(None)

    def _choose_folder(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Seleccionar carpeta de música / álbum")
        last_dir = self.cfg.get("last_directory")
        if last_dir and os.path.isdir(last_dir):
            dialog.set_initial_folder(Gio.File.new_for_path(last_dir))

        def on_folder_selected(dlg: Gtk.FileDialog, res):
            try:
                gfile = dlg.select_folder_finish(res)
                if gfile:
                    folder_path = gfile.get_path()
                    self.cfg["last_directory"] = folder_path
                    save_config(self.cfg)
                    self._load_directory(folder_path)
            except Exception:
                pass

        dialog.select_folder(self, None, on_folder_selected)

    def _choose_files(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Seleccionar pistas de audio")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f_audio = Gtk.FileFilter()
        f_audio.set_name("Archivos de audio Hi-Res y FLAC")
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
                    loaded.sort(key=lambda x: ((x.disc_number or 1) * 100000 + (x.track_number or 99999), x.filename))
                    self.track_list.add_tracks(loaded, clear=False)
            except Exception:
                pass

        dialog.open_multiple(self, None, on_files_selected)

    def _load_directory(self, folder_path: str):
        loaded = []
        for root, _, files in os.walk(folder_path):
            for file in sorted(files):
                if file.lower().endswith(SUPPORTED_EXTENSIONS):
                    full_p = os.path.join(root, file)
                    t = load_track(full_p)
                    if t:
                        loaded.append(t)

        if loaded:
            loaded.sort(key=lambda x: ((x.disc_number or 1) * 100000 + (x.track_number or 99999), x.filename))
            self.track_list.add_tracks(loaded, clear=True)
            # Seleccionar la primera
            first_track = loaded[0]
            self.inspector.set_track(first_track)

    def _open_device_dialog(self):
        dlg = DeviceSelectionDialog(
            current_device_id=self.engine.device_id,
            on_device_selected=self._on_device_selected,
            parent=self
        )
        dlg.present()

    def _on_device_selected(self, dev: AudioDevice):
        self.cfg["audio_device_id"] = dev.id
        save_config(self.cfg)
        self.engine.set_device(dev.id)

    def _on_close_request(self, _window) -> bool:
        self.engine.stop()
        w, h = self.get_default_size()
        self.cfg["window_width"] = w
        self.cfg["window_height"] = h
        self.cfg["window_maximized"] = self.is_maximized()
        save_config(self.cfg)
        return False
