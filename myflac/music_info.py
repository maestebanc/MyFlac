"""
Fichas "Tema", "Disco" y "Artista" del inspector a partir de fuentes reales:
- Wikipedia: entradilla con formato, descripción corta e imagen del artículo (en el idioma de la
  aplicación y, si no existe, en inglés).
- Discogs: año, sello, país, formato, géneros, estilos, créditos, notas de la edición y perfil del artista.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Callable

from gi.repository import GLib

from . import discogs, i18n, translate
from .audio.track import AudioTrack
from .logger import get_logger

log = get_logger("music_info")

# Wikimedia exige un User-Agent que identifique la aplicación y cómo contactar/consultarla
USER_AGENT = "MyFlac/0.1.0 (https://github.com/maestebanc/MyFlac; reproductor de música para GNOME)"
# Wikipedia limita las ráfagas de peticiones anónimas: se hacen de una en una y espaciadas
WIKIPEDIA_MIN_INTERVAL = 0.5
_wikipedia_lock = threading.Lock()
_wikipedia_last = [0.0]

# Versión del formato de las fichas: cambiarla invalida las guardadas
INFO_VERSION = 3
KINDS = ("track", "album", "artist")
# Una ficha sin información se vuelve a buscar pasado este tiempo (las fuentes crecen)
EMPTY_TTL = 14 * 24 * 3600
# Longitud máxima de textos largos de Discogs (perfil, notas de la edición)
MAX_DISCOGS_TEXT = 1500


class WikipediaRateLimited(Exception):
    """Wikipedia pidió esperar: no se guarda en caché y se reintenta más tarde."""


# Títulos candidatos de Wikipedia por idioma y tipo de ficha
_WIKI_PATTERNS = {
    "es": {
        "track": ["{title} (canción de {artist})", "{title} (canción)", "{title} (sencillo)", "{title}"],
        "album": ["{album} (álbum de {artist})", "{album} (álbum)", "{album}"],
        "artist": ["{artist} (banda)", "{artist} (grupo musical)", "{artist} (músico)", "{artist} (cantante)", "{artist}"],
    },
    "ca": {
        "track": ["{title} (cançó de {artist})", "{title} (cançó)", "{title} (senzill)", "{title}"],
        "album": ["{album} (àlbum de {artist})", "{album} (àlbum)", "{album}"],
        "artist": ["{artist} (grup)", "{artist} (grup musical)", "{artist} (músic)", "{artist} (cantant)", "{artist}"],
    },
    "en": {
        "track": ["{title} ({artist} song)", "{title} (song)", "{title}"],
        "album": ["{album} ({artist} album)", "{album} (album)", "{album}"],
        "artist": ["{artist} (band)", "{artist} (musician)", "{artist} (singer)", "{artist} (rapper)", "{artist}"],
    },
}

# Palabras que confirman que la página es del tipo buscado (en cualquiera de los tres idiomas)
_KIND_KEYWORDS = {
    "track": r"canci[oó]n|cançó|sencillo|senzill|single|song|tema",
    "album": r"[aáà]lbum|disco|recopilat",
    "artist": r"banda|grupo|grup|m[uú]sic|cantant|singer|band|musician|compositor|composer|rapper|dj|productor|producer|duo|dúo|orquesta|orchestra",
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in decomposed if not unicodedata.combining(c)).lower())


def _clean_album(album: str) -> str:
    """Quita coletillas de edición: '(2011 Remaster)', '[Deluxe]', 'CDP 7 46271 2'..."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*", " ", album or "").strip()


def _clean_title(title: str) -> str:
    title = re.sub(r"\s*[\(\[][^\)\]]*(remaster|live|mix|version|edit|feat|mono|stereo)[^\)\]]*[\)\]]", "", title or "", flags=re.I)
    return re.sub(r"\s+-\s+.*(remaster|live|version).*$", "", title, flags=re.I).strip()


