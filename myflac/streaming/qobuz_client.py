"""Cliente de streaming e integración con el catálogo Hi-Res de Qobuz para MyFlac.

Las credenciales de aplicación (app_id y clave de firma) las concede Qobuz a cada desarrollador:
no van en el código, se leen de la configuración local del usuario (~/.config/myflac/qobuz.json).
Todas las llamadas son bloqueantes: la interfaz las hace desde hilos de trabajo.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import i18n
from ..audio.track import AudioTrack
from ..logger import get_logger

log = get_logger("streaming.qobuz")

API_BASE_URL = "https://www.qobuz.com/api.json/0.2"
CONFIG_PATH = Path.home() / ".config" / "myflac" / "qobuz.json"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"

# Formatos de Qobuz: 5 = MP3 320, 6 = FLAC 16/44.1, 7 = FLAC 24 bit hasta 96 kHz,
# 27 = FLAC 24 bit hasta 192 kHz. Qobuz entrega la mejor calidad disponible hasta la pedida.
FORMAT_MP3, FORMAT_CD, FORMAT_HIRES_96, FORMAT_HIRES_192 = 5, 6, 7, 27
DEFAULT_MAX_FORMAT = FORMAT_HIRES_192


class QobuzError(Exception):
    """Error comprensible para el usuario (ya traducido)."""


class QobuzAuthError(QobuzError):
    """La sesión no es válida o ha caducado."""


@dataclass
class QobuzGenre:
    id: int
    name: str
    slug: str


@dataclass
class QobuzTrack:
    id: int
    title: str
    artist: str
    album_title: str
    duration: float
    track_number: int
    hires: bool
    bit_depth: int
    sample_rate: int
    cover_url: str = ""
    streamable: bool = True
    album_id: str = ""  # Álbum al que pertenece (en favoritos y listas cada pista es de uno distinto)
    artist_id: int = 0  # Artista principal (el del álbum)


@dataclass
class Booklet:
    """Libreto digital u otro extra en PDF que acompaña a un disco."""
    name: str
    url: str


@dataclass
class QobuzArtist:
    id: int
    name: str
    image_url: str = ""
    albums_count: int = 0


@dataclass
class QobuzAlbum:
    id: str
    title: str
    artist: str
    cover_url: str
    release_date: str
    hires: bool
    maximum_bit_depth: int
    maximum_sampling_rate: float
    genre_id: int
    genre_name: str = ""
    tracks: list[QobuzTrack] = field(default_factory=list)
    kind: str = "album"  # "album" o "playlist" (una lista se muestra y reproduce como un álbum)
    tracks_count: int = 0
    release_type: str = ""  # Tipo según Qobuz: album, single, ep, live, compilation...
    artist_id: int = 0
    booklets: list[Booklet] = field(default_factory=list)  # Libretos digitales (PDF) del disco

    @property
    def hires_badge(self) -> str:
        if not self.hires:
            return "16-Bit / 44.1 kHz FLAC"
        rate = self.maximum_sampling_rate
        if not rate:
            return f"{self.maximum_bit_depth}-Bit Hi-Res"  # Frecuencia desconocida (TIDAL)
        rate_khz = int(rate) if float(rate).is_integer() else rate
        return f"{self.maximum_bit_depth}-Bit / {rate_khz} kHz Hi-Res"


def parse_booklets(goodies) -> list[Booklet]:
    """Extras en PDF de un disco («goodies» de Qobuz: libreto digital, partituras...)."""
    out: list[Booklet] = []
    for g in goodies or []:
        if not isinstance(g, dict):
            continue
        url = g.get("original_url") or g.get("url") or ""
        is_pdf = url.lower().split("?", 1)[0].endswith(".pdf") or g.get("file_format_id") == 21
        if url.startswith("http") and is_pdf:
            out.append(Booklet(name=(g.get("name") or g.get("description") or "").strip(), url=url))
    return out


# Pestañas de la discografía de un artista (tipos de Qobuz, en este orden)
ARTIST_RELEASE_TYPES = ("album", "epSingle", "live", "compilation")


def classify_release(release_type: str) -> str:
    """Tipo de lanzamiento de Qobuz → pestaña de la discografía."""
    rt = (release_type or "").lower()
    if rt in ("single", "ep", "epmini", "epsingle", "ep-single"):
        return "epSingle"
    if rt in ("live",):
        return "live"
    if rt in ("compilation", "compil"):
        return "compilation"
    return "album"


@dataclass
class StreamInfo:
    """URL firmada de una pista y la calidad real que entrega Qobuz."""
    url: str
    mime_type: str
    bit_depth: int
    sample_rate: int
    format_id: int
    is_sample: bool = False  # Solo un fragmento de 30 s (la suscripción no da acceso completo)
    preview_reason: str = ""  # TIDAL: por qué solo hay fragmento (suscripción, compra, nivel de la app)


# Géneros de reserva si la API no responde (los nombres son los de Qobuz)
FALLBACK_GENRES = [
    QobuzGenre(id=112, name="Rock", slug="rock"),
    QobuzGenre(id=80, name="Jazz", slug="jazz"),
    QobuzGenre(id=10, name="Classical", slug="classical"),
    QobuzGenre(id=111, name="Pop", slug="pop"),
    QobuzGenre(id=64, name="Electronic", slug="electronic"),
    QobuzGenre(id=2, name="Blues", slug="blues"),
    QobuzGenre(id=124, name="Soul / Funk / R&B", slug="soul-funk-r-and-b"),
    QobuzGenre(id=127, name="Country / Folk", slug="country-folk"),
    QobuzGenre(id=133, name="Rap / Hip-Hop", slug="rap-hip-hop"),
    QobuzGenre(id=3, name="Soundtracks", slug="soundtracks"),
    QobuzGenre(id=94, name="World", slug="world"),
]


def sign_request(endpoint: str, params: dict[str, Any], ts: str, secret: str) -> str:
    """Firma de Qobuz: método sin barras + parámetros ordenados (clave y valor pegados) + ts + clave."""
    parts = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hashlib.md5(f"{endpoint.replace('/', '')}{parts}{ts}{secret}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class QobuzClient:
    """Cliente para la API de Qobuz v0.2."""

    service = "qobuz"
    release_types = ARTIST_RELEASE_TYPES
    server_side_genres = True  # Qobuz filtra el catálogo por género

    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self.app_id = ""
        self.app_secret = ""
        self.user_auth_token = ""
        self.user_email = ""
        self.user_display_name = ""
        self.subscription_label = ""
        self.max_format_id = DEFAULT_MAX_FORMAT
        self.last_error = ""
        self._lock = threading.RLock()
        # Identificadores de favoritos del usuario (para «Añadir/Quitar de mi biblioteca»)
        self._fav_ids: dict[str, set[str]] | None = None
        self._load_config()

    @property
    def is_logged_in(self) -> bool:
        return bool(self.user_auth_token)

    # -- configuración --------------------------------------------------------

    def _load_config(self) -> None:
        try:
            if self.config_path.is_file():
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.app_id = str(data.get("app_id", ""))
                self.app_secret = data.get("app_secret", "")
                self.user_auth_token = data.get("user_auth_token", "")
                self.user_email = data.get("user_email", "")
                self.user_display_name = data.get("user_display_name", "")
                self.subscription_label = data.get("subscription_label", "")
                self.max_format_id = int(data.get("max_format_id", DEFAULT_MAX_FORMAT))
                self._secure_config_file()
                log.info("Configuración de Qobuz cargada (sesión: %s)", bool(self.user_auth_token))
        except Exception as e:
            log.warning("No se pudo leer la configuración de Qobuz: %s", e)

    def _secure_config_file(self) -> None:
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

    def _save_config(self) -> None:
        data = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
            "user_auth_token": self.user_auth_token,
            "user_email": self.user_email,
            "user_display_name": self.user_display_name,
            "subscription_label": self.subscription_label,
            "max_format_id": self.max_format_id,
        }
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            # El token da acceso a la cuenta: el archivo solo lo puede leer el usuario
            fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._secure_config_file()
        except OSError as e:
            log.error("Error al guardar configuración de Qobuz: %s", e)

    # -- HTTP -----------------------------------------------------------------

    def _request(self, endpoint: str, params: dict[str, Any] | None = None, *,
                 auth: bool = True, timeout: float = 10, form: dict[str, Any] | None = None) -> tuple[int, dict]:
        """Llama a la API (POST de formulario si hay `form`). Devuelve (código HTTP, JSON)."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{API_BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": USER_AGENT, "X-App-Id": self.app_id}
        if auth and self.user_auth_token:
            headers["X-User-Auth-Token"] = self.user_auth_token
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            return e.code, body
        except (OSError, ValueError) as e:
            raise QobuzError(i18n.t("qobuz.err.network", error=e)) from e

    @property
    def has_app_credentials(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def ensure_app(self) -> None:
        """Comprueba que hay credenciales de aplicación de Qobuz configuradas (app_id y clave)."""
        if not self.has_app_credentials:
            raise QobuzError(i18n.t("qobuz.err.app_credentials", path=self.config_path))

    def set_app_credentials(self, app_id: str, app_secret: str) -> None:
        """Credenciales de aplicación concedidas por Qobuz al desarrollador (se guardan en local)."""
        self.app_id, self.app_secret = app_id.strip(), app_secret.strip()
        self._save_config()

    def _signed_file_url(self, track_id: int, format_id: int, secret: str) -> tuple[int, dict]:
        params = {"format_id": format_id, "intent": "stream", "track_id": track_id}
        ts = str(int(time.time()))
        sig = sign_request("track/getFileUrl", params, ts, secret)
        return self._request("track/getFileUrl", {**params, "request_ts": ts, "request_sig": sig})

    # -- sesión ---------------------------------------------------------------

    def _apply_user(self, data: dict) -> None:
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        self.user_email = user.get("email") or self.user_email
        self.user_display_name = user.get("display_name") or user.get("login") or self.user_email
        cred = user.get("credential") if isinstance(user.get("credential"), dict) else {}
        params = cred.get("parameters") if isinstance(cred.get("parameters"), dict) else {}
        sub = user.get("subscription") if isinstance(user.get("subscription"), dict) else {}
        self.subscription_label = (params.get("short_label") or cred.get("label")
                                   or cred.get("description") or sub.get("offer") or "")

    def login_with_password(self, email: str, password: str) -> None:
        """Inicia sesión con correo o usuario y contraseña. La contraseña no se guarda."""
        self.ensure_app()
        login = email.strip()
        status, data = self._request("user/login", {
            "email" if "@" in login else "username": login,
            "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
            "app_id": self.app_id,
        }, auth=False)
        if status in (400, 401) or (status == 200 and not data.get("user_auth_token")):
            raise QobuzAuthError(i18n.t("qobuz.dialog.invalid_creds"))
        if status != 200:
            raise QobuzError(i18n.t("qobuz.err.http", code=status, message=data.get("message", "")))
        self.user_auth_token = data["user_auth_token"]
        self._apply_user(data)
        self._after_login()

    def set_auth_token(self, token: str) -> None:
        """Conecta con un token de usuario y lo valida con Qobuz."""
        token = token.strip()
        if not token:
            raise QobuzError(i18n.t("qobuz.dialog.prompt_token"))
        self.ensure_app()
        previous = self.user_auth_token
        self.user_auth_token = token
        status, data = self._request("user/get")
        if status != 200:
            self.user_auth_token = previous
            raise QobuzAuthError(i18n.t("qobuz.err.invalid_token", code=status))
        self._apply_user(data)
        self._after_login()

    def set_auth_data(self, token: str, email: str = "", display_name: str = "",
                      subscription_label: str = "") -> None:
        """Sesión capturada del reproductor web (ventana de inicio de sesión)."""
        self.user_auth_token = token.strip()
        self.user_email = email or self.user_email
        self.user_display_name = display_name or email or self.user_display_name
        self.subscription_label = subscription_label or self.subscription_label
        self._save_config()

    def complete_web_login(self) -> None:
        """Tras capturar la sesión web: comprueba credenciales y completa el perfil (bloqueante)."""
        self.ensure_app()
        status, data = self._request("user/get")
        if status == 200:
            self._apply_user(data)
        self._after_login()

    def _after_login(self) -> None:
        self._save_config()
        log.info("Sesión de Qobuz iniciada: %s (%s)", self.user_display_name, self.subscription_label)

    def logout(self) -> None:
        """Cierra la sesión y elimina el token almacenado."""
        self._fav_ids = None
        self.user_auth_token = ""
        self.user_email = ""
        self.user_display_name = ""
        self.subscription_label = ""
        self._save_config()
        log.info("Sesión de Qobuz cerrada.")

    # -- catálogo -------------------------------------------------------------

    def _catalog(self, endpoint: str, params: dict[str, Any]) -> dict | None:
        """Consulta del catálogo; deja el motivo en last_error si falla."""
        self.last_error = ""
        try:
            self.ensure_app()
            status, data = self._request(endpoint, params)
        except QobuzError as e:
            self.last_error = str(e)
            log.warning("Qobuz %s: %s", endpoint, e)
            return None
        if status == 401:
            self.last_error = i18n.t("qobuz.err.session_expired")
            return None
        if status != 200:
            self.last_error = i18n.t("qobuz.err.http", code=status, message=data.get("message", ""))
            log.warning("Qobuz %s: HTTP %s %s", endpoint, status, data.get("message", ""))
            return None
        return data

    def get_genres(self) -> list[QobuzGenre]:
        """Géneros de Qobuz, con «Todos los géneros» al principio."""
        genres = [QobuzGenre(id=0, name=i18n.t("qobuz.all_genres"), slug="all")]
        if not self.is_logged_in:
            return genres
        data = self._catalog("genre/list", {})
        items = (data or {}).get("genres", {}).get("items", [])
        if items:
            genres += [QobuzGenre(id=int(g.get("id", 0)), name=g.get("name", ""), slug=g.get("slug", ""))
                       for g in items]
        else:
            genres += FALLBACK_GENRES
        return genres

    def get_featured_albums(self, category: str = "recent", genre_id: int = 0,
                            limit: int = 24, offset: int = 0) -> list[QobuzAlbum]:
        """
        Álbumes destacados por tipo y género.
        category: 'recent' (Novedades), 'most-streamed' (Más escuchados),
                  'press-awards' (Premios), 'ideal-discography' (Esenciales).
        """
        if not self.is_logged_in:
            return []
        api_type = {"recent": "new-releases"}.get(category, category)
        data = self._catalog("album/getFeatured", {
            "type": api_type, "limit": limit, "offset": offset,
            "genre_id": genre_id if genre_id > 0 else None,
        })
        items = (data or {}).get("albums", {}).get("items", [])
        return [a for a in (self._parse_album_summary(it, genre_id) for it in items) if a]

    def get_album(self, album_id: str) -> QobuzAlbum | None:
        """Álbum completo con su lista de pistas."""
        if not self.is_logged_in or not album_id:
            return None
        data = self._catalog("album/get", {"album_id": album_id})
        if not data:
            return None
        album = self._parse_album_summary(data)
        if album:
            album.tracks = [t for t in (self._parse_track(tr, album)
                                        for tr in data.get("tracks", {}).get("items", [])) if t]
            album.booklets = parse_booklets(data.get("goodies"))
        return album

    def search_catalog(self, query: str, limit: int = 30) -> list[QobuzAlbum]:
        """Busca álbumes en el catálogo de Qobuz."""
        query = query.strip()
        if not query or not self.is_logged_in:
            return []
        data = self._catalog("catalog/search", {"query": query, "type": "albums", "limit": limit})
        items = (data or {}).get("albums", {}).get("items", [])
        return [a for a in (self._parse_album_summary(it) for it in items) if a]

    def search_artists(self, query: str, limit: int = 5) -> list[QobuzArtist]:
        """Busca artistas en el catálogo de Qobuz."""
        query = query.strip()
        if not query or not self.is_logged_in:
            return []
        data = self._catalog("catalog/search", {"query": query, "type": "artists", "limit": limit})
        items = (data or {}).get("artists", {}).get("items", [])
        return [a for a in (self._parse_artist(it) for it in items) if a]

    def get_artist(self, artist_id: int) -> QobuzArtist | None:
        """Datos de un artista (para abrir su página desde un disco o un tema)."""
        if not self.is_logged_in or not artist_id:
            return None
        data = self._catalog("artist/get", {"artist_id": artist_id})
        return self._parse_artist(data) if data else None

    # -- biblioteca del usuario ----------------------------------------------

    def _paged(self, endpoint: str, params: dict[str, Any], key: str,
               page: int = 500, max_items: int = 5000) -> list[dict] | None:
        """Todas las páginas de una lista de la API (`key` → {items, total})."""
        items: list[dict] = []
        while len(items) < max_items:
            data = self._catalog(endpoint, {**params, "limit": page, "offset": len(items)})
            if data is None:
                return items or None
            block = data.get(key) or {}
            batch = block.get("items") or []
            items += batch
            total = int(block.get("total") or 0)
            if not batch or len(items) >= total:
                break
        return items

    def get_favorite_albums(self) -> list[QobuzAlbum]:
        if not self.is_logged_in:
            return []
        items = self._paged("favorite/getUserFavorites", {"type": "albums"}, "albums") or []
        return [a for a in (self._parse_album_summary(it) for it in items) if a]

    def get_favorite_tracks(self) -> list[QobuzTrack]:
        if not self.is_logged_in:
            return []
        items = self._paged("favorite/getUserFavorites", {"type": "tracks"}, "tracks") or []
        return [t for t in (self._parse_track(it) for it in items) if t]

    def get_favorite_artists(self) -> list[QobuzArtist]:
        if not self.is_logged_in:
            return []
        items = self._paged("favorite/getUserFavorites", {"type": "artists"}, "artists") or []
        return [a for a in (self._parse_artist(it) for it in items) if a]

    def get_user_playlists(self) -> list[QobuzAlbum]:
        """Listas propias y seguidas, como contenedores sin pistas (se cargan al abrirlas)."""
        if not self.is_logged_in:
            return []
        items = self._paged("playlist/getUserPlaylists", {}, "playlists") or []
        return [pl for pl in (self._parse_playlist(it) for it in items) if pl]

    def get_playlist(self, playlist_id: str) -> QobuzAlbum | None:
        """Lista con todas sus pistas."""
        if not self.is_logged_in or not playlist_id:
            return None
        head = self._catalog("playlist/get", {"playlist_id": playlist_id, "limit": 1})
        if head is None:
            return None
        playlist = self._parse_playlist(head)
        if playlist is None:
            return None
        items = self._paged("playlist/get", {"playlist_id": playlist_id, "extra": "tracks"}, "tracks") or []
        playlist.tracks = [t for t in (self._parse_track(it, None) for it in items) if t]
        return playlist

    def load_favorite_ids(self) -> None:
        """Carga qué álbumes, temas y artistas tiene el usuario en su biblioteca (bloqueante)."""
        data = self._catalog("favorite/getUserFavoriteIds", {})
        if data is None:
            return
        self._fav_ids = {kind: {str(i) for i in (data.get(kind) or [])}
                         for kind in ("albums", "tracks", "artists")}

    def is_favorite(self, kind: str, item_id) -> bool | None:
        """True/False si se sabe; None si aún no se han cargado los favoritos."""
        if self._fav_ids is None:
            return None
        return str(item_id) in self._fav_ids.get(kind, set())

    def set_favorite(self, kind: str, item_id, add: bool) -> None:
        """Añade o quita de la biblioteca de Qobuz. kind: 'albums', 'tracks' o 'artists'."""
        if kind not in ("albums", "tracks", "artists"):
            raise ValueError(kind)
        self.ensure_app()
        endpoint = "favorite/create" if add else "favorite/delete"
        status, data = self._request(endpoint, form={f"{kind[:-1]}_ids": str(item_id)})
        if status == 401:
            raise QobuzAuthError(i18n.t("qobuz.err.session_expired"))
        if status != 200 or data.get("status") == "error":
            raise QobuzError(i18n.t("qobuz.err.http", code=status, message=data.get("message", "")))
        if self._fav_ids is not None:
            ids = self._fav_ids.setdefault(kind, set())
            (ids.add if add else ids.discard)(str(item_id))
        log.info("Qobuz: %s %s %s la biblioteca", kind[:-1], item_id, "añadido a" if add else "quitado de")

    def get_artist_releases(self, artist_id: int, release_type: str = "album") -> list[QobuzAlbum]:
        """
        Discografía de un artista por tipo, de más reciente a más antigua, como la separa Qobuz:
        'album', 'epSingle', 'live' o 'compilation'.
        """
        if not self.is_logged_in or not artist_id:
            return []
        items: list[dict] = []
        while len(items) < 500:
            data = self._catalog("artist/getReleasesList", {
                "artist_id": artist_id, "release_type": release_type, "sort": "release_date",
                "order": "desc", "track_size": 1, "limit": 100, "offset": len(items),
            })
            if data is None:
                if not items:
                    # Sin la lista por tipos: discografía completa clasificada aquí
                    return [a for a in self.get_artist_albums(artist_id)
                            if classify_release(a.release_type) == release_type]
                break
            batch = data.get("items") or []
            items += batch
            if not batch or not data.get("has_more"):
                break
        return [a for a in (self._parse_album_summary(it) for it in items) if a]

    def get_artist_albums(self, artist_id: int) -> list[QobuzAlbum]:
        """Discografía de un artista (álbumes principales primero, como en Qobuz)."""
        if not self.is_logged_in or not artist_id:
            return []
        data = self._catalog("artist/get", {"artist_id": artist_id, "extra": "albums", "limit": 200})
        items = ((data or {}).get("albums") or {}).get("items") or []
        return [a for a in (self._parse_album_summary(it) for it in items) if a]

    # -- streaming ------------------------------------------------------------

    def get_stream_info(self, track_id: int, format_id: int | None = None) -> StreamInfo:
        """URL firmada de una pista en la mejor calidad disponible hasta `format_id` (bloqueante)."""
        if not self.is_logged_in:
            raise QobuzAuthError(i18n.t("qobuz.err.session_expired"))
        fmt = format_id or self.max_format_id
        self.ensure_app()
        status, data = self._signed_file_url(track_id, fmt, self.app_secret)
        if status == 401:
            raise QobuzAuthError(i18n.t("qobuz.err.session_expired"))
        if status != 200 or not data.get("url"):
            raise QobuzError(i18n.t("qobuz.err.http", code=status, message=data.get("message", "")))
        return self.parse_stream_info(data, fmt)

    @staticmethod
    def parse_stream_info(data: dict, requested_format: int) -> StreamInfo:
        fmt = int(data.get("format_id") or requested_format)
        mime = data.get("mime_type") or ("audio/mpeg" if fmt == FORMAT_MP3 else "audio/flac")
        rate_khz = float(data.get("sampling_rate") or 44.1)
        return StreamInfo(
            url=data["url"],
            mime_type=mime,
            bit_depth=int(data.get("bit_depth") or (16 if fmt != FORMAT_MP3 else 0)),
            sample_rate=int(round(rate_khz * 1000)) if rate_khz < 1000 else int(rate_khz),
            format_id=fmt,
            is_sample=bool(data.get("sample")),
        )

    def to_audio_track(self, q_track: QobuzTrack) -> AudioTrack:
        """Pista de Qobuz como AudioTrack. La URL se obtiene justo antes de reproducirla."""
        track = AudioTrack(
            filepath="",
            filename=f"qobuz_{q_track.id}.flac",
            title=q_track.title,
            artist=q_track.artist,
            album=q_track.album_title,
            album_artist=q_track.artist,
            track_number=q_track.track_number,
            duration=q_track.duration,
            sample_rate=q_track.sample_rate,
            bits_per_sample=q_track.bit_depth,
            format_name="FLAC",
            bitrate=q_track.sample_rate * q_track.bit_depth * 2,
            cover_url=q_track.cover_url,
            is_stream=True,
        )
        track.stream_resolver = lambda: self.get_stream_info(q_track.id)
        track.stream_id = f"qobuz:{q_track.id}"
        return track

    # -- parseo ---------------------------------------------------------------

    def _parse_album_summary(self, data: dict[str, Any], default_genre_id: int = 0) -> QobuzAlbum | None:
        try:
            image = data.get("image") or {}
            artist = data.get("artist") or {}
            artist_name = artist.get("name") or "" if isinstance(artist, dict) else str(artist)
            if isinstance(artist_name, dict):  # Formato nuevo: {"display": "..."}
                artist_name = artist_name.get("display") or ""
            dates = data.get("dates") or {}
            date_str = str(data.get("release_date_original") or dates.get("original")
                           or data.get("released_at") or "")[:4]
            audio = data.get("audio_info") or {}
            rights = data.get("rights") or {}
            hires = bool(data.get("hires_streamable") or data.get("hires") or rights.get("hires_streamable"))
            bit_depth = data.get("maximum_bit_depth") or audio.get("maximum_bit_depth")
            rate = data.get("maximum_sampling_rate") or audio.get("maximum_sampling_rate")
            genre = data.get("genre") or {}
            return QobuzAlbum(
                id=str(data.get("id") or ""),
                title=data.get("title") or "",
                artist=artist_name,
                cover_url=image.get("large") or image.get("medium") or image.get("small") or "",
                release_date=date_str,
                hires=hires,
                maximum_bit_depth=int(bit_depth or (24 if hires else 16)),
                maximum_sampling_rate=float(rate or (96.0 if hires else 44.1)),
                genre_id=int(genre.get("id") or default_genre_id),
                genre_name=genre.get("name") or "",
                tracks_count=int(data.get("tracks_count") or 0),
                release_type=str(data.get("release_type") or data.get("product_type") or ""),
                artist_id=int(artist.get("id") or 0) if isinstance(artist, dict) else 0,
            )
        except (TypeError, ValueError, AttributeError) as e:
            log.debug("Error al parsear álbum de Qobuz: %s", e)
            return None

    def _parse_track(self, data: dict[str, Any], album: QobuzAlbum | None = None) -> QobuzTrack | None:
        """Pista de un álbum (`album`) o suelta (favoritos, listas: trae su propio álbum)."""
        try:
            own = data.get("album") if isinstance(data.get("album"), dict) else {}
            image = own.get("image") or {}
            album_artist = (own.get("artist") or {}).get("name") or (album.artist if album else "")
            hires = bool(data.get("hires_streamable") or data.get("hires"))
            rate_khz = float(data.get("maximum_sampling_rate") or (96.0 if hires else 44.1))
            title = data.get("title") or ""
            if data.get("version"):
                title = f"{title} ({data['version']})"
            return QobuzTrack(
                id=int(data.get("id") or 0),
                title=title,
                artist=(data.get("performer") or {}).get("name") or (data.get("artist") or {}).get("name")
                or album_artist,
                album_title=own.get("title") or (album.title if album else ""),
                duration=float(data.get("duration") or 0.0),
                track_number=int(data.get("track_number") or 1),
                hires=hires,
                bit_depth=int(data.get("maximum_bit_depth") or (24 if hires else 16)),
                sample_rate=int(round(rate_khz * 1000)),
                cover_url=image.get("large") or image.get("small") or (album.cover_url if album else ""),
                streamable=data.get("streamable", True) is not False,
                album_id=str(own.get("id") or (album.id if album and album.kind == "album" else "")),
                artist_id=int((own.get("artist") or {}).get("id") or (album.artist_id if album else 0)
                              or (data.get("performer") or {}).get("id") or 0),
            )
        except (TypeError, ValueError) as e:
            log.debug("Error al parsear pista de Qobuz: %s", e)
            return None

    def _parse_artist(self, data: dict[str, Any]) -> QobuzArtist | None:
        try:
            image = data.get("image") or {}
            picture = data.get("picture") or ""
            return QobuzArtist(
                id=int(data.get("id") or 0),
                name=data.get("name") or "",
                image_url=image.get("large") or image.get("medium") or image.get("small") or picture,
                albums_count=int(data.get("albums_count") or 0),
            )
        except (TypeError, ValueError) as e:
            log.debug("Error al parsear artista de Qobuz: %s", e)
            return None

    def _parse_playlist(self, data: dict[str, Any]) -> QobuzAlbum | None:
        try:
            images = data.get("images300") or data.get("images150") or data.get("images") or []
            cover = data.get("image_rectangle") or (images[0] if images else "")
            if isinstance(cover, list):
                cover = cover[0] if cover else ""
            owner = (data.get("owner") or {}).get("name") or ""
            return QobuzAlbum(
                id=str(data.get("id") or ""),
                title=data.get("name") or "",
                artist=owner,
                cover_url=cover or "",
                release_date="",
                hires=False,
                maximum_bit_depth=16,
                maximum_sampling_rate=44.1,
                genre_id=0,
                kind="playlist",
                tracks_count=int(data.get("tracks_count") or 0),
            )
        except (TypeError, ValueError) as e:
            log.debug("Error al parsear lista de Qobuz: %s", e)
            return None


# Instancia única compartida del cliente Qobuz
_client_instance: QobuzClient | None = None
_client_lock = threading.Lock()


def get_qobuz_client() -> QobuzClient:
    global _client_instance
    with _client_lock:
        if _client_instance is None:
            _client_instance = QobuzClient()
        return _client_instance
