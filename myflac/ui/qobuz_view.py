"""Vista de exploración y reproducción de streaming Hi-Res de Qobuz con filtrado por género."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.track import AudioTrack
from ..logger import get_logger
from .wave_indicator import PlayingWaveIndicator
from ..streaming.qobuz_client import QobuzAlbum, QobuzArtist, QobuzGenre, QobuzTrack, get_qobuz_client
from .. import i18n

log = get_logger("ui.qobuz_view")

COVER_CACHE_DIR = Path.home() / ".cache" / "myflac" / "qobuz_covers"
BOOKLET_CACHE_DIR = Path.home() / ".cache" / "myflac" / "booklets"
FALLBACK_ART_PATH = Path(__file__).resolve().parent.parent / "resources" / "placeholder-aesthetic.png"


def _simplify(text: str) -> str:
    """Minúsculas sin acentos ni espacios sobrantes, para reconocer nombres de extras."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


# Nombres habituales de los extras de Qobuz (francés e inglés) → texto traducido
BOOKLET_KINDS = {
    "livret numerique": "qobuz.booklet.default_name",
    "livret": "qobuz.booklet.default_name",
    "livret pdf": "qobuz.booklet.default_name",
    "digital booklet": "qobuz.booklet.default_name",
    "booklet": "qobuz.booklet.default_name",
    "pdf booklet": "qobuz.booklet.default_name",
    "partition": "qobuz.booklet.score",
    "partitions": "qobuz.booklet.score",
    "score": "qobuz.booklet.score",
    "paroles": "qobuz.booklet.lyrics",
    "lyrics": "qobuz.booklet.lyrics",
}


class FixedPicture(Gtk.Picture):
    """
    Imagen de tamaño exacto. Gtk.Picture pide como tamaño natural el de la imagen y, con
    ContentFit.COVER, crece con el espacio libre: la misma foto cambiaba de tamaño según la
    longitud de la lista de debajo. Esta siempre mide `size` × `size`.
    """

    def __init__(self, size: int):
        super().__init__()
        self._size = size
        self.set_can_shrink(True)
        self.set_content_fit(Gtk.ContentFit.COVER)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)

    def do_measure(self, orientation, for_size):
        return self._size, self._size, -1, -1