class _PangoFromHTML(HTMLParser):
    """Convierte el HTML de la entradilla de Wikipedia en marcado Pango (párrafos, negrita, cursiva)."""

    _INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i", "sub": "sub", "sup": "sup"}
    # Contenido que no se muestra: referencias, estilos, tablas y fragmentos marcados como no extraíbles
    _SKIP = {"style", "script", "table", "figure"}
    _VOID = {"br", "img", "hr", "wbr", "meta", "link", "input", "source", "col", "area"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._stack: list[tuple[str, str | None, bool]] = []  # (etiqueta, pango, omitida)
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID:
            if tag == "br" and not self._skip:
                self.out.append("\n")
            return
        classes = dict(attrs).get("class") or ""
        skipped = tag in self._SKIP or "reference" in classes or "noexcerpt" in classes
        pango = None if (skipped or self._skip) else self._INLINE.get(tag)
        if skipped:
            self._skip += 1
        elif not self._skip:
            if pango:
                self.out.append(f"<{pango}>")
            elif tag in ("p", "div") and self.out and not self.out[-1].endswith("\n\n"):
                self.out.append("\n\n")
            elif tag == "li":
                self.out.append("\n• ")
        self._stack.append((tag, pango, skipped))

    def handle_endtag(self, tag):
        if not any(t == tag for t, _, _ in self._stack):
            return  # cierre sin apertura: se ignora
        while self._stack:
            open_tag, pango, skipped = self._stack.pop()
            if skipped:
                self._skip -= 1
            elif pango:
                self.out.append(f"</{pango}>")
            if open_tag == tag:
                break

    def handle_data(self, data):
        if not self._skip:
            self.out.append(GLib.markup_escape_text(data.replace("\u200b", "")))

    def close(self):
        super().close()
        while self._stack:  # etiquetas sin cerrar al final del fragmento
            _tag, pango, skipped = self._stack.pop()
            if pango and not skipped:
                self.out.append(f"</{pango}>")


def html_to_markup(fragment: str) -> str:
    """HTML de la entradilla de Wikipedia -> marcado Pango para un Gtk.Label."""
    parser = _PangoFromHTML()
    parser.feed(fragment or "")
    parser.close()
    markup = "".join(parser.out)
    markup = re.sub(r"[ \t]*\n[ \t]*", "\n", markup)
    markup = re.sub(r"\n{3,}", "\n\n", markup)
    return markup.strip()


def markup_to_text(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


@dataclass
class WikiPage:
    title: str
    description: str
    markup: str  # Entradilla con formato (marcado Pango)
    url: str
    image_url: str = ""

    @property
    def text(self) -> str:
        return markup_to_text(self.markup)


@dataclass
class InfoCard:
    """Ficha lista para mostrar."""
    title: str = ""
    description: str = ""
    image_path: str = ""  # Imagen del artículo de Wikipedia, ya descargada en la caché
    markup: str = ""  # Entradilla de Wikipedia con formato (marcado Pango)
    facts: list[tuple[str, str]] = field(default_factory=list)  # (dato, valor en marcado Pango)
    sections: list[tuple[str, str]] = field(default_factory=list)  # (título, texto en marcado Pango)
    sources: list[str] = field(default_factory=list)  # URLs de las fuentes
    translated_by: str = ""  # Servicio de traducción automática usado para textos en inglés
    temporary: bool = False  # Incompleta por un fallo temporal: no se guarda en caché
    status: str = "ok"  # 'ok' | 'empty' | 'error'
    error: str = ""
    created: float = 0.0


def _esc(text) -> str:
    return GLib.markup_escape_text(str(text))


def _credits_markup(credits: list[tuple[str, str]], language: str) -> str:
    return "\n".join(f"<b>{_esc(translate.role(role, language))}</b>: {_esc(names)}" for role, names in credits)


def _shorten(markup: str, limit: int = MAX_DISCOGS_TEXT) -> str:
    """Recorta un texto largo por el último párrafo o frase que quepa (sin romper el marcado)."""
    if len(markup) <= limit:
        return markup
    cut = markup[:limit]
    for sep in ("\n\n", ". "):
        pos = cut.rfind(sep)
        if pos > limit // 2:
            cut = cut[: pos + (1 if sep == ". " else 0)]
            break
    # Cerrar etiquetas que hayan quedado abiertas
    for tag in ("a", "i", "b"):
        if cut.count(f"<{tag}") > cut.count(f"</{tag}>"):
            cut += f"</{tag}>"
    return cut.rstrip() + " …"


class MusicInfoService:
    """Construye, cachea y comparte las fichas; una sola búsqueda por ficha a la vez."""

    _instance: MusicInfoService | None = None

    @classmethod
    def get_default(cls) -> MusicInfoService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._cache_dir = os.path.join(GLib.get_user_cache_dir(), "myflac", "info")
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
        except OSError as e:
            log.warning("No se pudo crear la caché de fichas %s: %s", self._cache_dir, e)
        self._pending: dict[str, list[Callable[[InfoCard], None]]] = {}
        self._discogs_memory: dict[str, dict | None] = {}
        self._discogs_lock = threading.Lock()

    # ------------------------------------------------------------------ API pública
    @staticmethod
    def subject_key(kind: str, track: AudioTrack) -> str:
        """Identifica de qué trata la ficha: el mismo artista comparte ficha entre sus discos."""
        artist = track.album_artist or track.artist
        if kind == "artist":
            return f"artist|{_normalize(artist)}"
        if kind == "album":
            return f"album|{_normalize(artist)}|{_normalize(_clean_album(track.album))}"
        return f"track|{_normalize(track.artist)}|{_normalize(_clean_title(track.title))}|{_normalize(_clean_album(track.album))}"

    def fetch(self, kind: str, track: AudioTrack, language: str, callback: Callable[[InfoCard], None]):
        """callback(InfoCard) en el hilo principal. Usa la caché si existe."""
        key = f"{self.subject_key(kind, track)}|{language}"
        cache_file = os.path.join(self._cache_dir, hashlib.sha256(key.encode()).hexdigest()[:40] + ".json")
        cached = self._read_cache(cache_file)
        if cached is not None:
            GLib.idle_add(callback, cached)
            return
        if key in self._pending:
            self._pending[key].append(callback)
            return
        self._pending[key] = [callback]

        def _worker():
            try:
                info = self._build(kind, track, language)
            except Exception as e:
                log.exception("Error preparando la ficha %s: %s", key, e)
                info = InfoCard(status="error", error=str(e))
            if info.status in ("ok", "empty") and not info.temporary:
                self._write_cache(cache_file, info)
            GLib.idle_add(self._deliver, key, info)

        threading.Thread(target=_worker, name=f"music-info-{kind}", daemon=True).start()

    def prefetch(self, track: AudioTrack, language: str):
        """Prepara en segundo plano las tres fichas de la pista (para que al abrirlas salgan al instante)."""
        for kind in KINDS:
            self.fetch(kind, track, language, lambda _info: None)

    # ------------------------------------------------------------------ caché
    def _deliver(self, key: str, info: InfoCard) -> bool:
        for callback in self._pending.pop(key, []):
            try:
                callback(info)
            except Exception as e:
                log.exception("Error en callback de ficha: %s", e)
        return False

    def _read_cache(self, path: str) -> InfoCard | None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.pop("version", None) != INFO_VERSION:
                return None
            info = InfoCard(**data)
            info.facts = [tuple(x) for x in info.facts]
            info.sections = [tuple(x) for x in info.sections]
            if info.status == "empty" and time.time() - info.created > EMPTY_TTL:
                return None
            if info.image_path and not os.path.isfile(info.image_path):
                info.image_path = ""
            return info
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_cache(self, path: str, info: InfoCard):
        info.created = time.time()
        try:
            tmp = f"{path}.tmp.{threading.get_ident()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": INFO_VERSION, **asdict(info)}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except OSError as e:
            log.debug("No se pudo guardar la ficha %s: %s", path, e)

    def _discogs_cached(self, key: str, loader: Callable[[], dict | None]) -> dict | None:
        """Datos de Discogs compartidos (p. ej. el disco para las fichas Tema y Disco), en memoria y disco."""
        path = os.path.join(self._cache_dir, "discogs-" + hashlib.sha256(key.encode()).hexdigest()[:40] + ".json")
        with self._discogs_lock:
            if key in self._discogs_memory:
                return self._discogs_memory[key]
            try:
                with open(path, encoding="utf-8") as f:
                    stored = json.load(f)
                if stored.get("data") is not None or time.time() - stored.get("created", 0) < EMPTY_TTL:
                    self._discogs_memory[key] = stored.get("data")
                    return stored.get("data")
            except (OSError, ValueError):
                pass
            data = loader()  # DiscogsRateLimited u otros errores se propagan: no se guarda nada
            self._discogs_memory[key] = data
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"created": time.time(), "data": data}, f)
            except OSError:
                pass
            return data

    # ------------------------------------------------------------------ Wikipedia
    def _get_json(self, url: str) -> dict:
        with _wikipedia_lock:
            wait = WIKIPEDIA_MIN_INTERVAL - (time.monotonic() - _wikipedia_last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    raise WikipediaRateLimited("Wikipedia") from e
                raise
            finally:
                _wikipedia_last[0] = time.monotonic()

    def _download_image(self, url: str) -> str:
        """Descarga (una vez) la imagen del artículo y devuelve su ruta en la caché, o ''."""
        if not url:
            return ""
        folder = os.path.join(self._cache_dir, "images")
        path = os.path.join(folder, hashlib.sha256(url.encode()).hexdigest()[:40] + ".img")
        if os.path.isfile(path):
            return path
        try:
            os.makedirs(folder, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            tmp = f"{path}.tmp.{threading.get_ident()}"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            return path
        except Exception as e:
            log.debug("No se pudo descargar la imagen %s: %s", url, e)
            return ""

    def _wikipedia(self, kind: str, track: AudioTrack, language: str) -> WikiPage | None:
        """Entradilla de Wikipedia (con formato e imagen) del tema/disco/artista, o None."""
        artist = track.album_artist or track.artist or ""
        values = {"artist": artist, "album": _clean_album(track.album), "title": _clean_title(track.title)}
        if not values["artist"] or (kind == "album" and not values["album"]) or (kind == "track" and not values["title"]):
            return None
        keyword = re.compile(_KIND_KEYWORDS[kind], re.I)
        for lang in dict.fromkeys([language, "en"]):
            candidates = [p.format(**values) for p in _WIKI_PATTERNS.get(lang, _WIKI_PATTERNS["en"])[kind]]
            params = urllib.parse.urlencode({
                "action": "query", "titles": "|".join(candidates), "redirects": 1,
                "prop": "extracts|pageprops|description|info|pageimages", "inprop": "url", "exintro": 1,
                "piprop": "thumbnail", "pithumbsize": 640,
                "ppprop": "disambiguation", "format": "json", "formatversion": 2,
            })
            try:
                query = self._get_json(f"https://{lang}.wikipedia.org/w/api.php?{params}").get("query", {})
            except WikipediaRateLimited:
                raise
            except Exception as e:
                log.debug("Wikipedia (%s) no respondió: %s", lang, e)
                continue
            redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
            normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
            pages = {p.get("title"): p for p in query.get("pages", [])}
            for title in candidates:
                final = redirects.get(normalized.get(title, title), normalized.get(title, title))
                page = pages.get(final)
                if not page or page.get("missing") or "disambiguation" in page.get("pageprops", {}):
                    continue
                markup = html_to_markup(page.get("extract") or "")
                extract = markup_to_text(markup).strip()
                about = f"{page.get('description', '')} {extract[:400]}"
                if not extract or not keyword.search(about):
                    continue
                # Un disco o canción debe ser del artista (evita homónimos de otros artistas)
                if kind != "artist" and _normalize(artist)[:12] not in _normalize(about):
                    continue
                # Muchas canciones redirigen al artículo de su disco: eso no es una ficha del tema
                if kind == "track" and _normalize(values["title"])[:10] not in _normalize(final):
                    continue
                return WikiPage(
                    title=page.get("title", final),
                    description=page.get("description", ""),
                    markup=markup,
                    url=page.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(final)}",
                    image_url=(page.get("thumbnail") or {}).get("source", ""),
                )
        return None

    # ------------------------------------------------------------------ construcción
    def _build(self, kind: str, track: AudioTrack, language: str) -> InfoCard:
        info = InfoCard()
        try:
            wiki = self._wikipedia(kind, track, language)
        except WikipediaRateLimited:
            log.info("Wikipedia pide esperar; la ficha se completará más tarde")
            wiki, info.temporary = None, True
        if wiki:
            info.title, info.description, info.markup = wiki.title, wiki.description, wiki.markup
            if language in ("es", "ca") and urllib.parse.urlparse(wiki.url).netloc.startswith("en."):
                # Solo existe en la Wikipedia en inglés: entradilla y descripción traducidas
                info.markup = self._translated(info, wiki.markup, language)
                if wiki.description:
                    info.description = markup_to_text(self._translated(info, _esc(wiki.description), language))
            info.image_path = self._download_image(wiki.image_url)
            info.sources.append(wiki.url)

        artist = track.album_artist or track.artist or ""
        try:
            if kind == "artist":
                self._add_discogs_artist(info, artist, language)
            else:
                album = self._discogs_cached(
                    f"album|{_normalize(artist)}|{_normalize(_clean_album(track.album))}",
                    lambda: discogs.find_master(artist, _clean_album(track.album)) if track.album else None,
                )
                if kind == "album":
                    self._add_discogs_album(info, album, language)
                else:
                    self._add_discogs_track(info, album, track, language)
        except discogs.DiscogsRateLimited:
            log.info("Discogs pide esperar; la ficha se completará más tarde")
            info.temporary = True
        except Exception as e:
            log.warning("Discogs no respondió: %s", e)
            info.temporary = True

        if not (info.markup or info.facts or info.sections):
            if info.temporary:
                return InfoCard(status="error", error=i18n.t("info.err_busy"))
            return InfoCard(status="empty")
        return info

    def _translated(self, info: InfoCard, markup: str, language: str) -> str:
        """Texto libre de Discogs o Wikipedia (en inglés) traducido al idioma de la aplicación."""
        if language not in ("es", "ca") or not markup:
            return markup
        text, service = translate.Translator.get_default().translate(markup_to_text(markup), language)
        if text is None:
            info.temporary = True  # Sin traducción ahora: se reintentará más tarde
            return markup
        if service:
            info.translated_by = service
        return _esc(text)

    def _add_discogs_album(self, info: InfoCard, album: dict | None, language: str):
        if not album:
            return
        master, release = album.get("master") or {}, album.get("release") or {}
        year = master.get("year") or release.get("year")
        facts = []
        if year:
            facts.append((i18n.t("info.year"), _esc(year)))
        labels = [f"{discogs.clean_name(l.get('name', ''))}" + (f" ({l['catno']})" if l.get("catno") and l["catno"].lower() != "none" else "")
                  for l in release.get("labels", [])]
        if labels:
            facts.append((i18n.t("info.label"), _esc(", ".join(dict.fromkeys(labels)))))
        if release.get("country"):
            facts.append((i18n.t("info.country"), _esc(translate.region(release["country"], language))))
        formats = [
            ", ".join(translate.term(x, language) for x in [f.get("name", "")] + f.get("descriptions", []))
            for f in release.get("formats", [])
        ]
        if formats:
            facts.append((i18n.t("info.format"), _esc("; ".join(formats))))
        genres = master.get("genres") or release.get("genres") or []
        if genres:
            facts.append((i18n.t("info.genres"), _esc(", ".join(translate.term(g, language) for g in genres))))
        styles = master.get("styles") or release.get("styles") or []
        if styles:
            facts.append((i18n.t("info.styles"), _esc(", ".join(translate.term(s, language) for s in styles))))
        info.facts += facts
        credits = discogs.group_credits(release.get("extraartists", []))
        if credits:
            info.sections.append((i18n.t("info.credits"), _credits_markup(credits, language)))
        notes = discogs.discogs_to_markup(release.get("notes", ""))
        if notes:
            info.sections.append((i18n.t("info.release_notes"), self._translated(info, _shorten(notes), language)))
        uri = master.get("uri") or release.get("uri")
        if uri:
            info.sources.append(uri)

    def _add_discogs_track(self, info: InfoCard, album: dict | None, track: AudioTrack, language: str):
        if not album or not album.get("release"):
            return
        release = album["release"]
        found, credits = discogs.track_credits(release, _clean_title(track.title))
        if not found:
            return
        facts = []
        album_title = _clean_album(track.album)
        year = (album.get("master") or {}).get("year") or release.get("year")
        if album_title:
            facts.append((i18n.t("info.album"), _esc(f"{album_title} ({year})" if year else album_title)))
        if found.get("position"):
            facts.append((i18n.t("info.position"), _esc(found["position"])))
        if found.get("duration"):
            facts.append((i18n.t("info.duration"), _esc(found["duration"])))
        info.facts += facts
        if credits:
            info.sections.append((i18n.t("info.credits"), _credits_markup(credits, language)))
        uri = (album.get("master") or {}).get("uri") or release.get("uri")
        if uri:
            info.sources.append(uri)

    def _add_discogs_artist(self, info: InfoCard, name: str, language: str):
        if not name:
            return
        artist = self._discogs_cached(f"artist|{_normalize(name)}", lambda: discogs.find_artist(name))
        if not artist:
            return
        facts = []
        if artist.get("realname") and _normalize(artist["realname"]) != _normalize(name):
            facts.append((i18n.t("info.real_name"), _esc(artist["realname"])))
        members = [discogs.clean_name(m["name"]) for m in artist.get("members", []) if m.get("active", True)]
        if members:
            facts.append((i18n.t("info.members"), _esc(", ".join(members[:12]))))
        groups = [discogs.clean_name(g["name"]) for g in artist.get("groups", [])]
        if groups:
            facts.append((i18n.t("info.groups"), _esc(", ".join(groups[:8]))))
        aliases = [discogs.clean_name(a["name"]) for a in artist.get("aliases", [])]
        if aliases:
            facts.append((i18n.t("info.aliases"), _esc(", ".join(aliases[:8]))))
        info.facts += facts
        profile = discogs.discogs_to_markup(artist.get("profile", ""))
        if profile:
            info.sections.append((i18n.t("info.discogs_profile"), self._translated(info, _shorten(profile), language)))
        if artist.get("uri"):
            info.sources.append(artist["uri"])
