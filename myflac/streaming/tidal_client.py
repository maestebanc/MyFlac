"""Cliente de TIDAL para MyFlac sobre la API oficial (https://openapi.tidal.com/v2, JSON:API).

MyFlac lleva de serie el Client ID de su app registrada en developer.tidal.com. Con OAuth 2.1 y PKCE
el Client ID es público (no hay secreto en el código): el usuario solo inicia sesión en la web de
TIDAL y MyFlac recibe la respuesta en la dirección local registrada en la app. En ~/.config/myflac/
tidal.json se puede indicar otra app propia (client_id y redirect_uri).

Los datos usan los mismos modelos que Qobuz (álbumes, temas, artistas, listas) para que la vista
de streaming sea la misma. Todas las llamadas son bloqueantes: la interfaz las hace desde hilos.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from .. import i18n
from ..audio.track import AudioTrack
from ..logger import get_logger
from .qobuz_client import QobuzAlbum, QobuzArtist, QobuzError, QobuzGenre, QobuzTrack, StreamInfo

log = get_logger("streaming.tidal")

API_BASE_URL = "https://openapi.tidal.com/v2"
AUTHORIZE_URL = "https://login.tidal.com/authorize"
TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"
CONFIG_PATH = Path.home() / ".config" / "myflac" / "tidal.json"
DEFAULT_REDIRECT_URI = "http://localhost:8723/callback"
# App «MyFlac» en developer.tidal.com (cliente público con PKCE: el Client ID no es secreto)
DEFAULT_CLIENT_ID = "Y9SIZKBRGVjMFGJ4"
SCOPES = ("user.read collection.read collection.write playlists.read search.read "
          "recommendations.read playback entitlements.read")
USER_AGENT = "MyFlac"
_BATCH = 20  # Identificadores por petición al pedir detalles (filter[id])
_MIN_REQUEST_INTERVAL_S = 0.35  # Separación mínima entre peticiones
_RATE_LIMIT_RETRIES = 4
_MAX_ITEMS = 2000

# Pestañas de la discografía (TIDAL solo distingue álbum, EP y single)
TIDAL_RELEASE_TYPES = ("album", "epSingle")

# Exploración: mezclas personales de TIDAL (álbumes de sus temas, sin repetir)
EXPLORE_MIXES = {
    "new-releases": "userNewReleaseMixes",
    "discovery": "userDiscoveryMixes",
    "daily": "userDailyMixes",
}


class TidalError(QobuzError):
    """Error comprensible para el usuario (ya traducido)."""


class TidalAuthError(TidalError):
    """Sesión no válida o caducada."""


# ---------------------------------------------------------------------------
# Utilidades de formato
# ---------------------------------------------------------------------------

def parse_iso_duration(text: str | None) -> float:
    """ISO 8601 (PT1H2M3.5S) → segundos."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?", text or "")
    if not m:
        return 0.0
    d, h, mi, s = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge S256) para OAuth 2.1 con PKCE."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def best_image(files: list[dict] | None, target: int = 640) -> str:
    """De los tamaños de una ilustración, el más cercano por encima de `target` (o el mayor)."""
    files = [f for f in files or [] if isinstance(f, dict) and f.get("href")]
    if not files:
        return ""
    def width(f):
        return int((f.get("meta") or {}).get("width") or 0)
    bigger = sorted((f for f in files if width(f) >= target), key=width)
    return (bigger[0] if bigger else max(files, key=width))["href"]


def _retry_after(header: str | None, attempt: int) -> float:
    """Segundos de espera tras un 429: los que diga TIDAL o 1, 2, 4, 8..."""
    try:
        return min(30.0, max(0.5, float(header)))
    except (TypeError, ValueError):
        return float(2 ** attempt)


def parse_dash_sample_rate(mpd: str) -> int:
    m = re.search(r'audioSamplingRate="(\d+)"', mpd or "")
    return int(m.group(1)) if m else 0