class QobuzView(Gtk.Box):
    """Vista de un servicio de streaming. TidalView reutiliza todo cambiando estos atributos."""

    SERVICE = "qobuz"
    BADGE = "QOBUZ"
    # Categorías de Explorar: (clave para el cliente, texto)
    CATEGORIES = (("recent", "qobuz.cat.recent"), ("most-streamed", "qobuz.cat.most_streamed"),
                  ("press-awards", "qobuz.cat.press_awards"),
                  ("ideal-discography", "qobuz.cat.ideal_discography"))

    # Sin peticiones hasta abrir la pestaña (y nunca si el servicio está desactivado)
    LAZY_LOAD = True

    def _make_client(self):
        return get_qobuz_client()

    def _initial_load(self):
        if self.client.is_logged_in:
            self._load_genres()
            self.refresh_catalog()
            self._load_favorite_ids()

    def _on_first_map(self, *_):
        self.disconnect(self._first_map_id)
        self._initial_load()

    def _t(self, key: str, **kwargs) -> str:
        """Texto del servicio: «tidal.x» si existe para «qobuz.x» (los que nombran al servicio)."""
        if self.SERVICE != "qobuz" and key.startswith("qobuz."):
            alt = self.SERVICE + key[len("qobuz"):]
            if alt in i18n.STRINGS:
                key = alt
        return i18n.t(key, **kwargs)

    """
    Vista principal de Qobuz integrada en MyFlac:
    - Filtro nativo por género (Rock, Jazz, Clásica, Pop, Electrónica, etc.)
    - Filtro por categoría (Novedades, Más escuchados, Premios de la crítica, Esenciales)
    - Exploración de álbumes y pistas en FLAC de alta resolución
    - Reproducción directa hacia el motor bit-perfect de GStreamer
    """

    def __init__(
        self,
        on_track_activate: Callable[[AudioTrack], None],
        on_queue_track: Callable[[AudioTrack], None] | None = None,
        on_play_list: Callable[[list[AudioTrack]], None] | None = None,
        on_play_next: Callable[[AudioTrack], None] | None = None,
        parent_window: Gtk.Window | None = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.on_track_activate = on_track_activate
        self.on_queue_track = on_queue_track
        self.on_play_list = on_play_list
        self.on_play_next = on_play_next
        # Tema en reproducción (para marcarlo como en la biblioteca local: color y onda)
        self._playing_id: int | None = None
        self._playing_active = False
        self._playing_paused = False
        self._list_marks: list[tuple] = []    # Temas de la lista de la izquierda (favoritos)
        self._detail_marks: list[tuple] = []  # Temas del álbum o lista abierto a la derecha
        self.parent_window = parent_window

        self.client = self._make_client()
        self.genres: list[QobuzGenre] = []
        self.current_genre_id: int = 0
        self.current_category: str = self.CATEGORIES[0][0]
        # Filtro de género sobre la lista cargada (biblioteca, o Explorar si el servicio no filtra)
        self._loaded_albums: list[QobuzAlbum] = []
        self._local_genre: str = ""
        self._genre_mode = "server"
        self._syncing_genres = False
        # Sección: "explore" (catálogo) o "library" (biblioteca del usuario: álbumes, temas, artistas, listas)
        self.section: str = "explore"
        self.library_kind: str = "albums"
        self.favorite_tracks: list[QobuzTrack] = []
        self._detail_token = 0  # Descarta cargas de detalle que llegan tarde
        self._artist_cache: dict[int, dict[str, list[QobuzAlbum]]] = {}  # Discografía ya cargada
        self.current_albums: list[QobuzAlbum] = []
        self.selected_album: QobuzAlbum | None = None

        COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._update_genre_visibility()
        self._update_auth_ui()
        if self.LAZY_LOAD:
            # Nada de peticiones hasta que se abre la pestaña (TIDAL limita mucho las peticiones)
            self._first_map_id = self.connect("map", self._on_first_map)
        else:
            self._initial_load()

        i18n.add_language_listener(self._on_language_changed)

    def _populate_categories(self):
        curr_selected = self.cat_dropdown.get_selected() if hasattr(self, "cat_dropdown") else 0
        items = [self._t(key) for _cat, key in self.CATEGORIES]
        self.cat_model.splice(0, self.cat_model.get_n_items(), items)
        if hasattr(self, "cat_dropdown") and 0 <= curr_selected < len(items):
            self.cat_dropdown.set_selected(curr_selected)

    def _populate_library_kinds(self):
        curr = self.lib_dropdown.get_selected() if hasattr(self, "lib_dropdown") else 0
        items = [self._t("qobuz.lib.albums"), self._t("qobuz.lib.tracks"),
                 self._t("qobuz.lib.artists"), self._t("qobuz.lib.playlists")]
        self.lib_model.splice(0, self.lib_model.get_n_items(), items)
        if hasattr(self, "lib_dropdown") and 0 <= curr < len(items):
            self.lib_dropdown.set_selected(curr)

    def _on_language_changed(self, _lang: str):
        self.genre_lbl.set_label(self._t("qobuz.genre_label"))
        self.cat_lbl.set_label(self._t("qobuz.show_label"))
        self.lib_lbl.set_label(self._t("qobuz.show_label"))
        self.btn_explore.set_label(self._t("qobuz.section.explore"))
        self.btn_library.set_label(self._t("qobuz.section.library"))
        self._populate_categories()
        self._populate_library_kinds()
        self.search_entry.set_placeholder_text(self._t("qobuz.search_placeholder"))
        self._update_auth_ui()
        if self.selected_album:
            self._render_album_detail(self.selected_album)

    def _build_ui(self):
        # =====================================================================
        # 1. BARRA SUPERIOR DE FILTROS Y CONTROL
        # =====================================================================
        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        filter_bar.set_margin_start(16)
        filter_bar.set_margin_end(16)
        filter_bar.set_margin_top(12)
        filter_bar.set_margin_bottom(12)
        filter_bar.add_css_class("qobuz-filter-bar")

        # Insignia de Qobuz
        logo_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        logo_box.set_valign(Gtk.Align.CENTER)
        badge = Gtk.Label(label=self.BADGE)
        badge.add_css_class("tag-badge")
        badge.add_css_class("tag-badge-flac")
        badge.set_tooltip_text(self._t("qobuz.badge_tooltip"))
        logo_box.append(badge)
        filter_bar.append(logo_box)

        # Sección: [ Explorar | Mi biblioteca ]
        section_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        section_box.add_css_class("linked")
        section_box.set_valign(Gtk.Align.CENTER)
        self.btn_explore = Gtk.ToggleButton(label=self._t("qobuz.section.explore"))
        self.btn_explore.set_active(True)
        self.btn_library = Gtk.ToggleButton(label=self._t("qobuz.section.library"))
        self.btn_library.set_group(self.btn_explore)
        self.btn_explore.connect("toggled", self._on_section_toggled)
        self.btn_library.connect("toggled", self._on_section_toggled)
        section_box.append(self.btn_explore)
        section_box.append(self.btn_library)
        filter_bar.append(section_box)

        # Separador visual
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        filter_bar.append(sep1)

        # Selector de Género
        self.genre_lbl = Gtk.Label(label=self._t("qobuz.genre_label"))
        self.genre_lbl.add_css_class("dim-label")
        filter_bar.append(self.genre_lbl)

        self.genre_model = Gtk.StringList()
        self.genre_dropdown = Gtk.DropDown(model=self.genre_model)
        self.genre_dropdown.set_size_request(180, -1)
        self.genre_dropdown.connect("notify::selected", self._on_genre_dropdown_changed)
        filter_bar.append(self.genre_dropdown)

        # Selector de Categoría (Píldoras)
        self.cat_lbl = Gtk.Label(label=self._t("qobuz.show_label"))
        self.cat_lbl.add_css_class("dim-label")
        self.cat_lbl.set_margin_start(8)
        filter_bar.append(self.cat_lbl)

        self.cat_model = Gtk.StringList()
        self._populate_categories()

        self.cat_dropdown = Gtk.DropDown(model=self.cat_model)
        self.cat_dropdown.connect("notify::selected", self._on_cat_dropdown_changed)
        filter_bar.append(self.cat_dropdown)

        # Biblioteca del usuario: qué mostrar (oculto en Explorar)
        self.lib_lbl = Gtk.Label(label=self._t("qobuz.show_label"))
        self.lib_lbl.add_css_class("dim-label")
        filter_bar.append(self.lib_lbl)
        self.lib_model = Gtk.StringList()
        self._populate_library_kinds()
        self.lib_dropdown = Gtk.DropDown(model=self.lib_model)
        self.lib_dropdown.connect("notify::selected", self._on_lib_dropdown_changed)
        filter_bar.append(self.lib_dropdown)
        self.lib_lbl.set_visible(False)
        self.lib_dropdown.set_visible(False)

        # Buscador en catálogo de Qobuz
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(self._t("qobuz.search_placeholder"))
        self.search_entry.set_size_request(220, -1)
        self.search_entry.connect("activate", self._on_search_activate)
        filter_bar.append(self.search_entry)

        # Espaciador elástico para empujar cuenta a la derecha
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        filter_bar.append(spacer)

        # Spinner de carga
        self.loading_spinner = Gtk.Spinner()
        self.loading_spinner.set_visible(False)
        filter_bar.append(self.loading_spinner)

        # Botón de Estado / Login de Cuenta
        self.btn_account = Gtk.Button()
        self.btn_account.connect("clicked", self._open_login_dialog)
        filter_bar.append(self.btn_account)

        self.append(filter_bar)

        # Línea separadora sutil
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # =====================================================================
        # 2. CONTENEDOR CONMUTABLE: Catálogo | Inicio de Sesión Obligatorio
        # =====================================================================
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_transition_duration(180)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)

        # --- Página 1: Catálogo de Álbumes | Detalle y Temas ---
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_hexpand(True)
        self.paned.set_vexpand(True)
        self.paned.set_resize_start_child(True)
        self.paned.set_resize_end_child(True)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)
        self.paned.set_position(520)

        # Panel izquierdo: Cuadrícula/Lista de Álbumes
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left_box.set_hexpand(True)
        left_box.set_vexpand(True)
        self.albums_scroll = Gtk.ScrolledWindow()
        self.albums_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.albums_scroll.set_hexpand(True)
        self.albums_scroll.set_vexpand(True)

        self.albums_listbox = Gtk.ListBox()
        self.albums_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        # Importante: activar solo con doble clic para que un solo clic únicamente seleccione
        self.albums_listbox.set_activate_on_single_click(False)
        self.albums_listbox.connect("row-selected", self._on_list_row_selected)
        self.albums_listbox.connect("row-activated", self._on_list_row_activated)
        self.albums_listbox.add_css_class("boxed-list")
        self.albums_listbox.set_margin_start(16)
        self.albums_listbox.set_margin_end(16)
        self.albums_listbox.set_margin_top(12)
        self.albums_listbox.set_margin_bottom(12)

        self.albums_scroll.set_child(self.albums_listbox)
        left_box.append(self.albums_scroll)
        self.paned.set_start_child(left_box)

        # Panel derecho: Detalle del Álbum y Lista de Pistas
        self.right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.right_box.set_hexpand(True)
        self.right_box.set_vexpand(True)

        # Contenedor de detalle
        self.detail_scroll = Gtk.ScrolledWindow()
        self.detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.detail_scroll.set_hexpand(True)
        self.detail_scroll.set_vexpand(True)
        self.detail_scroll.set_min_content_height(400)
        self.detail_scroll.set_propagate_natural_height(False)

        self.detail_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.detail_container.set_hexpand(True)
        self.detail_container.set_vexpand(False)
        self.detail_container.set_margin_start(16)
        self.detail_container.set_margin_end(16)
        self.detail_container.set_margin_top(16)
        self.detail_container.set_margin_bottom(16)

        self.detail_scroll.set_child(self.detail_container)
        self.right_box.append(self.detail_scroll)
        self.paned.set_end_child(self.right_box)

        self.content_stack.add_named(self.paned, "catalog")

        # --- Página 2: Inicio de Sesión Obligatorio ---
        status_page = Adw.StatusPage()
        status_page.set_icon_name("avatar-default-symbolic")
        status_page.set_title(self._t("qobuz.login_required_title"))
        status_page.set_description(self._t("qobuz.login_required_desc"))
        status_page.set_hexpand(True)
        status_page.set_vexpand(True)

        login_action_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        login_action_box.set_halign(Gtk.Align.CENTER)
        login_action_box.set_valign(Gtk.Align.CENTER)

        btn_web_connect = Gtk.Button(label=self._t("qobuz.connect_btn"))
        btn_web_connect.set_icon_name("network-wireless-symbolic")
        btn_web_connect.add_css_class("suggested-action")
        btn_web_connect.add_css_class("pill")
        btn_web_connect.connect("clicked", self._open_login_dialog)
        login_action_box.append(btn_web_connect)

        btn_manual_token = Gtk.Button(label=self._t("qobuz.manual_token_btn"))
        btn_manual_token.add_css_class("flat")
        btn_manual_token.connect("clicked", self._open_manual_token_dialog)
        login_action_box.append(btn_manual_token)

        status_page.set_child(login_action_box)
        self.content_stack.add_named(status_page, "login_required")

        self.append(self.content_stack)

    # -------------------------------------------------------------------------
    # Estado de autenticación y carga de datos
    # -------------------------------------------------------------------------

    def _update_auth_ui(self):
        """Actualiza la interfaz según el usuario haya iniciado sesión o no."""
        is_logged_in = self.client.is_logged_in
        if is_logged_in:
            self.content_stack.set_visible_child_name("catalog")
            self.genre_dropdown.set_sensitive(True)
            self.cat_dropdown.set_sensitive(True)
            self.btn_library.set_sensitive(True)
            self.search_entry.set_sensitive(True)
            name = self.client.user_display_name or self.client.user_email or self._t("qobuz.dialog.user_fallback")
            self.btn_account.set_label(self._t("qobuz.account.connected_btn", name=name))
            self.btn_account.set_tooltip_text(self._t("qobuz.account.connected_tooltip", plan=self.client.subscription_label or "Hi-Res"))
            self.btn_account.remove_css_class("suggested-action")
        else:
            self.content_stack.set_visible_child_name("login_required")
            self.genre_dropdown.set_sensitive(False)
            self.cat_dropdown.set_sensitive(False)
            self.btn_library.set_sensitive(False)
            self.search_entry.set_sensitive(False)
            self.btn_account.set_label(self._t("qobuz.account.login_btn"))
            self.btn_account.set_tooltip_text(self._t("qobuz.account.login_tooltip"))
            self.btn_account.add_css_class("suggested-action")
            self._clear_albums_list()
            self._render_album_detail(None)

    def _clear_albums_list(self):
        self._list_marks = []
        while True:
            child = self.albums_listbox.get_first_child()
            if not child:
                break
            self.albums_listbox.remove(child)

    def _load_genres(self):
        if self._genre_mode == "local":
            return
        if not self.client.is_logged_in:
            self.genres = []
            self.genre_model.splice(0, self.genre_model.get_n_items(), [])
            return

        def worker():
            genres = self.client.get_genres()

            def apply():
                if self._genre_mode == "local":
                    return False
                self.genres = genres
                self.current_genre_id = 0
                self._syncing_genres = True
                self.genre_model.splice(0, self.genre_model.get_n_items(), [g.name for g in genres])
                self.genre_dropdown.set_selected(0)
                self._syncing_genres = False
                return False

            GLib.idle_add(apply)

        threading.Thread(target=worker, daemon=True, name="qobuz-genres").start()

    def _local_genre_mode(self) -> bool:
        """Género filtrado aquí: en Mi biblioteca (álbumes) o si el servicio no filtra el catálogo."""
        if self.section == "library":
            return self.library_kind == "albums"
        return not getattr(self.client, "server_side_genres", True)

    def _update_genre_visibility(self):
        explore = self.section == "explore"
        show_genre = (explore and getattr(self.client, "server_side_genres", True)) or self._local_genre_mode()
        self.genre_lbl.set_visible(show_genre)
        self.genre_dropdown.set_visible(show_genre)
        self.cat_lbl.set_visible(explore)
        self.cat_dropdown.set_visible(explore)
        self.lib_lbl.set_visible(not explore)
        self.lib_dropdown.set_visible(not explore)
        wanted = "local" if self._local_genre_mode() else "server"
        if wanted != self._genre_mode:
            self._genre_mode = wanted
            self._local_genre = ""
            if wanted == "server":
                self._load_genres()  # Vuelven los géneros del catálogo

    def _populate_local_genres(self, albums: list[QobuzAlbum]):
        """Géneros presentes en la lista cargada (los álbumes pueden tener varios, separados por comas)."""
        names = sorted({g.strip() for a in albums for g in (a.genre_name or "").split(",") if g.strip()},
                       key=str.lower)
        self.genres = [QobuzGenre(id=0, name=self._t("qobuz.all_genres"), slug="all")] + \
                      [QobuzGenre(id=-(i + 1), name=n, slug=n) for i, n in enumerate(names)]
        self._syncing_genres = True
        self.genre_model.splice(0, self.genre_model.get_n_items(), [g.name for g in self.genres])
        selected = next((i for i, g in enumerate(self.genres) if g.name == self._local_genre), 0)
        if selected == 0:
            self._local_genre = ""
        self.genre_dropdown.set_selected(selected)
        self._syncing_genres = False

    def _filtered(self, albums: list[QobuzAlbum]) -> list[QobuzAlbum]:
        if not self._local_genre:
            return albums
        return [a for a in albums
                if self._local_genre in [g.strip() for g in (a.genre_name or "").split(",")]]

    def _on_genre_dropdown_changed(self, dropdown, _param):
        if self._syncing_genres:
            return
        idx = dropdown.get_selected()
        if self._genre_mode == "local":
            name = self.genres[idx].name if 0 < idx < len(self.genres) else ""
            if name != self._local_genre:
                self._local_genre = name
                self._render_album_list(self._filtered(self._loaded_albums))
            return
        if 0 <= idx < len(self.genres):
            genre = self.genres[idx]
            if genre.id != self.current_genre_id:
                self.current_genre_id = genre.id
                log.info("Filtro de género Qobuz cambiado a: %s (ID %s)", genre.name, genre.id)
                self.refresh_catalog()

    def _on_cat_dropdown_changed(self, dropdown, _param):
        idx = dropdown.get_selected()
        new_cat = self.CATEGORIES[idx][0] if 0 <= idx < len(self.CATEGORIES) else self.CATEGORIES[0][0]
        if new_cat != self.current_category:
            self.current_category = new_cat
            self.refresh_catalog()

    def _on_search_activate(self, entry):
        q = entry.get_text().strip()
        if q:
            self._start_search(q)
        else:
            self.refresh_catalog()

    def _start_search(self, query: str):
        if not self.client.is_logged_in:
            return
        self._set_loading(True)

        def worker():
            artists = self.client.search_artists(query)
            albums = self.client.search_catalog(query)
            GLib.idle_add(lambda: (self._on_search_loaded(artists, albums), False)[1])

        threading.Thread(target=worker, daemon=True, name="qobuz-search").start()

    def _section_header(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        lbl = Gtk.Label(label=text, xalign=0.0)
        lbl.add_css_class("heading")
        lbl.add_css_class("dim-label")
        lbl.set_margin_start(10)
        lbl.set_margin_top(8)
        lbl.set_margin_bottom(4)
        row.set_child(lbl)
        return row

    def _on_search_loaded(self, artists: list[QobuzArtist], albums: list[QobuzAlbum]):
        """Resultados de búsqueda: primero los artistas que coinciden, después los álbumes."""
        if not artists:
            self._on_albums_loaded(albums)
            return
        self._set_loading(False)
        self.current_albums = albums
        self._clear_albums_list()
        self.albums_listbox.append(self._section_header(self._t("qobuz.search.artists")))
        for artist in artists:
            self.albums_listbox.append(self._create_artist_row(artist))
        if albums:
            self.albums_listbox.append(self._section_header(self._t("qobuz.search.albums")))
            for album in albums:
                self.albums_listbox.append(self._create_album_row(album))
        self.albums_listbox.select_row(self.albums_listbox.get_row_at_index(1))

    def refresh_catalog(self):
        """Descarga o actualiza la lista de la izquierda según la sección, el género y la categoría."""
        if self.section == "library" and self.client.is_logged_in:
            self._load_library()
            return
        if not self.client.is_logged_in:
            self._set_loading(False)
            self._clear_albums_list()
            self._render_album_detail(None)
            return

        self._set_loading(True)
        genre_id = self.current_genre_id
        cat = self.current_category

        def worker():
            albums = self.client.get_featured_albums(category=cat, genre_id=genre_id, limit=30)
            GLib.idle_add(lambda: self._on_albums_loaded(albums))

        threading.Thread(target=worker, daemon=True).start()

    def _set_loading(self, active: bool):
        if active:
            self.loading_spinner.set_visible(True)
            self.loading_spinner.start()
        else:
            self.loading_spinner.stop()
            self.loading_spinner.set_visible(False)

    def _on_albums_loaded(self, albums: list[QobuzAlbum]):
        self._set_loading(False)
        self._loaded_albums = albums
        if self._genre_mode == "local":
            self._populate_local_genres(albums)
            albums = self._filtered(albums)
        self._render_album_list(albums)

    def _render_album_list(self, albums: list[QobuzAlbum]):
        self.current_albums = albums
        self._clear_albums_list()

        if not albums:
            self._show_empty()
            return

        for album in albums:
            row = self._create_album_row(album)
            self.albums_listbox.append(row)

        # Seleccionar automáticamente el primero para mostrar sus detalles (sin reproducir)
        first_row = self.albums_listbox.get_row_at_index(0)
        if first_row:
            self.albums_listbox.select_row(first_row)
            self._render_album_detail(albums[0])

    def _set_default_paintable(self, picture: Gtk.Picture):
        if FALLBACK_ART_PATH.is_file():
            try:
                texture = Gdk.Texture.new_from_filename(str(FALLBACK_ART_PATH))
                picture.set_paintable(texture)
            except Exception:
                pass

    def _create_album_row(self, album: QobuzAlbum) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._album_data = album
        self._add_context_menu(row, lambda: self._album_menu(album))

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Portada miniatura (56x56)
        picture = FixedPicture(56)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.add_css_class("card")
        self._set_default_paintable(picture)
        self._load_cover_async(album.cover_url, picture)
        box.append(picture)

        # Metadatos textuales
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label(label=album.title)
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.add_css_class("heading")
        text_box.append(title_lbl)

        artist_lbl = Gtk.Label(label=album.artist)
        artist_lbl.set_halign(Gtk.Align.START)
        artist_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        artist_lbl.add_css_class("dim-label")
        text_box.append(artist_lbl)

        if album.kind == "playlist":
            sub_info = self._t("qobuz.playlist_tracks", n=album.tracks_count)
        else:
            sub_info = f"{album.release_date} • {album.genre_name}" if album.genre_name else album.release_date
        date_lbl = Gtk.Label(label=sub_info)
        date_lbl.set_halign(Gtk.Align.START)
        date_lbl.add_css_class("caption")
        date_lbl.add_css_class("dim-label")
        text_box.append(date_lbl)

        box.append(text_box)

        # Insignia Hi-Res
        badge_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        badge_box.set_valign(Gtk.Align.CENTER)
        if album.kind == "album":
            badge = Gtk.Label(label=album.hires_badge)
            badge.add_css_class("tag-badge")
            if album.hires:
                badge.add_css_class("tag-badge-flac")
            badge_box.append(badge)
        box.append(badge_box)

        row.set_child(box)
        return row

    def _on_list_row_selected(self, _listbox, row: Gtk.ListBoxRow | None):
        """Un solo clic únicamente muestra los detalles en el panel derecho."""
        if row is None:
            return
        if hasattr(row, "_album_data"):
            self.selected_album = row._album_data
            self._render_album_detail(row._album_data)
        elif hasattr(row, "_artist_data"):
            self._render_artist_detail(row._artist_data)
        elif hasattr(row, "_fav_track"):
            self._show_track_album(row._fav_track)

    def _on_list_row_activated(self, _listbox, row: Gtk.ListBoxRow | None):
        """El doble clic reproduce: el álbum o la lista entera, o los temas favoritos desde ese."""
        if row is None:
            return
        if hasattr(row, "_album_data"):
            album = row._album_data
            self.selected_album = album
            self._render_album_detail(album)
            self._play_entire_album(album)
        elif hasattr(row, "_fav_track"):
            self._play_tracks(self.favorite_tracks, row._fav_track)

    # -------------------------------------------------------------------------
    # Mi biblioteca: álbumes, temas y artistas favoritos, y listas
    # -------------------------------------------------------------------------

    def _on_section_toggled(self, btn: Gtk.ToggleButton):
        if not btn.get_active():
            return
        self.section = "library" if btn is self.btn_library else "explore"
        self._update_genre_visibility()
        self.refresh_catalog()

    def _on_lib_dropdown_changed(self, dropdown, _param):
        kind = {0: "albums", 1: "tracks", 2: "artists", 3: "playlists"}.get(dropdown.get_selected(), "albums")
        if kind != self.library_kind:
            self.library_kind = kind
            if self.section == "library":
                self._update_genre_visibility()
                self.refresh_catalog()

    def _load_library(self):
        self._set_loading(True)
        kind = self.library_kind
        loaders = {
            "albums": (self.client.get_favorite_albums, self._on_albums_loaded),
            "playlists": (self.client.get_user_playlists, self._on_albums_loaded),
            "tracks": (self.client.get_favorite_tracks, self._on_tracks_loaded),
            "artists": (self.client.get_favorite_artists, self._on_artists_loaded),
        }
        load, show = loaders[kind]

        def worker():
            items = load()

            def apply():
                # Si mientras tanto se cambió de sección o de tipo, se descarta
                if self.section == "library" and self.library_kind == kind:
                    show(items)
                return False

            GLib.idle_add(apply)

        threading.Thread(target=worker, daemon=True, name=f"qobuz-library-{kind}").start()

    def _show_empty(self):
        empty_row = Gtk.ListBoxRow()
        msg = self.client.last_error or (self._t("qobuz.library_empty") if self.section == "library"
                                         else self._t("qobuz.no_albums_found"))
        empty_lbl = Gtk.Label(label=msg)
        empty_lbl.set_wrap(True)
        empty_lbl.set_margin_top(24)
        empty_lbl.set_margin_bottom(24)
        empty_lbl.add_css_class("dim-label")
        empty_row.set_child(empty_lbl)
        self.albums_listbox.append(empty_row)
        self._render_album_detail(None)

    def _thumb(self, url: str, size: int = 56, round_: bool = False) -> Gtk.Picture:
        picture = FixedPicture(size)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.add_css_class("card")
        if round_:
            picture.add_css_class("qobuz-artist-picture")
        self._set_default_paintable(picture)
        self._load_cover_async(url, picture)
        return picture

    def _on_tracks_loaded(self, tracks: list[QobuzTrack]):
        self._set_loading(False)
        self.favorite_tracks = tracks
        self._clear_albums_list()
        if not tracks:
            self._show_empty()
            return
        for track in tracks:
            self.albums_listbox.append(self._create_fav_track_row(track))
        self._render_album_detail(None)

    def _create_fav_track_row(self, track: QobuzTrack) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._fav_track = track
        row.set_sensitive(track.streamable)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        slot = self._mark_slot(Gtk.Box())
        box.append(slot)
        box.append(self._thumb(track.cover_url, 44))

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)
        title_lbl = Gtk.Label(label=track.title)
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(title_lbl)
        mark = (track.id, slot, title_lbl)
        self._list_marks.append(mark)
        self._apply_mark(mark)
        self._add_context_menu(row, lambda: self._track_menu(track, self.favorite_tracks))
        sub = " • ".join(x for x in (track.artist, track.album_title) if x)
        sub_lbl = Gtk.Label(label=sub)
        sub_lbl.set_halign(Gtk.Align.START)
        sub_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        sub_lbl.add_css_class("dim-label")
        sub_lbl.add_css_class("caption")
        text_box.append(sub_lbl)
        box.append(text_box)

        if track.hires:
            badge = Gtk.Label(label=self._quality_str(track))
            badge.add_css_class("tag-badge")
            badge.add_css_class("tag-badge-flac")
            badge.set_valign(Gtk.Align.CENTER)
            box.append(badge)
        dur_lbl = Gtk.Label(label=f"{int(track.duration // 60)}:{int(track.duration % 60):02d}")
        dur_lbl.add_css_class("dim-label")
        dur_lbl.add_css_class("numeric")
        box.append(dur_lbl)
        row.set_child(box)
        return row

    def _show_track_album(self, track: QobuzTrack):
        """Al seleccionar un tema favorito se muestra su álbum."""
        if not track.album_id:
            return
        self._detail_token += 1
        token = self._detail_token

        def worker():
            album = self.client.get_album(track.album_id)

            def apply():
                if album and token == self._detail_token:
                    self.selected_album = album
                    self._render_album_detail(album)
                return False

            GLib.idle_add(apply)

        threading.Thread(target=worker, daemon=True, name="qobuz-track-album").start()

    def _on_artists_loaded(self, artists: list[QobuzArtist]):
        self._set_loading(False)
        self._clear_albums_list()
        if not artists:
            self._show_empty()
            return
        for artist in artists:
            self.albums_listbox.append(self._create_artist_row(artist))
        first = self.albums_listbox.get_row_at_index(0)
        if first:
            self.albums_listbox.select_row(first)

    def _create_artist_row(self, artist: QobuzArtist) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._artist_data = artist
        self._add_context_menu(row, lambda: self._artist_menu(artist))
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.append(self._thumb(artist.image_url, 48, round_=True))
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)
        name_lbl = Gtk.Label(label=artist.name)
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_lbl.add_css_class("heading")
        text_box.append(name_lbl)
        if artist.albums_count:
            count_lbl = Gtk.Label(label=self._t("qobuz.artist_albums", n=artist.albums_count))
            count_lbl.set_halign(Gtk.Align.START)
            count_lbl.add_css_class("dim-label")
            count_lbl.add_css_class("caption")
            text_box.append(count_lbl)
        box.append(text_box)
        row.set_child(box)
        return row

    def _clear_detail(self):
        self._detail_marks = []
        while True:
            child = self.detail_container.get_first_child()
            if not child:
                break
            self.detail_container.remove(child)

    def _render_artist_detail(self, artist: QobuzArtist, release_type: str = "album", back=None):
        """
        Cabecera del artista y su discografía separada como en Qobuz: Álbumes, EPs y singles,
        Directos y Recopilatorios. Al pulsar un disco se abre, con un botón para volver.
        """
        self._detail_token += 1
        token = self._detail_token
        self._clear_detail()
        if back:
            self.detail_container.append(self._back_button(back))

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        picture = self._thumb(artist.image_url, 120, round_=True)
        head.append(picture)
        name_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        name_col.set_valign(Gtk.Align.CENTER)
        name = Gtk.Label(label=artist.name)
        name.add_css_class("title-1")
        name.set_wrap(True)
        name.set_halign(Gtk.Align.START)
        name_col.append(name)
        name_col.append(self._artist_favorite_button(artist))
        head.append(name_col)
        self.detail_container.append(head)
        if not artist.image_url:
            # Abierto desde un disco o un tema: se completa la foto en cuanto llegue
            def fetch_picture():
                full = self.client.get_artist(artist.id)
                if full and full.image_url and token == self._detail_token:
                    artist.image_url = full.image_url
                    GLib.idle_add(lambda: (self._load_cover_async(full.image_url, picture), False)[1])

            threading.Thread(target=fetch_picture, daemon=True, name="qobuz-artist-picture").start()

        # Pestañas de tipo de lanzamiento
        tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tabs.add_css_class("linked")
        tabs.set_halign(Gtk.Align.START)
        buttons: dict[str, Gtk.ToggleButton] = {}
        first = None
        for rt in self.client.release_types:
            btn = Gtk.ToggleButton(label=self._t(f"qobuz.releases.{rt}"))
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            buttons[rt] = btn
            tabs.append(btn)
        buttons[release_type].set_active(True)
        self.detail_container.append(tabs)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.detail_container.append(content)
        cache = self._artist_cache.setdefault(artist.id, {})

        def show(rt: str, albums: list[QobuzAlbum], auto: bool):
            while (child := content.get_first_child()) is not None:
                content.remove(child)
            if not albums:
                if auto and rt == "album":
                    # Artista sin álbumes (solo singles, por ejemplo): se abre la siguiente pestaña
                    buttons["epSingle"].set_active(True)
                    return
                lbl = Gtk.Label(label=self.client.last_error or self._t(f"qobuz.releases.empty_{rt}"))
                lbl.add_css_class("dim-label")
                lbl.set_wrap(True)
                lbl.set_margin_top(20)
                content.append(lbl)
                return
            listbox = Gtk.ListBox()
            listbox.add_css_class("boxed-list")
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            for album in albums:
                listbox.append(self._create_album_row(album))
            back_here = (artist.name, lambda: self._render_artist_detail(artist, rt, back))
            listbox.connect("row-activated", lambda _lb, row: self._open_album(row._album_data, back_here))
            content.append(listbox)

        def load(rt: str, auto: bool = False):
            if rt in cache:
                show(rt, cache[rt], auto)
                return
            while (child := content.get_first_child()) is not None:
                content.remove(child)
            spinner = Gtk.Spinner()
            spinner.start()
            spinner.set_margin_top(20)
            content.append(spinner)

            def worker():
                albums = self.client.get_artist_releases(artist.id, rt)

                def apply():
                    if token != self._detail_token:
                        return False  # Se abrió otra cosa mientras tanto
                    if albums or not self.client.last_error:
                        cache[rt] = albums
                    if buttons[rt].get_active():
                        show(rt, albums, auto)
                    return False

                GLib.idle_add(apply)

            threading.Thread(target=worker, daemon=True, name=f"qobuz-artist-{rt}").start()

        for rt, btn in buttons.items():
            btn.connect("toggled", lambda b, rt=rt: b.get_active() and load(rt))
        load(release_type, auto=release_type == "album")

    # -------------------------------------------------------------------------
    # Libretos digitales (PDF)
    # -------------------------------------------------------------------------

    def _booklet_buttons(self, album: QobuzAlbum, booklet) -> Gtk.Widget:
        """[ 📄 Libreto ] [ ⬇ ]: abrir en el visor de PDF o guardar una copia."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("linked")
        name = self._booklet_label(booklet)
        view_btn = Gtk.Button()
        view_btn.set_child(Adw.ButtonContent(icon_name="x-office-document-symbolic", label=name))
        view_btn.add_css_class("pill")
        view_btn.set_tooltip_text(self._t("qobuz.booklet.view"))
        save_btn = Gtk.Button.new_from_icon_name("document-save-symbolic")
        save_btn.add_css_class("pill")
        save_btn.set_tooltip_text(self._t("qobuz.booklet.save"))
        view_btn.connect("clicked", lambda *_: self._open_booklet(album, booklet, view_btn))
        save_btn.connect("clicked", lambda *_: self._save_booklet(album, booklet))
        box.append(view_btn)
        box.append(save_btn)
        return box

    def _booklet_label(self, booklet) -> str:
        """Nombre del extra en el idioma de MyFlac (Qobuz los da en francés o inglés)."""
        key = BOOKLET_KINDS.get(_simplify(booklet.name))
        if key or not booklet.name:
            return self._t(key or "qobuz.booklet.default_name")
        return booklet.name  # Título propio del disco: se respeta

    def _booklet_filename(self, album: QobuzAlbum, booklet) -> str:
        base = f"{album.artist} - {album.title}"
        base += f" - {self._booklet_label(booklet)}"
        safe = "".join("_" if c in '/\\:*?"<>|' else c for c in base).strip()
        return (safe or "booklet")[:180] + ".pdf"

    def _download_booklet(self, booklet, dest: Path, done: Callable[[str], None]):
        """Descarga el PDF a `dest` en otro hilo; `done` recibe el error ('' si fue bien)."""
        def worker():
            error = ""
            try:
                import urllib.request
                req = urllib.request.Request(booklet.url, headers={"User-Agent": "Mozilla/5.0"})
                tmp = dest.with_suffix(".part")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as f:
                    while chunk := resp.read(262144):
                        f.write(chunk)
                tmp.replace(dest)
            except Exception as e:
                log.warning("No se pudo descargar el libreto %s: %s", booklet.url, e)
                error = str(e)
            GLib.idle_add(lambda: (done(error), False)[1])

        threading.Thread(target=worker, daemon=True, name="qobuz-booklet").start()

    def _open_booklet(self, album: QobuzAlbum, booklet, button: Gtk.Button):
        """Abre el libreto en el visor de PDF del sistema (se guarda en la caché la primera vez)."""
        dest = BOOKLET_CACHE_DIR / f"{hashlib.md5(booklet.url.encode()).hexdigest()}.pdf"

        def launch(error: str = ""):
            button.set_sensitive(True)
            if error:
                self._toast(self._t("qobuz.booklet.failed", error=error))
                return
            launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(dest)))
            launcher.launch(self.get_root(), None, None)

        if dest.is_file():
            launch()
            return
        button.set_sensitive(False)
        self._toast(self._t("qobuz.booklet.downloading"))
        self._download_booklet(booklet, dest, launch)

    def _save_booklet(self, album: QobuzAlbum, booklet):
        """Guarda una copia del libreto donde elija el usuario."""
        dialog = Gtk.FileDialog()
        dialog.set_title(self._t("qobuz.booklet.save"))
        dialog.set_initial_name(self._booklet_filename(album, booklet))
        downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if downloads:
            dialog.set_initial_folder(Gio.File.new_for_path(downloads))

        def on_chosen(dlg, result):
            try:
                gfile = dlg.save_finish(result)
            except GLib.Error:
                return  # Cancelado
            dest = Path(gfile.get_path())
            cached = BOOKLET_CACHE_DIR / f"{hashlib.md5(booklet.url.encode()).hexdigest()}.pdf"

            def saved(error: str):
                if error:
                    self._toast(self._t("qobuz.booklet.failed", error=error))
                else:
                    self._toast(self._t("qobuz.booklet.saved", path=str(dest)))

            if cached.is_file():
                try:
                    import shutil
                    shutil.copyfile(cached, dest)
                    saved("")
                except OSError as e:
                    saved(str(e))
            else:
                self._download_booklet(booklet, dest, saved)

        dialog.save(self.get_root(), None, on_chosen)

    def _back_button(self, back) -> Gtk.Button:
        btn = Gtk.Button()
        btn.add_css_class("flat")
        btn.set_halign(Gtk.Align.START)
        btn.set_child(Adw.ButtonContent(icon_name="go-previous-symbolic",
                                        label=self._t("qobuz.back_to", name=back[0])))
        btn.connect("clicked", lambda *_: back[1]())
        return btn

    def _open_artist(self, artist_id: int, name: str, back=None):
        self._render_artist_detail(QobuzArtist(id=artist_id, name=name), back=back)

    def _artist_favorite_button(self, artist: QobuzArtist) -> Gtk.Button:
        """Botón «Añadir a mi biblioteca» / «En mi biblioteca» de la página del artista."""
        btn = Gtk.Button()
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.START)

        def show(fav: bool):
            btn.set_child(Adw.ButtonContent(
                icon_name="starred-symbolic" if fav else "non-starred-symbolic",
                label=self._t("qobuz.fav.in_library" if fav else "qobuz.fav.add_artists")))
            btn.set_tooltip_text(self._t("qobuz.fav.remove_artists") if fav else None)
            if fav:
                btn.remove_css_class("suggested-action")
            else:
                btn.add_css_class("suggested-action")
            btn._fav = fav

        fav = self.client.is_favorite("artists", artist.id)
        if fav is None:
            fav = self.section == "library" and self.library_kind == "artists"
        show(bool(fav))

        def on_click(_b):
            btn.set_sensitive(False)
            add = not btn._fav

            def done(ok: bool):
                btn.set_sensitive(True)
                if ok:
                    show(add)

            self._toggle_favorite("artists", artist.id, artist.name, add, on_done=done)

        btn.connect("clicked", on_click)
        return btn

    def _open_album(self, album: QobuzAlbum, back=None):
        self.selected_album = album
        self._render_album_detail(album, back)

    # -------------------------------------------------------------------------
    # Renderizado del detalle del álbum seleccionado
    # -------------------------------------------------------------------------

    def _render_album_detail(self, album: QobuzAlbum | None, back=None):
        """Detalle de un álbum o lista. `back` = (nombre, función) añade un botón para volver."""
        self._detail_token += 1
        self._clear_detail()

        if album and back:
            back_btn = Gtk.Button()
            back_btn.add_css_class("flat")
            back_btn.set_halign(Gtk.Align.START)
            back_content = Adw.ButtonContent(icon_name="go-previous-symbolic",
                                             label=self._t("qobuz.back_to", name=back[0]))
            back_btn.set_child(back_content)
            back_btn.connect("clicked", lambda *_: back[1]())
            self.detail_container.append(back_btn)

        if not album:
            lbl = Gtk.Label(label=self._t("qobuz.select_album_hint"))
            lbl.set_margin_top(60)
            lbl.add_css_class("dim-label")
            self.detail_container.append(lbl)
            return

        # 1. Cabecera del Álbum
        head_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        head_box.set_margin_bottom(12)

        # Portada grande (160x160)
        big_cover = FixedPicture(160)
        big_cover.set_can_shrink(True)
        big_cover.set_content_fit(Gtk.ContentFit.COVER)
        big_cover.add_css_class("card")
        self._set_default_paintable(big_cover)
        self._load_cover_async(album.cover_url, big_cover)
        head_box.append(big_cover)

        # Información textual y botones
        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info_col.set_hexpand(True)
        info_col.set_valign(Gtk.Align.CENTER)

        alb_title = Gtk.Label(label=album.title)
        alb_title.set_halign(Gtk.Align.START)
        alb_title.set_wrap(True)
        alb_title.add_css_class("title-1")
        info_col.append(alb_title)

        alb_artist = Gtk.Label(label=album.artist)
        alb_artist.set_halign(Gtk.Align.START)
        alb_artist.add_css_class("title-3")
        alb_artist.add_css_class("dim-label")
        if album.kind == "album" and album.artist_id:
            # El nombre lleva a la página del artista (y desde allí, a añadirlo a la biblioteca)
            artist_btn = Gtk.Button()
            artist_btn.set_child(alb_artist)
            artist_btn.add_css_class("flat")
            artist_btn.add_css_class("qobuz-artist-link")
            artist_btn.set_halign(Gtk.Align.START)
            artist_btn.set_tooltip_text(self._t("qobuz.view_artist"))
            artist_btn.connect("clicked", lambda *_: self._open_artist(
                album.artist_id, album.artist, (album.title, lambda: self._open_album(album, back))))
            info_col.append(artist_btn)
        else:
            info_col.append(alb_artist)

        meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        if album.kind == "playlist":
            count = len(album.tracks) or album.tracks_count
            hires_lbl = Gtk.Label(label=self._t("qobuz.playlist_tracks", n=count))
            hires_lbl.add_css_class("dim-label")
        else:
            hires_lbl = Gtk.Label(label=album.hires_badge)
            hires_lbl.add_css_class("tag-badge")
            if album.hires:
                hires_lbl.add_css_class("tag-badge-flac")
        meta_box.append(hires_lbl)

        extra_str = album.release_date
        if album.genre_name:
            extra_str += f" • {album.genre_name}"
        extra_lbl = Gtk.Label(label=extra_str)
        extra_lbl.add_css_class("dim-label")
        meta_box.append(extra_lbl)
        info_col.append(meta_box)

        # Botón reproducir todo el álbum
        btn_play_album = Gtk.Button(label=self._t("qobuz.play_playlist" if album.kind == "playlist"
                                                  else "qobuz.play_album"))
        btn_play_album.set_icon_name("media-playback-start-symbolic")
        btn_play_album.add_css_class("suggested-action")
        btn_play_album.add_css_class("pill")
        btn_play_album.set_halign(Gtk.Align.START)
        btn_play_album.set_margin_top(6)
        btn_play_album.connect("clicked", lambda *_: self._play_entire_album(album))
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_margin_top(6)
        btn_play_album.set_margin_top(0)
        actions.append(btn_play_album)
        for booklet in album.booklets:
            actions.append(self._booklet_buttons(album, booklet))
        info_col.append(actions)

        head_box.append(info_col)
        self.detail_container.append(head_box)

        # 2. Separador
        self.detail_container.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # 3. Lista de temas
        tracks_list = Gtk.ListBox()
        tracks_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        tracks_list.set_activate_on_single_click(False)
        tracks_list.add_css_class("boxed-list")
        tracks_list.connect("row-activated", self._on_track_row_activated)

        # Cargar pistas si no están descargadas
        if not album.tracks:
            loading_row = Gtk.ListBoxRow()
            loading_row.set_selectable(False)
            loading_row.set_activatable(False)
            lbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            lbox.set_halign(Gtk.Align.CENTER)
            lbox.set_margin_top(20)
            lbox.set_margin_bottom(20)
            sp = Gtk.Spinner()
            sp.start()
            lbox.append(sp)
            loading_lbl = Gtk.Label(label=self._t("qobuz.loading_tracks"))
            loading_lbl.add_css_class("dim-label")
            lbox.append(loading_lbl)
            loading_row.set_child(lbox)
            tracks_list.append(loading_row)
            self.detail_container.append(tracks_list)

            # Carga asíncrona de pistas completas
            def track_worker():
                full_alb = self._fetch_full(album)
                if full_alb and full_alb.tracks:
                    album.tracks = full_alb.tracks
                    album.booklets = full_alb.booklets
                    GLib.idle_add(lambda: (self.selected_album is album and self._render_album_detail(album, back), False)[-1])
                else:
                    msg = self.client.last_error or self._t("qobuz.no_tracks")
                    GLib.idle_add(lambda: (loading_lbl.set_label(msg), sp.stop(), sp.set_visible(False), False)[-1])

            threading.Thread(target=track_worker, daemon=True).start()
            return

        for track in album.tracks:
            row = self._create_track_row(track, album)
            tracks_list.append(row)

        self.detail_container.append(tracks_list)

    def _create_track_row(self, track: QobuzTrack, album: QobuzAlbum) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._track_data = track
        row._album_data = album
        row.set_activatable(track.streamable)
        row.set_sensitive(track.streamable)

        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row_box.set_margin_start(14)
        row_box.set_margin_end(14)
        row_box.set_margin_top(10)
        row_box.set_margin_bottom(10)

        # Número de pista (o la onda si es el tema que suena)
        num_lbl = Gtk.Label(label=f"{track.track_number:02d}")
        num_lbl.add_css_class("dim-label")
        num_lbl.add_css_class("numeric")
        num_stack = self._mark_slot(num_lbl)
        row_box.append(num_stack)

        # Título
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        title_lbl = Gtk.Label(label=track.title)
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_box.append(title_lbl)
        mark = (track.id, num_stack, title_lbl)
        self._detail_marks.append(mark)
        self._apply_mark(mark)
        self._add_context_menu(row, lambda: self._track_menu(track, album.tracks))

        if track.artist and track.artist != album.artist:
            art_lbl = Gtk.Label(label=track.artist)
            art_lbl.set_halign(Gtk.Align.START)
            art_lbl.add_css_class("dim-label")
            art_lbl.add_css_class("caption")
            title_box.append(art_lbl)

        row_box.append(title_box)

        # Calidad
        qual_lbl = Gtk.Label(label=self._quality_str(track))
        qual_lbl.add_css_class("tag-badge")
        if track.hires:
            qual_lbl.add_css_class("tag-badge-flac")
        row_box.append(qual_lbl)

        # Duración
        mins = int(track.duration // 60)
        secs = int(track.duration % 60)
        dur_lbl = Gtk.Label(label=f"{mins}:{secs:02d}")
        dur_lbl.add_css_class("dim-label")
        dur_lbl.add_css_class("numeric")
        row_box.append(dur_lbl)

        # Botón Play individual
        btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        btn_play.add_css_class("flat")
        btn_play.set_tooltip_text(self._t("qobuz.play_track_tooltip"))
        btn_play.connect("clicked", lambda *_: self._play_track(track, album))
        row_box.append(btn_play)

        # Botón Añadir a la cola
        if self.on_queue_track:
            btn_queue = Gtk.Button.new_from_icon_name("list-add-symbolic")
            btn_queue.add_css_class("flat")
            btn_queue.set_tooltip_text(self._t("qobuz.queue_track_tooltip"))
            btn_queue.connect("clicked", lambda *_: self._queue_track(track))
            row_box.append(btn_queue)

        row.set_child(row_box)
        return row

    @staticmethod
    def _quality_str(track: QobuzTrack) -> str:
        if not track.sample_rate:
            return f"{track.bit_depth}-Bit Hi-Res"  # Frecuencia exacta desconocida hasta reproducir
        rate_khz = track.sample_rate / 1000
        rate = f"{int(rate_khz)}" if rate_khz.is_integer() else f"{rate_khz:.1f}"
        return f"{track.bit_depth}-Bit / {rate} kHz"

    def _on_track_row_activated(self, _listbox, row: Gtk.ListBoxRow):
        """Doble clic en una canción inicia su reproducción."""
        if hasattr(row, "_track_data"):
            self._play_track(row._track_data, row._album_data)

    # -------------------------------------------------------------------------
    # Reproducción de streaming
    # -------------------------------------------------------------------------

    def _fetch_full(self, album: QobuzAlbum) -> QobuzAlbum | None:
        """Álbum o lista con todas sus pistas (bloqueante: desde un hilo)."""
        if album.kind == "playlist":
            return self.client.get_playlist(album.id)
        return self.client.get_album(album.id)

    def _play_from(self, album: QobuzAlbum, start: QobuzTrack | None = None):
        """Reproduce el álbum o la lista desde `start` (o desde el principio); el resto, a la cola."""
        log.info("Reproduciendo de Qobuz: %s - %s", album.artist, album.title)
        self._play_tracks(album.tracks, start)

    def _play_tracks(self, tracks: list[QobuzTrack], start: QobuzTrack | None = None):
        tracks = [t for t in tracks if t.streamable]
        if start is not None and start in tracks:
            tracks = tracks[tracks.index(start):]
        if not tracks:
            log.warning("No hay pistas reproducibles")
            return
        audio_tracks = [self.client.to_audio_track(t) for t in tracks]
        if self.on_play_list:
            self.on_play_list(audio_tracks)
        elif self.on_track_activate:
            self.on_track_activate(audio_tracks[0])

    def _play_track(self, track: QobuzTrack, album: QobuzAlbum):
        self._play_from(album, track)

    def _queue_track(self, track: QobuzTrack):
        audio_track = self.client.to_audio_track(track)
        log.info("Pista de Qobuz encolada: %s - %s", audio_track.artist, audio_track.title)
        if self.on_queue_track:
            self.on_queue_track(audio_track)

    def _play_entire_album(self, album: QobuzAlbum):
        if album.tracks:
            self._play_from(album)
            return
        self._set_loading(True)

        def fetch_worker():
            full_alb = self._fetch_full(album)

            def on_fetched():
                self._set_loading(False)
                if full_alb and full_alb.tracks:
                    album.tracks = full_alb.tracks
                    album.booklets = full_alb.booklets
                    if self.selected_album is album:
                        self._render_album_detail(album)
                    self._play_from(album)
                elif self.parent_window is not None and hasattr(self.parent_window, "_on_playback_error"):
                    self.parent_window._on_playback_error(self.client.last_error or self._t("qobuz.no_tracks"))
                return False

            GLib.idle_add(on_fetched)

        threading.Thread(target=fetch_worker, daemon=True, name="qobuz-album").start()

    # -------------------------------------------------------------------------
    # Tema en reproducción
    # -------------------------------------------------------------------------

    @staticmethod
    def _mark_slot(idle_child: Gtk.Widget) -> Gtk.Stack:
        """Hueco de ancho fijo que muestra `idle_child` o la onda animada si el tema suena."""
        stack = Gtk.Stack()
        stack.set_size_request(26, -1)
        stack.set_valign(Gtk.Align.CENTER)
        stack.add_named(idle_child, "idle")
        stack.add_named(PlayingWaveIndicator(), "wave")
        stack.set_visible_child_name("idle")
        return stack

    def _apply_mark(self, mark: tuple):
        track_id, stack, title_lbl = mark
        playing = self._playing_active and track_id == self._playing_id
        wave = stack.get_child_by_name("wave")
        wave.set_state(playing, self._playing_paused)
        stack.set_visible_child_name("wave" if playing else "idle")
        if playing:
            title_lbl.add_css_class("row-playing")
        else:
            title_lbl.remove_css_class("row-playing")

    def _refresh_marks(self):
        for mark in self._list_marks + self._detail_marks:
            self._apply_mark(mark)

    def set_playing_track(self, track: AudioTrack | None, is_playing: bool, is_paused: bool):
        """La ventana avisa del tema en reproducción: se marca si es de Qobuz y está a la vista."""
        sid = getattr(track, "stream_id", "") if track else ""
        prefix = f"{self.SERVICE}:"
        self._playing_id = int(sid[len(prefix):]) if sid.startswith(prefix) else None
        self._playing_active = is_playing or is_paused
        self._playing_paused = is_paused
        self._refresh_marks()

    # -------------------------------------------------------------------------
    # Menú del botón derecho: reproducir, cola y «Mi biblioteca» de Qobuz
    # -------------------------------------------------------------------------

    def _add_context_menu(self, row: Gtk.Widget, build: Callable[[], list]):
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", lambda _g, _n, x, y: self._show_menu(row, x, y, build()))
        row.add_controller(click)

    def _show_menu(self, widget: Gtk.Widget, x: float, y: float, entries: list):
        """entries: (icono, texto, función) o None para un separador."""
        popover = Gtk.Popover()
        popover.set_parent(widget)
        popover.set_has_arrow(True)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("context-menu-box")
        for m in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{m}")(4)
        for entry in entries:
            if entry is None:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                sep.set_margin_top(4)
                sep.set_margin_bottom(4)
                box.append(sep)
                continue
            icon, text, callback = entry
            btn = Gtk.Button()
            btn.add_css_class("flat")
            btn.add_css_class("context-menu-item")
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            img = Gtk.Image.new_from_icon_name(icon)
            img.set_pixel_size(16)
            lbl = Gtk.Label(label=text, xalign=0.0)
            lbl.set_hexpand(True)
            content.append(img)
            content.append(lbl)
            btn.set_child(content)
            btn.connect("clicked", lambda *_, cb=callback: (popover.popdown(), cb()))
            box.append(btn)
        popover.set_child(box)
        popover.connect("closed", lambda *_: GLib.idle_add(lambda: (popover.unparent(), False)[1]))
        popover.popup()

    def _favorite_entry(self, kind: str, item_id, name: str):
        """Entrada «Añadir a / Quitar de mi biblioteca» según lo que ya tenga el usuario."""
        fav = self.client.is_favorite(kind, item_id)
        if fav is None and self.section == "library" and self.library_kind == kind:
            fav = True  # Está en la lista de favoritos que se está viendo
        if fav:
            return ("starred-symbolic", self._t(f"qobuz.fav.remove_{kind}"),
                    lambda: self._toggle_favorite(kind, item_id, name, False))
        return ("non-starred-symbolic", self._t(f"qobuz.fav.add_{kind}"),
                lambda: self._toggle_favorite(kind, item_id, name, True))

    def _toggle_favorite(self, kind: str, item_id, name: str, add: bool, on_done=None):
        def worker():
            try:
                self.client.set_favorite(kind, item_id, add)
                msg = self._t("qobuz.fav.added" if add else "qobuz.fav.removed", name=name)
                ok = True
            except Exception as e:
                msg, ok = str(e), False

            def apply():
                self._toast(msg)
                if on_done:
                    on_done(ok)
                if ok and self.section == "library" and self.library_kind == kind:
                    self.refresh_catalog()  # La lista de favoritos que se ve ha cambiado
                return False

            GLib.idle_add(apply)

        threading.Thread(target=worker, daemon=True, name="qobuz-favorite").start()

    def _toast(self, msg: str):
        overlay = getattr(self.parent_window, "toast_overlay", None)
        if overlay is not None:
            toast = Adw.Toast.new(msg)
            toast.set_timeout(3)
            overlay.add_toast(toast)
        else:
            log.info("%s", msg)

    def _track_menu(self, track: QobuzTrack, context: list[QobuzTrack]) -> list:
        entries = [("media-playback-start-symbolic", i18n.t("context.play_now"),
                    lambda: self._play_tracks(context, track))]
        if self.on_play_next:
            entries.append(("media-skip-forward-symbolic", i18n.t("context.play_next"),
                            lambda: self.on_play_next(self.client.to_audio_track(track))))
        if self.on_queue_track:
            entries.append(("list-add-symbolic", i18n.t("context.add_queue"), lambda: self._queue_track(track)))
        entries.append(None)
        entries.append(self._favorite_entry("tracks", track.id, track.title))
        if track.album_id:
            entries.append(self._favorite_entry("albums", track.album_id, track.album_title))
        if track.artist_id:
            entries.append(self._favorite_entry("artists", track.artist_id, track.artist))
            entries.append(None)
            entries.append(("avatar-default-symbolic", self._t("qobuz.view_artist"),
                            lambda: self._open_artist(track.artist_id, track.artist)))
        return entries

    def _album_menu(self, album: QobuzAlbum) -> list:
        entries = [("media-playback-start-symbolic", self._t("qobuz.play_playlist" if album.kind == "playlist"
                                                            else "qobuz.play_album"),
                    lambda: self._play_entire_album(album))]
        if self.on_queue_track:
            entries.append(("list-add-symbolic", i18n.t("context.add_queue"), lambda: self._queue_album(album)))
        if album.kind == "album":
            entries.append(None)
            entries.append(self._favorite_entry("albums", album.id, album.title))
            if album.artist_id:
                entries.append(self._favorite_entry("artists", album.artist_id, album.artist))
                entries.append(None)
                entries.append(("avatar-default-symbolic", self._t("qobuz.view_artist"),
                                lambda: self._open_artist(album.artist_id, album.artist)))
        return entries

    def _artist_menu(self, artist: QobuzArtist) -> list:
        return [self._favorite_entry("artists", artist.id, artist.name)]

    def _queue_album(self, album: QobuzAlbum):
        def enqueue(alb: QobuzAlbum):
            for t in alb.tracks:
                if t.streamable:
                    self._queue_track(t)

        if album.tracks:
            enqueue(album)
            return

        def worker():
            full = self._fetch_full(album)
            if full and full.tracks:
                album.tracks = full.tracks
                album.booklets = full.booklets
                GLib.idle_add(lambda: (enqueue(album), False)[1])

        threading.Thread(target=worker, daemon=True, name="qobuz-queue-album").start()

    def _load_favorite_ids(self):
        if self.client.is_logged_in:
            threading.Thread(target=self.client.load_favorite_ids, daemon=True, name="qobuz-fav-ids").start()

    # -------------------------------------------------------------------------
    # Gestión de cuenta y portadas
    # -------------------------------------------------------------------------

    def _open_login_dialog(self, _btn):
        # Importación diferida: la ventana web necesita WebKitGTK, que es opcional
        from .qobuz_login_dialog import QobuzLoginDialog
        dlg = QobuzLoginDialog(parent=self.parent_window, on_auth_changed=self._on_auth_changed)
        dlg.present()

    def _open_manual_token_dialog(self, _btn):
        from .qobuz_login_dialog import QobuzManualTokenDialog
        dlg = QobuzManualTokenDialog(parent=self.parent_window, on_auth_changed=self._on_auth_changed)
        dlg.present()

    def _on_auth_changed(self):
        if not self.client.is_logged_in:
            self.btn_explore.set_active(True)
        self._load_favorite_ids()
        self._update_auth_ui()
        if self.client.is_logged_in:
            self._load_genres()
            self.refresh_catalog()

    def _load_cover_async(self, url: str, picture: Gtk.Picture):
        if not url:
            return

        cache_name = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
        cache_path = COVER_CACHE_DIR / cache_name

        if cache_path.is_file():
            try:
                texture = Gdk.Texture.new_from_filename(str(cache_path))
                picture.set_paintable(texture)
                return
            except Exception:
                pass

        def worker():
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = resp.read()
                with open(cache_path, "wb") as f:
                    f.write(data)
                GLib.idle_add(lambda: self._set_texture(picture, cache_path))
            except Exception as e:
                log.debug("No se pudo descargar portada de Qobuz %s: %s", url, e)

        threading.Thread(target=worker, daemon=True).start()

    def _set_texture(self, picture: Gtk.Picture, path: Path):
        try:
            if path.is_file():
                texture = Gdk.Texture.new_from_filename(str(path))
                picture.set_paintable(texture)
        except Exception as e:
            log.debug("Error asignando textura de portada: %s", e)