class Document:
    """Respuesta JSON:API: recursos principales y los incluidos, por (tipo, id)."""

    def __init__(self, body: dict):
        data = body.get("data")
        self.data: list[dict] = data if isinstance(data, list) else ([data] if data else [])
        self.included: dict[tuple[str, str], dict] = {
            (r.get("type"), str(r.get("id"))): r for r in body.get("included") or [] if isinstance(r, dict)}
        for r in self.data:
            if r.get("attributes") is not None:
                self.included.setdefault((r.get("type"), str(r.get("id"))), r)
        self.next = ((body.get("links") or {}).get("next")) or ""

    def get(self, ref: dict | None) -> dict | None:
        if not ref:
            return None
        return self.included.get((ref.get("type"), str(ref.get("id"))))

    def related(self, resource: dict, name: str) -> list[dict]:
        rel = ((resource.get("relationships") or {}).get(name) or {}).get("data") or []
        refs = rel if isinstance(rel, list) else [rel]
        return [r for r in (self.get(ref) for ref in refs) if r]


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

@dataclass
class _Tokens:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0


class TidalClient:
    """Cliente de la API oficial de TIDAL con la misma interfaz que el de Qobuz."""

    service = "tidal"
    release_types = TIDAL_RELEASE_TYPES
    server_side_genres = False  # La API no permite listar el catálogo por género

    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self.client_id = DEFAULT_CLIENT_ID
        self.client_secret = ""
        self.redirect_uri = DEFAULT_REDIRECT_URI
        self._tokens = _Tokens()
        self.user_id = ""
        self.user_email = ""
        self.user_display_name = ""
        self.subscription_label = ""
        self.country = "US"
        self.last_error = ""
        self._lock = threading.RLock()
        self._fav_ids: dict[str, set[str]] | None = None
        self._throttle_lock = threading.Lock()
        self._next_request_at = 0.0
        # Detalles ya pedidos (álbumes, artistas...): evita repetir peticiones y el límite de TIDAL
        self._cache: dict[tuple[str, str], tuple[dict, Document]] = {}
        self._load_config()

    # -- configuración --------------------------------------------------------

    @property
    def is_logged_in(self) -> bool:
        return bool(self._tokens.refresh_token or self._tokens.access_token)

    @property
    def has_app_credentials(self) -> bool:
        return bool(self.client_id)

    def _load_config(self) -> None:
        try:
            if self.config_path.is_file():
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.client_id = data.get("client_id") or DEFAULT_CLIENT_ID
                self.client_secret = data.get("client_secret", "")
                self.redirect_uri = data.get("redirect_uri") or DEFAULT_REDIRECT_URI
                self._tokens = _Tokens(data.get("access_token", ""), data.get("refresh_token", ""),
                                       float(data.get("expires_at", 0)))
                self.user_id = str(data.get("user_id", ""))
                self.user_email = data.get("user_email", "")
                self.user_display_name = data.get("user_display_name", "")
                self.country = data.get("country") or "US"
                try:
                    os.chmod(self.config_path, 0o600)
                except OSError:
                    pass
        except Exception as e:
            log.warning("No se pudo leer la configuración de TIDAL: %s", e)

    def _save_config(self) -> None:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "access_token": self._tokens.access_token,
            "refresh_token": self._tokens.refresh_token,
            "expires_at": self._tokens.expires_at,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "user_display_name": self.user_display_name,
            "country": self.country,
        }
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.chmod(self.config_path, 0o600)
        except OSError as e:
            log.error("Error al guardar configuración de TIDAL: %s", e)

    def set_app_credentials(self, client_id: str, client_secret: str = "", redirect_uri: str = "") -> None:
        self.client_id, self.client_secret = client_id.strip() or DEFAULT_CLIENT_ID, client_secret.strip()
        self.redirect_uri = redirect_uri.strip() or DEFAULT_REDIRECT_URI
        self._save_config()

    def ensure_app(self) -> None:
        if not self.has_app_credentials:
            raise TidalError(i18n.t("tidal.err.app_credentials", path=self.config_path))

    # -- OAuth 2.1 con PKCE ---------------------------------------------------

    def authorization_url(self, challenge: str, state: str) -> str:
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        })

    def login_interactive(self, open_url: Callable[[str], None], timeout: float = 300) -> None:
        """
        Inicio de sesión completo (bloqueante): abre la web de TIDAL con `open_url`, espera la
        respuesta en la dirección de retorno local y obtiene los tokens.
        """
        self.ensure_app()
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(16)
        target = urllib.parse.urlparse(self.redirect_uri)
        if target.hostname not in ("localhost", "127.0.0.1") or not target.port:
            raise TidalError(i18n.t("tidal.err.redirect_uri", uri=self.redirect_uri))
        result: dict[str, str] = {}
        page = i18n.t("tidal.dialog.browser_done")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path != (target.path or "/"):
                    self.send_error(404)
                    return
                q = urllib.parse.parse_qs(url.query)
                result.update({k: v[0] for k, v in q.items()})
                body = f"<html><meta charset='utf-8'><body style='font-family:sans-serif'>" \
                       f"<h2>MyFlac</h2><p>{page}</p></body></html>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            server = HTTPServer((target.hostname, target.port), Handler)
        except OSError as e:
            raise TidalError(i18n.t("tidal.err.port_busy", port=target.port, error=e)) from e
        server.timeout = 1.0
        try:
            open_url(self.authorization_url(challenge, state))
            deadline = time.monotonic() + timeout
            while not result and time.monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        if not result:
            raise TidalError(i18n.t("tidal.err.login_timeout"))
        if result.get("state") != state:
            raise TidalError(i18n.t("tidal.err.login_failed", error="state"))
        if "error" in result:
            raise TidalAuthError(i18n.t("tidal.err.login_failed",
                                        error=result.get("error_description") or result["error"]))
        self._token_request({
            "grant_type": "authorization_code",
            "code": result.get("code", ""),
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        })
        self._load_profile()

    def _token_request(self, form: dict[str, str]) -> None:
        form = {**form, "client_id": self.client_id}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            if form["grant_type"] == "refresh_token":
                self._tokens = _Tokens()
                self._save_config()
                raise TidalAuthError(i18n.t("tidal.err.session_expired")) from e
            raise TidalAuthError(i18n.t("tidal.err.login_failed",
                                        error=body.get("error_description") or body.get("error") or e.code)) from e
        except (OSError, ValueError) as e:
            raise TidalError(i18n.t("tidal.err.network", error=e)) from e
        self._tokens = _Tokens(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token") or self._tokens.refresh_token,
            expires_at=time.time() + float(data.get("expires_in") or 3600) - 60,
        )
        if data.get("user_id"):
            self.user_id = str(data["user_id"])
        self._save_config()

    def _access_token(self) -> str:
        with self._lock:
            if self._tokens.access_token and time.time() < self._tokens.expires_at:
                return self._tokens.access_token
            if not self._tokens.refresh_token:
                raise TidalAuthError(i18n.t("tidal.err.session_expired"))
            self._token_request({"grant_type": "refresh_token", "refresh_token": self._tokens.refresh_token})
            return self._tokens.access_token

    def _load_profile(self) -> None:
        doc = self._get("users/me")
        user = doc.data[0] if doc.data else {}
        attrs = user.get("attributes") or {}
        self.user_id = str(user.get("id") or self.user_id)
        self.user_email = attrs.get("email") or self.user_email
        name = " ".join(x for x in (attrs.get("firstName"), attrs.get("lastName")) if x)
        self.user_display_name = attrs.get("username") or name or self.user_email
        self.country = attrs.get("country") or self.country
        self._save_config()
        log.info("Sesión de TIDAL iniciada: %s (%s)", self.user_display_name, self.country)

    def logout(self) -> None:
        self._tokens = _Tokens()
        self.user_id = self.user_email = self.user_display_name = ""
        self._fav_ids = None
        self._save_config()
        log.info("Sesión de TIDAL cerrada.")

    # -- HTTP -----------------------------------------------------------------

    def _http(self, method: str, path: str, params: dict[str, Any] | None = None,
              body: dict | None = None) -> tuple[int, dict]:
        self.ensure_app()
        if path.startswith("/"):
            path = path[1:]
        url = path if path.startswith("http") else f"{API_BASE_URL}/{path}"
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, "", [])}
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
        headers = {"Authorization": f"Bearer {self._access_token()}", "User-Agent": USER_AGENT,
                   "Accept": "application/vnd.api+json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/vnd.api+json"
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            self._throttle()
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read()
                    return resp.status, json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < _RATE_LIMIT_RETRIES:
                    # Límite de peticiones de TIDAL: se espera lo que indique y se reintenta
                    wait = _retry_after(e.headers.get("Retry-After"), attempt)
                    log.info("TIDAL: límite de peticiones, reintento en %.1f s", wait)
                    with self._throttle_lock:
                        self._next_request_at = max(self._next_request_at, time.monotonic() + wait)
                    continue
                try:
                    parsed = json.loads(e.read() or b"{}")
                except ValueError:
                    parsed = {}
                return e.code, parsed
            except (OSError, ValueError) as e:
                raise TidalError(i18n.t("tidal.err.network", error=e)) from e
        return 429, {}

    def _throttle(self):
        """Espacia las peticiones (las apps de TIDAL tienen un límite de peticiones por segundo)."""
        with self._throttle_lock:
            now = time.monotonic()
            wait = self._next_request_at - now
            self._next_request_at = max(now, self._next_request_at) + _MIN_REQUEST_INTERVAL_S
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _error_text(body: dict) -> str:
        errors = body.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return errors[0].get("detail") or errors[0].get("title") or ""
        return body.get("message", "")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Document:
        status, body = self._http("GET", path, params)
        if status == 401:
            raise TidalAuthError(i18n.t("tidal.err.session_expired"))
        if status >= 400:
            raise TidalError(i18n.t("tidal.err.http", code=status, message=self._error_text(body)))
        return Document(body)

    def _catalog(self, fn: Callable[[], Any], default):
        """Ejecuta una consulta del catálogo y deja el motivo en last_error si falla."""
        self.last_error = ""
        try:
            return fn()
        except QobuzError as e:
            self.last_error = str(e)
            log.warning("TIDAL: %s", e)
            return default

    def _relationship_ids(self, path: str, params: dict[str, Any] | None = None,
                          limit: int = _MAX_ITEMS) -> list[dict]:
        """Identificadores (con su `meta`) de una relación, siguiendo todas las páginas."""
        refs: list[dict] = []
        doc = self._get(path, params)
        while True:
            refs += doc.data
            if not doc.next or len(refs) >= limit:
                break
            doc = self._get(doc.next)
        return refs[:limit]

    def _hydrate(self, kind: str, ids: list[str], include: list[str]) -> Document:
        """Detalles de muchos recursos a la vez (por lotes, con caché) en un solo Document."""
        merged = Document({})
        missing = []
        for i in dict.fromkeys(ids):
            cached = self._cache.get((kind, i))
            if cached:
                merged.data.append(cached[0])
                merged.included.update(cached[1].included)
            else:
                missing.append(i)
        for i in range(0, len(missing), _BATCH):
            doc = self._get(kind, {"filter[id]": missing[i:i + _BATCH], "include": include,
                                   "countryCode": self.country})
            merged.data += doc.data
            merged.included.update(doc.included)
            for res in doc.data:
                self._cache[(kind, str(res.get("id")))] = (res, doc)
        return merged

    # -- conversión a modelos ---------------------------------------------------

    def _album(self, doc: Document, res: dict) -> QobuzAlbum:
        a = res.get("attributes") or {}
        artists = doc.related(res, "artists")
        genres = doc.related(res, "genres")
        cover = doc.related(res, "coverArt")
        tags = set(a.get("mediaTags") or [])
        hires = "HIRES_LOSSLESS" in tags
        title = a.get("title") or ""
        if a.get("version"):
            title = f"{title} ({a['version']})"
        return QobuzAlbum(
            id=str(res.get("id")),
            title=title,
            artist=", ".join((x.get("attributes") or {}).get("name", "") for x in artists[:2]),
            cover_url=best_image((cover[0].get("attributes") or {}).get("files")) if cover else "",
            release_date=str(a.get("releaseDate") or "")[:4],
            hires=hires,
            maximum_bit_depth=24 if hires else 16,
            maximum_sampling_rate=0.0 if hires else 44.1,  # TIDAL no dice la frecuencia exacta del Hi-Res
            genre_id=0,
            genre_name=", ".join((g.get("attributes") or {}).get("genreName", "").title() for g in genres[:2]),
            tracks_count=int(a.get("numberOfItems") or 0),
            release_type=str(a.get("albumType") or a.get("type") or "ALBUM").lower(),
            artist_id=int(artists[0]["id"]) if artists and str(artists[0].get("id", "")).isdigit() else 0,
        )

    def _track(self, doc: Document, res: dict, album: QobuzAlbum | None = None,
               number: int = 0) -> QobuzTrack | None:
        a = res.get("attributes") or {}
        if not str(res.get("id", "")).isdigit():
            return None
        artists = doc.related(res, "artists")
        albums = doc.related(res, "albums")
        own = self._album(doc, albums[0]) if albums else album
        hires = "HIRES_LOSSLESS" in set(a.get("mediaTags") or [])
        title = a.get("title") or ""
        if a.get("version"):
            title = f"{title} ({a['version']})"
        availability = a.get("availability")
        return QobuzTrack(
            id=int(res["id"]),
            title=title,
            artist=", ".join((x.get("attributes") or {}).get("name", "") for x in artists[:2])
            or (own.artist if own else ""),
            album_title=own.title if own else "",
            duration=parse_iso_duration(a.get("duration")),
            track_number=number or 1,
            hires=hires,
            bit_depth=24 if hires else 16,
            sample_rate=0 if hires else 44100,  # Hi-Res sin frecuencia exacta: la real llega con el manifiesto
            cover_url=own.cover_url if own else "",
            streamable=availability is None or "STREAM" in availability,
            album_id=own.id if own else "",
            artist_id=int(artists[0]["id"]) if artists and str(artists[0].get("id", "")).isdigit()
            else (own.artist_id if own else 0),
        )

    def _artist(self, doc: Document, res: dict) -> QobuzArtist:
        a = res.get("attributes") or {}
        art = doc.related(res, "profileArt")
        return QobuzArtist(
            id=int(res["id"]) if str(res.get("id", "")).isdigit() else 0,
            name=a.get("name") or "",
            image_url=best_image((art[0].get("attributes") or {}).get("files"), 320) if art else "",
        )

    def _playlist(self, doc: Document, res: dict) -> QobuzAlbum:
        a = res.get("attributes") or {}
        cover = doc.related(res, "coverArt")
        return QobuzAlbum(
            id=str(res.get("id")), title=a.get("name") or "", artist=a.get("description", "")[:60] or "",
            cover_url=best_image((cover[0].get("attributes") or {}).get("files")) if cover else "",
            release_date="", hires=False, maximum_bit_depth=16, maximum_sampling_rate=44.1, genre_id=0,
            kind="playlist", tracks_count=int(a.get("numberOfTrackItems") or a.get("numberOfItems") or 0),
        )

    def _albums_by_ids(self, ids: list[str]) -> list[QobuzAlbum]:
        doc = self._hydrate("albums", ids, ["artists", "coverArt", "genres"])
        by_id = {str(r.get("id")): self._album(doc, r) for r in doc.data}
        return [by_id[i] for i in ids if i in by_id]

    def _tracks_by_ids(self, ids: list[str], numbers: dict[str, int] | None = None) -> list[QobuzTrack]:
        doc = self._hydrate("tracks", ids, ["albums", "artists"])
        # Las portadas son del álbum: segunda tanda con coverArt
        album_ids = sorted({str(ref["id"]) for r in doc.data
                            for ref in ((r.get("relationships") or {}).get("albums") or {}).get("data") or []})
        if album_ids:
            covers = self._hydrate("albums", album_ids, ["coverArt", "artists"])
            doc.included.update(covers.included)
            for r in covers.data:
                doc.included[(r.get("type"), str(r.get("id")))] = r
        out = {}
        for r in doc.data:
            t = self._track(doc, r, number=(numbers or {}).get(str(r.get("id")), 0))
            if t:
                out[str(t.id)] = t
        return [out[i] for i in ids if i in out]

    # -- catálogo (misma interfaz que QobuzClient) ------------------------------

    def get_genres(self) -> list[QobuzGenre]:
        return [QobuzGenre(id=0, name=i18n.t("qobuz.all_genres"), slug="all")]

    def get_featured_albums(self, category: str = "new-releases", genre_id: int = 0,
                            limit: int = 30, offset: int = 0) -> list[QobuzAlbum]:
        """
        Exploración con las mezclas personales de TIDAL. Cada mezcla es una lista: en «Novedades» y
        «Descubrimiento» se muestran los discos de sus temas; en «Mezclas diarias», las mezclas.
        """
        if not self.is_logged_in:
            return []
        resource = EXPLORE_MIXES.get(category, "userNewReleaseMixes")

        def run():
            refs = self._relationship_ids(f"{resource}/me/relationships/items", {"locale": self._locale()},
                                          limit=12)
            mix_ids = [str(r["id"]) for r in refs if r.get("type") == "playlists"]
            if category == "daily":
                doc = self._hydrate("playlists", mix_ids, ["coverArt"])
                by_id = {str(r["id"]): self._playlist(doc, r) for r in doc.data}
                return [by_id[i] for i in mix_ids if i in by_id]
            track_ids = [str(r["id"]) for r in refs if r.get("type") == "tracks"]
            for mix in mix_ids[:3]:
                items = self._relationship_ids(f"playlists/{mix}/relationships/items",
                                               {"countryCode": self.country}, limit=60)
                track_ids += [str(r["id"]) for r in items if r.get("type") == "tracks"]
            tracks = self._tracks_by_ids(list(dict.fromkeys(track_ids)))
            seen: list[str] = []
            for t in tracks:
                if t.album_id and t.album_id not in seen:
                    seen.append(t.album_id)
            return self._albums_by_ids(seen[:limit])

        return self._catalog(run, [])

    def get_album(self, album_id: str) -> QobuzAlbum | None:
        if not self.is_logged_in or not album_id:
            return None

        def run():
            (album,) = self._albums_by_ids([str(album_id)]) or (None,)
            if album is None:
                return None
            refs = self._relationship_ids(f"albums/{album_id}/relationships/items",
                                          {"countryCode": self.country})
            ids = [str(r["id"]) for r in refs if r.get("type") == "tracks"]
            numbers = {str(r["id"]): int((r.get("meta") or {}).get("trackNumber") or 0) for r in refs}
            album.tracks = self._tracks_by_ids(ids, numbers)
            return album

        return self._catalog(run, None)

    def _search(self, query: str, kind: str):
        doc = self._get("searchResults", {"filter[query]": query, "include": [kind],
                                          "countryCode": self.country})
        if not doc.data:
            return []
        return [str(r["id"]) for r in doc.related(doc.data[0], kind)] or [
            str(ref["id"]) for ref in ((doc.data[0].get("relationships") or {}).get(kind) or {}).get("data") or []]

    def search_catalog(self, query: str, limit: int = 30) -> list[QobuzAlbum]:
        query = query.strip()
        if not query or not self.is_logged_in:
            return []
        return self._catalog(lambda: self._albums_by_ids(self._search(query, "albums")[:limit]), [])

    def search_artists(self, query: str, limit: int = 5) -> list[QobuzArtist]:
        query = query.strip()
        if not query or not self.is_logged_in:
            return []

        def run():
            ids = self._search(query, "artists")[:limit]
            doc = self._hydrate("artists", ids, ["profileArt"])
            by_id = {str(r["id"]): self._artist(doc, r) for r in doc.data}
            return [by_id[i] for i in ids if i in by_id]

        return self._catalog(run, [])

    def get_artist(self, artist_id: int) -> QobuzArtist | None:
        if not self.is_logged_in or not artist_id:
            return None

        def run():
            doc = self._hydrate("artists", [str(artist_id)], ["profileArt"])
            return self._artist(doc, doc.data[0]) if doc.data else None

        return self._catalog(run, None)

    def get_artist_releases(self, artist_id: int, release_type: str = "album") -> list[QobuzAlbum]:
        """Discografía por tipo: 'album' (álbumes) o 'epSingle' (EPs y singles), de más nueva a más antigua."""
        if not self.is_logged_in or not artist_id:
            return []

        def run():
            refs = self._relationship_ids(f"artists/{artist_id}/relationships/albums",
                                          {"countryCode": self.country}, limit=500)
            albums = self._albums_by_ids([str(r["id"]) for r in refs])
            wanted = {"album": ("album",), "epSingle": ("ep", "single")}.get(release_type, ("album",))
            albums = [a for a in albums if a.release_type in wanted]
            return sorted(albums, key=lambda a: a.release_date, reverse=True)

        return self._catalog(run, [])

    # -- biblioteca -----------------------------------------------------------

    def _collection_ids(self, kind: str) -> list[str]:
        resource = {"albums": "userCollectionAlbums", "tracks": "userCollectionTracks",
                    "artists": "userCollectionArtists", "playlists": "userCollectionPlaylists"}[kind]
        refs = self._relationship_ids(f"{resource}/me/relationships/items", {"sort": "-addedAt"})
        return [str(r["id"]) for r in refs]

    def get_favorite_albums(self) -> list[QobuzAlbum]:
        if not self.is_logged_in:
            return []
        return self._catalog(lambda: self._albums_by_ids(self._collection_ids("albums")), [])

    def get_favorite_tracks(self) -> list[QobuzTrack]:
        if not self.is_logged_in:
            return []
        return self._catalog(lambda: self._tracks_by_ids(self._collection_ids("tracks")), [])

    def get_favorite_artists(self) -> list[QobuzArtist]:
        if not self.is_logged_in:
            return []

        def run():
            ids = self._collection_ids("artists")
            doc = self._hydrate("artists", ids, ["profileArt"])
            by_id = {str(r["id"]): self._artist(doc, r) for r in doc.data}
            return [by_id[i] for i in ids if i in by_id]

        return self._catalog(run, [])

    def get_user_playlists(self) -> list[QobuzAlbum]:
        if not self.is_logged_in:
            return []

        def run():
            ids = self._collection_ids("playlists")
            doc = self._hydrate("playlists", ids, ["coverArt"])
            by_id = {str(r["id"]): self._playlist(doc, r) for r in doc.data}
            return [by_id[i] for i in ids if i in by_id]

        return self._catalog(run, [])

    def get_playlist(self, playlist_id: str) -> QobuzAlbum | None:
        if not self.is_logged_in or not playlist_id:
            return None

        def run():
            doc = self._hydrate("playlists", [playlist_id], ["coverArt"])
            if not doc.data:
                return None
            playlist = self._playlist(doc, doc.data[0])
            refs = self._relationship_ids(f"playlists/{playlist_id}/relationships/items",
                                          {"countryCode": self.country})
            playlist.tracks = self._tracks_by_ids([str(r["id"]) for r in refs if r.get("type") == "tracks"])
            return playlist

        return self._catalog(run, None)

    def load_favorite_ids(self) -> None:
        def run():
            self._fav_ids = {k: set(self._collection_ids(k)) for k in ("albums", "tracks", "artists")}
        self._catalog(run, None)

    def is_favorite(self, kind: str, item_id) -> bool | None:
        if self._fav_ids is None:
            return None
        return str(item_id) in self._fav_ids.get(kind, set())

    def set_favorite(self, kind: str, item_id, add: bool) -> None:
        resource = {"albums": "userCollectionAlbums", "tracks": "userCollectionTracks",
                    "artists": "userCollectionArtists"}[kind]
        body = {"data": [{"id": str(item_id), "type": kind}]}
        status, resp = self._http("POST" if add else "DELETE", f"{resource}/me/relationships/items", body=body)
        if status == 401:
            raise TidalAuthError(i18n.t("tidal.err.session_expired"))
        if status >= 400 and status != 409:  # 409: ya estaba
            raise TidalError(i18n.t("tidal.err.http", code=status, message=self._error_text(resp)))
        if self._fav_ids is not None:
            ids = self._fav_ids.setdefault(kind, set())
            (ids.add if add else ids.discard)(str(item_id))

    # -- reproducción ---------------------------------------------------------

    def get_stream_info(self, track_id: int) -> StreamInfo:
        """Manifiesto MPEG-DASH de la pista en FLAC (Hi-Res si existe). Falla si viene con DRM."""
        if not self.is_logged_in:
            raise TidalAuthError(i18n.t("tidal.err.session_expired"))
        doc = self._get(f"trackManifests/{track_id}", {
            "manifestType": "MPEG_DASH", "formats": ["FLAC_HIRES", "FLAC"], "uriScheme": "HTTPS",
            "usage": "PLAYBACK", "adaptive": "false",
        })
        attrs = (doc.data[0].get("attributes") if doc.data else None) or {}
        if attrs.get("trackPresentation") == "PREVIEW":
            log.warning("TIDAL da solo un fragmento de la pista %s (motivo: %s)", track_id,
                        attrs.get("previewReason") or "sin indicar")
        if attrs.get("drmData"):
            raise TidalError(i18n.t("tidal.err.drm"))
        uri = attrs.get("uri") or ""
        if not uri:
            raise TidalError(i18n.t("tidal.err.http", code=200, message="manifest"))
        formats = set(attrs.get("formats") or [])
        rate = 0
        try:
            req = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                rate = parse_dash_sample_rate(resp.read(65536).decode("utf-8", "ignore"))
        except (OSError, ValueError) as e:
            log.debug("No se pudo leer el manifiesto DASH: %s", e)
        hires = "FLAC_HIRES" in formats
        return StreamInfo(
            url=uri, mime_type="application/dash+xml", bit_depth=24 if hires else 16,
            sample_rate=rate or (96000 if hires else 44100),
            format_id=27 if hires else 6, is_sample=attrs.get("trackPresentation") == "PREVIEW",
            preview_reason=attrs.get("previewReason") or "",
        )

    def to_audio_track(self, q_track: QobuzTrack) -> AudioTrack:
        track = AudioTrack(
            filepath="", filename=f"tidal_{q_track.id}.flac", title=q_track.title, artist=q_track.artist,
            album=q_track.album_title, album_artist=q_track.artist, track_number=q_track.track_number,
            duration=q_track.duration, sample_rate=q_track.sample_rate, bits_per_sample=q_track.bit_depth,
            format_name="FLAC", bitrate=q_track.sample_rate * q_track.bit_depth * 2,
            cover_url=q_track.cover_url, is_stream=True,
        )
        track.stream_resolver = lambda: self.get_stream_info(q_track.id)
        track.stream_id = f"tidal:{q_track.id}"
        return track

    def _locale(self) -> str:
        lang = i18n.get_language()
        return {"es": "es-ES", "ca": "ca-ES"}.get(lang, "en-US")


_client_instance: TidalClient | None = None
_client_lock = threading.Lock()


def get_tidal_client() -> TidalClient:
    global _client_instance
    with _client_lock:
        if _client_instance is None:
            _client_instance = TidalClient()
        return _client_instance
