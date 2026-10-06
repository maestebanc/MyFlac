"""Salidas de red UPnP/DLNA (receptores, amplificadores, streamers y otros MediaRenderer) para MyFlac.

El dispositivo de red descarga el archivo directamente (la URL firmada de Qobuz o un archivo local
servido por HTTP desde este equipo) y lo decodifica él mismo: sin recodificación, hasta 24 bit / 192 kHz.
Todo el tráfico de red se hace fuera del hilo de la interfaz.
"""
from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import queue
import re
import socket
import threading
import time
from collections import OrderedDict
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from xml.sax.saxutils import escape

from .. import i18n
from ..logger import get_logger

log = get_logger("audio.upnp")

REMOTE_PREFIX = "upnp:"
_SSDP_ADDR = ("239.255.255.250", 1900)
_ST_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
_SOAP_ENV = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>{body}</s:Body></s:Envelope>'
)


class UpnpError(Exception):
    pass


@dataclass
class UpnpDevice:
    udn: str
    name: str
    location: str
    host: str
    manufacturer: str = ""
    model: str = ""
    av_url: str = ""
    av_type: str = "urn:schemas-upnp-org:service:AVTransport:1"
    rc_url: str = ""
    rc_type: str = "urn:schemas-upnp-org:service:RenderingControl:1"

    @property
    def id(self) -> str:
        return REMOTE_PREFIX + self.udn

    @property
    def description(self) -> str:
        parts = [p for p in (self.manufacturer, self.model) if p]
        return " ".join(parts) + (" · " if parts else "") + f"UPnP/DLNA ({self.host})"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# Descubrimiento SSDP
# ---------------------------------------------------------------------------

def _ssdp_search(timeout: float) -> set[str]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\nMX: 2\r\n'
        f"ST: {_ST_RENDERER}\r\n\r\n"
    ).encode()
    locations: set[str] = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.4)
        for _ in range(2):
            sock.sendto(msg, _SSDP_ADDR)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(r"^location:\s*(\S+)", data.decode("utf-8", "ignore"), re.I | re.M)
            if m:
                locations.add(m.group(1))
    except OSError as e:
        log.warning("Búsqueda SSDP fallida: %s", e)
    finally:
        sock.close()
    return locations


def _fetch_description(location: str) -> UpnpDevice | None:
    try:
        with urllib.request.urlopen(location, timeout=4) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        log.debug("No se pudo leer la descripción UPnP %s: %s", location, e)
        return None

    base = location
    for el in root.iter():
        if _local(el.tag) == "URLBase" and (el.text or "").strip():
            base = el.text.strip()
    udn = name = manufacturer = model = ""
    av_url = rc_url = ""
    av_type = "urn:schemas-upnp-org:service:AVTransport:1"
    rc_type = "urn:schemas-upnp-org:service:RenderingControl:1"
    devices = [el for el in root.iter() if _local(el.tag) == "device"]
    for idx, dev in enumerate(devices):
        info = {_local(c.tag): (c.text or "").strip() for c in dev if len(c) == 0}
        if idx == 0:
            udn = info.get("UDN", "")
            name = info.get("friendlyName", "")
            manufacturer = info.get("manufacturer", "")
            model = info.get("modelName", "")
        for svc in dev.iter():
            if _local(svc.tag) != "service":
                continue
            s = {_local(c.tag): (c.text or "").strip() for c in svc}
            stype = s.get("serviceType", "")
            if "AVTransport" in stype and not av_url:
                av_type, av_url = stype, urllib.parse.urljoin(base, s.get("controlURL", ""))
            elif "RenderingControl" in stype and not rc_url:
                rc_type, rc_url = stype, urllib.parse.urljoin(base, s.get("controlURL", ""))
    if not udn or not av_url:
        return None
    udn = udn.removeprefix("uuid:")
    host = urllib.parse.urlparse(location).hostname or ""
    return UpnpDevice(udn=udn, name=name or model or host, location=location, host=host,
                      manufacturer=manufacturer, model=model, av_url=av_url, av_type=av_type,
                      rc_url=rc_url, rc_type=rc_type)


_known: dict[str, UpnpDevice] = {}
_known_lock = threading.Lock()
_scan_lock = threading.Lock()
_listeners: list[Callable[[], None]] = []


def add_discovery_listener(cb: Callable[[], None]):
    _listeners.append(cb)


def known_devices() -> list[UpnpDevice]:
    """Dispositivos ya descubiertos (no bloquea)."""
    with _known_lock:
        return sorted(_known.values(), key=lambda d: d.name.lower())


def find_known_device(device_id: str) -> UpnpDevice | None:
    udn = device_id.removeprefix(REMOTE_PREFIX)
    with _known_lock:
        return _known.get(udn)


def discover(timeout: float = 2.5) -> list[UpnpDevice]:
    """Busca renderers en la red (bloqueante: llamar desde un hilo)."""
    if not _scan_lock.acquire(blocking=False):
        return known_devices()
    try:
        found: dict[str, UpnpDevice] = {}
        for loc in _ssdp_search(timeout):
            dev = _fetch_description(loc)
            if dev:
                found[dev.udn] = dev
        with _known_lock:
            changed = set(found) != set(_known)
            _known.update(found)
            # Un dispositivo que no responde se conserva: puede haber perdido solo un paquete
        if changed:
            log.info("Dispositivos UPnP/DLNA: %s", ", ".join(d.name for d in found.values()) or "ninguno")
            for cb in list(_listeners):
                try:
                    cb()
                except Exception:
                    log.exception("Error en listener de descubrimiento UPnP")
        return known_devices()
    finally:
        _scan_lock.release()


def discover_async(callback: Callable[[list[UpnpDevice]], None] | None = None):
    def run():
        devs = discover()
        if callback:
            callback(devs)
    threading.Thread(target=run, daemon=True, name="upnp-discover").start()


_bg_started = False


def start_background_discovery(interval: float = 60.0):
    """Busca al arrancar y luego periódicamente, sin bloquear la interfaz."""
    global _bg_started
    if _bg_started:
        return
    _bg_started = True

    def loop():
        while True:
            try:
                discover()
            except Exception:
                log.exception("Error en la búsqueda UPnP")
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="upnp-bg-discovery").start()


# ---------------------------------------------------------------------------
# Cliente SOAP
# ---------------------------------------------------------------------------

def soap_call(url: str, service_type: str, action: str, args: dict, timeout: float = 6.0) -> dict[str, str]:
    inner = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items())
    body = f'<u:{action} xmlns:u="{service_type}">{inner}</u:{action}>'
    req = urllib.request.Request(
        url,
        data=_SOAP_ENV.format(body=body).encode("utf-8"),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{service_type}#{action}"',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            root = ET.fromstring(e.read())
            detail = " ".join((el.text or "").strip() for el in root.iter()
                              if _local(el.tag) in ("errorCode", "errorDescription") and el.text)
        except Exception:
            pass
        raise UpnpError(f"{action}: HTTP {e.code} {detail}".strip()) from e
    except OSError as e:
        raise UpnpError(f"{action}: {e}") from e
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(data)
        for el in root.iter():
            if len(el) == 0 and _local(el.tag) not in ("Envelope", "Body"):
                out[_local(el.tag)] = el.text or ""
    except ET.ParseError:
        pass
    return out


def _fmt_time(seconds: float) -> str:
    s = int(max(0, seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _parse_time(text: str) -> float | None:
    m = re.match(r"^(\d+):(\d+):(\d+(?:\.\d+)?)$", (text or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


# ---------------------------------------------------------------------------
# Servidor HTTP para archivos locales (con soporte Range)
# ---------------------------------------------------------------------------

_MIME_OVERRIDES = {
    ".flac": "audio/flac", ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".aif": "audio/aiff", ".aiff": "audio/aiff",
    ".dsf": "audio/x-dsf", ".dff": "audio/x-dff", ".wv": "audio/x-wavpack", ".ape": "audio/x-ape",
}


def guess_mime(path_or_url: str) -> str:
    path = urllib.parse.urlparse(path_or_url).path if "://" in path_or_url else path_or_url
    ext = os.path.splitext(path)[1].lower()
    return _MIME_OVERRIDES.get(ext) or mimetypes.guess_type(path)[0] or "audio/flac"


class _FileHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MyFlac"

    def log_message(self, fmt, *args):  # silencia el log por defecto
        pass

    def _resolve(self) -> str | None:
        parts = urllib.parse.urlparse(self.path).path.split("/")
        if len(parts) >= 3 and parts[1] == "f":
            return self.server.files.get(parts[2])  # type: ignore[attr-defined]
        return None

    def _serve_cover(self, head: bool) -> bool:
        """Portadas en memoria: /c/<token>/cover.jpg. Devuelve True si la ruta era de portada."""
        parts = urllib.parse.urlparse(self.path).path.split("/")
        if len(parts) < 3 or parts[1] != "c":
            return False
        data = self.server.covers.get(parts[2])  # type: ignore[attr-defined]
        if data is None:
            self.send_error(404)
            return True
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("contentFeatures.dlna.org", "DLNA.ORG_PN=JPEG_MED;DLNA.ORG_OP=01;DLNA.ORG_CI=0")
        self.end_headers()
        if not head:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
        return True

    def _serve_dash(self, head: bool) -> bool:
        """
        Streams MPEG-DASH (TIDAL): /d/<token>/stream.flac. Los fragmentos MP4 se convierten al vuelo
        en un FLAC continuo sin decodificar (mismos bits), que cualquier renderer UPnP entiende.
        """
        parts = urllib.parse.urlparse(self.path).path.split("/")
        if len(parts) < 3 or parts[1] != "d":
            return False
        mpd_url = self.server.dash.get(parts[2])  # type: ignore[attr-defined]
        if mpd_url is None:
            self.send_error(404)
            return True
        self.send_response(200)
        self.send_header("Content-Type", "audio/flac")
        self.send_header("transferMode.dlna.org", "Streaming")
        self.send_header("contentFeatures.dlna.org",
                         "DLNA.ORG_OP=00;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if head:
            return True
        try:
            for chunk in dash_to_flac(mpd_url):
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # El renderer corta al saltar de pista o al parar
        except Exception as e:
            log.warning("Error al convertir el stream DASH para el renderer: %s", e)
        return True

    def _serve(self, head: bool):
        if self._serve_cover(head) or self._serve_dash(head):
            return
        path = self._resolve()
        if not path or not os.path.isfile(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", guess_mime(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("transferMode.dlna.org", "Streaming")
        self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # El renderer cierra la conexión al saltar o hacer seek

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)


# Puertos fijos preferidos: así basta con abrir uno en el cortafuegos (si está ocupado, el siguiente)
MEDIA_SERVER_PORTS = range(8765, 8775)
_MAX_SERVED_FILES = 256
_MAX_SERVED_COVERS = 32
# Los renderers muestran mejor (y más rápido) una portada JPEG de tamaño moderado
COVER_MAX_PX = 800


class MediaServer:
    """Sirve únicamente los archivos registrados, bajo URLs con un token aleatorio."""

    def __init__(self):
        self._httpd = None
        for port in [*MEDIA_SERVER_PORTS, 0]:
            try:
                self._httpd = ThreadingHTTPServer(("0.0.0.0", port), _FileHandler)
                break
            except OSError:
                continue
        assert self._httpd is not None
        self._httpd.daemon_threads = True
        self._httpd.files = OrderedDict()  # type: ignore[attr-defined]
        self._httpd.covers = OrderedDict()  # type: ignore[attr-defined]
        self._httpd.dash = OrderedDict()  # type: ignore[attr-defined]
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True, name="upnp-media-server").start()
        log.info("Servidor de medios UPnP escuchando en el puerto %d", self.port)

    def url_for(self, path: str, peer_host: str) -> str:
        ip = _local_ip_towards(peer_host)
        token = os.urandom(8).hex()
        files = self._httpd.files  # type: ignore[attr-defined]
        files[token] = os.path.abspath(path)
        while len(files) > _MAX_SERVED_FILES:
            files.popitem(last=False)  # Solo hace falta la pista actual y la siguiente
        name = urllib.parse.quote(os.path.basename(path))
        return f"http://{ip}:{self.port}/f/{token}/{name}"

    def dash_url_for(self, mpd_url: str, peer_host: str) -> str:
        """URL local que entrega como FLAC normal un stream MPEG-DASH (TIDAL)."""
        ip = _local_ip_towards(peer_host)
        token = os.urandom(8).hex()
        dash = self._httpd.dash  # type: ignore[attr-defined]
        dash[token] = mpd_url
        while len(dash) > _MAX_SERVED_COVERS:
            dash.popitem(last=False)
        return f"http://{ip}:{self.port}/d/{token}/stream.flac"

    def cover_url_for(self, image: bytes, peer_host: str) -> str:
        """Publica una portada (ya en JPEG) para que el renderer la descargue."""
        ip = _local_ip_towards(peer_host)
        token = hashlib.sha1(image).hexdigest()[:16]  # La misma portada para todo el álbum
        covers = self._httpd.covers  # type: ignore[attr-defined]
        covers[token] = image
        covers.move_to_end(token)
        while len(covers) > _MAX_SERVED_COVERS:
            covers.popitem(last=False)
        return f"http://{ip}:{self.port}/c/{token}/cover.jpg"

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()


def _local_ip_towards(peer_host: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((peer_host or "239.255.255.250", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


_media_server: MediaServer | None = None
_media_server_lock = threading.Lock()


def get_media_server() -> MediaServer:
    global _media_server
    with _media_server_lock:
        if _media_server is None:
            _media_server = MediaServer()
        return _media_server


# ---------------------------------------------------------------------------
# Renderer remoto
# ---------------------------------------------------------------------------

# Flags DLNA: transferencia en streaming, admite salto por bytes (Range)
_DLNA_FEATURES = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"


def build_didl(title: str, artist: str, album: str, url: str, mime: str,
               duration: float, cover_url: str = "", sample_rate: int = 0,
               bit_depth: int = 0, channels: int = 2) -> str:
    """Metadatos DIDL-Lite de la pista. Frecuencia y bits permiten al renderer mostrar la resolución."""
    art = f"<upnp:albumArtURI>{escape(cover_url)}</upnp:albumArtURI>" if cover_url.startswith("http") else ""
    attrs = f' protocolInfo="http-get:*:{escape(mime)}:{_DLNA_FEATURES}"'
    if duration > 0:
        attrs += f' duration="{_fmt_time(duration)}.000"'
    if sample_rate > 0:
        attrs += f' sampleFrequency="{int(sample_rate)}"'
    if bit_depth > 0:
        attrs += f' bitsPerSample="{int(bit_depth)}"'
    if channels > 0:
        attrs += f' nrAudioChannels="{int(channels)}"'
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{escape(title or '')}</dc:title>"
        f"<dc:creator>{escape(artist or '')}</dc:creator>"
        f"<upnp:artist>{escape(artist or '')}</upnp:artist>"
        f"<upnp:album>{escape(album or '')}</upnp:album>{art}"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        f"<res{attrs}>{escape(url)}</res>"
        "</item></DIDL-Lite>"
    )


def same_uri(a: str, b: str) -> bool:
    """Compara la URI que informa el renderer con la enviada (algunos la devuelven escapada)."""
    from html import unescape
    a, b = unescape((a or "").strip()), unescape((b or "").strip())
    return bool(a) and (a == b or urllib.parse.unquote(a) == urllib.parse.unquote(b))


def has_advanced(reported_uri: str, next_uri: str, prev_pos: float, new_pos: float, duration: float) -> bool:
    """
    ¿El renderer ha pasado solo a la pista encadenada (SetNextAVTransportURI)?

    La posición tiene que haber vuelto al principio: ciertos renderers informan de la URI
    siguiente en cuanto terminan de descargar la actual, mucho antes de que empiece a sonar.
    """
    if not next_uri:
        return False
    jumped_back = new_pos < 5 and prev_pos > new_pos + 3
    if not jumped_back:
        return False
    if same_uri(reported_uri, next_uri):
        return True
    # Hay renderers que reescriben la URI: el salto desde casi el final también lo delata
    return duration > 10 and prev_pos > duration - 15


def dash_to_flac(mpd_url: str, timeout_s: float = 20.0):
    """
    Genera los bytes de un FLAC continuo a partir de un stream MPEG-DASH con FLAC en MP4, sin
    decodificar: urisourcebin (DASH y MP4) → flacparse. El primer bloque es la cabecera «fLaC».
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    pipeline = Gst.parse_launch(
        f'urisourcebin uri="{mpd_url}" parse-streams=true ! flacparse ! appsink name=sink sync=false max-buffers=64')
    sink = pipeline.get_by_name("sink")
    pipeline.set_state(Gst.State.PLAYING)
    first = True
    try:
        while True:
            sample = sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
            if sample is None:
                msg = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                if msg is not None:
                    raise RuntimeError(msg.parse_error()[0].message)
                return  # Fin del stream
            buf = sample.get_buffer()
            data = buf.extract_dup(0, buf.get_size())
            if first:
                first = False
                if not data.startswith(b"fLaC"):
                    # Sin cabecera en línea: se toma de las caps (streamheader de flacparse)
                    st = sample.get_caps().get_structure(0)
                    if st.has_field("streamheader"):
                        for hb in st.get_value("streamheader"):
                            yield hb.extract_dup(0, hb.get_size())
            yield data
    finally:
        pipeline.set_state(Gst.State.NULL)


def cover_jpeg(data: bytes, max_px: int = COVER_MAX_PX) -> bytes | None:
    """Portada como JPEG de hasta `max_px` píxeles (los renderers no siempre aceptan PNG o 3000 px)."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            if img.format == "JPEG" and max(img.size) <= max_px and img.mode in ("RGB", "L"):
                return data
            img = img.convert("RGB")
            img.thumbnail((max_px, max_px))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=90)
            return out.getvalue()
    except Exception as e:
        log.debug("No se pudo preparar la portada para el renderer: %s", e)
        return None


def local_cover_url(track, peer_host: str) -> str:
    """URL servida desde este equipo con la portada de una pista local ('' si no tiene)."""
    cover = track.cached_cover() if hasattr(track, "cached_cover") else None
    if cover is None and hasattr(track, "get_cover_image_bytes"):
        cover = track.get_cover_image_bytes()  # Hilo de trabajo: puede leer del disco
    if not cover:
        return ""
    jpeg = cover_jpeg(cover[0])
    return get_media_server().cover_url_for(jpeg, peer_host) if jpeg else ""


class RemoteRenderer:
    """
    Controla un MediaRenderer UPnP. Todos los comandos se ejecutan en un hilo de trabajo y el
    estado se sondea cada segundo; los callbacks se entregan en el hilo principal de GTK.
    """

    _QUIET_S = 2.5  # tras una orden del usuario se ignora el estado sondeado (puede ir retrasado)

    def __init__(self, device: UpnpDevice,
                 on_state: Callable[[str], None],
                 on_finished: Callable[[], None],
                 on_error: Callable[[str], None],
                 on_volume: Callable[[], None] | None = None,
                 on_advanced: Callable[[object], None] | None = None):
        from gi.repository import GLib
        self._glib = GLib
        self.device = device
        self._on_state, self._on_finished, self._on_error, self._on_volume = (
            on_state, on_finished, on_error, on_volume)
        self._on_advanced = on_advanced

        self.volume: float | None = None
        self._base_pos = 0.0
        self._base_ts = time.monotonic()
        self._playing = False
        self._duration = 0.0

        self._expect_playing = False
        self._seen_playing = False
        self._load_ts = 0.0
        self._quiet_until = 0.0
        self._reported = "STOPPED"
        self._gen = 0
        self._pending_volume: float | None = None
        self._closed = False
        self._error_reported = False
        self._current_is_local = False
        # Pista encadenada con SetNextAVTransportURI (reproducción sin pausas entre pistas)
        self._next_track = None
        self._next_url = ""
        self._next_gen = 0
        self._last_rel = 0.0

        self._q: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="upnp-worker").start()
        threading.Thread(target=self._poller, daemon=True, name="upnp-poller").start()
        self._submit(self._fetch_volume)

    # -- utilidades ---------------------------------------------------------

    def _ui(self, fn, *args):
        self._glib.idle_add(lambda: (fn(*args), False)[1])

    def _submit(self, job: Callable[[], None]):
        self._q.put(job)

    def _worker(self):
        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                job()
            except UpnpError as e:
                log.warning("UPnP (%s): %s", self.device.name, e)
                self._fail(str(e))
            except Exception as e:
                log.exception("Error inesperado en el renderer UPnP")
                self._fail(str(e))

    def _fail(self, reason: str):
        if self._closed or self._error_reported:
            return
        self._error_reported = True
        self._ui(self._on_error, reason)

    def _avt(self, action: str, **args) -> dict:
        return soap_call(self.device.av_url, self.device.av_type, action, {"InstanceID": 0, **args})

    def _rc(self, action: str, **args) -> dict:
        if not self.device.rc_url:
            raise UpnpError("El dispositivo no expone RenderingControl")
        return soap_call(self.device.rc_url, self.device.rc_type, action, {"InstanceID": 0, **args})

    def _quiet(self):
        self._quiet_until = time.monotonic() + self._QUIET_S

    def _prepare(self, track) -> tuple[str, str]:
        """URL y metadatos DIDL de la pista (renueva la URL firmada de streaming si ha caducado)."""
        if getattr(track, "needs_stream_url", None) and track.needs_stream_url():
            try:
                track.resolve_stream()
            except Exception as e:
                raise UpnpError(i18n.t("devices.network_stream_failed", error=e)) from e
        cover_url = getattr(track, "cover_url", "") or ""
        if getattr(track, "stream_mime", "") == "application/dash+xml":
            # TIDAL: el renderer no entiende DASH; se le sirve como FLAC desde este equipo
            url = get_media_server().dash_url_for(track.filepath, self.device.host)
            mime = "audio/flac"
        elif track.filepath.startswith(("http://", "https://")):
            url = track.filepath
            mime = getattr(track, "stream_mime", "") or guess_mime(url)
        else:
            url = get_media_server().url_for(track.filepath, self.device.host)
            mime = guess_mime(track.filepath)
            if not cover_url:
                # Pista local: la portada (embebida o cover.jpg) se sirve desde este equipo
                cover_url = local_cover_url(track, self.device.host)
                log.info("UPnP portada de '%s': %s", track.title, cover_url or "ninguna")
        didl = build_didl(track.title, track.artist, track.album, url, mime, track.duration,
                          cover_url,
                          sample_rate=track.sample_rate or 0,
                          bit_depth=track.bits_per_sample if mime != "audio/mpeg" else 0,
                          channels=track.channels or 2)
        return url, didl

    # -- posición -----------------------------------------------------------

    @property
    def position(self) -> float:
        if self._playing:
            return self._base_pos + (time.monotonic() - self._base_ts)
        return self._base_pos

    def _set_position(self, pos: float, playing: bool | None = None):
        self._base_pos = max(0.0, pos)
        self._base_ts = time.monotonic()
        if playing is not None:
            self._playing = playing

    # -- órdenes ------------------------------------------------------------

    def load(self, track, play: bool, position: float = 0.0):
        self._gen += 1
        gen = self._gen
        self._error_reported = False
        self._expect_playing = play
        self._seen_playing = False
        self._load_ts = time.monotonic()
        self._reported = "PLAYING" if play else "PAUSED"
        self._duration = track.duration or 0.0
        self._next_track, self._next_url = None, ""
        self._last_rel = position
        self._quiet()
        self._set_position(position, play)

        def job():
            if gen != self._gen:
                return
            # El renderer descarga de este equipo: archivos locales y streams DASH convertidos aquí
            self._current_is_local = getattr(track, "stream_mime", "") == "application/dash+xml" or (
                not track.filepath.startswith(("http://", "https://")) and not getattr(track, "is_stream", False))
            url, didl = self._prepare(track)
            log.info("UPnP → %s: %s (%s Hz, %s bit)", self.device.name,
                     url if self._current_is_local else url.split("?", 1)[0],
                     track.sample_rate, track.bits_per_sample)
            try:
                self._avt("Stop")
            except UpnpError:
                pass
            self._avt("SetAVTransportURI", CurrentURI=url, CurrentURIMetaData=didl)
            if gen != self._gen:
                return
            if play:
                self._avt("Play", Speed="1")
                if position > 1.0:
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline and gen == self._gen:
                        if self._avt("GetTransportInfo").get("CurrentTransportState") == "PLAYING":
                            break
                        time.sleep(0.4)
                    if gen == self._gen:
                        self._avt("Seek", Unit="REL_TIME", Target=_fmt_time(position))
            self._quiet()

        self._submit(job)

    def set_next(self, track):
        """Encadena la siguiente pista en el propio dispositivo para que no haya silencio entre pistas."""
        self._next_gen += 1
        ngen, gen = self._next_gen, self._gen
        self._next_track, self._next_url = None, ""
        if track is None:
            return

        def job():
            if ngen != self._next_gen or gen != self._gen or self._closed:
                return
            try:
                url, didl = self._prepare(track)
                self._avt("SetNextAVTransportURI", NextURI=url, NextURIMetaData=didl)
            except UpnpError as e:
                # No todos los renderers lo admiten: la siguiente pista se carga al terminar esta
                log.info("UPnP (%s): sin encadenado de pistas (%s)", self.device.name, e)
                return
            if ngen == self._next_gen and gen == self._gen:
                self._next_track, self._next_url = track, url
                log.info("UPnP: siguiente pista encadenada en %s: '%s'", self.device.name, track.title)

        self._submit(job)

    def play(self):
        self._expect_playing = True
        self._quiet()
        self._set_position(self.position, True)
        self._reported = "PLAYING"
        self._submit(lambda: self._avt("Play", Speed="1"))

    def pause(self):
        self._expect_playing = False
        self._quiet()
        self._set_position(self.position, False)
        self._reported = "PAUSED"
        self._submit(lambda: self._avt("Pause"))

    def stop(self):
        self._expect_playing = False
        self._gen += 1
        self._next_track, self._next_url = None, ""
        self._quiet()
        self._set_position(0.0, False)
        self._reported = "STOPPED"
        self._submit(lambda: self._avt("Stop"))

    def seek(self, seconds: float):
        self._quiet()
        self._set_position(seconds)
        self._last_rel = seconds
        self._submit(lambda: self._avt("Seek", Unit="REL_TIME", Target=_fmt_time(seconds)))

    def set_volume(self, vol: float):
        if self.volume is None or abs(vol - self.volume) < 0.005:
            return
        self.volume = vol
        self._pending_volume = vol

        def job():
            v, self._pending_volume = self._pending_volume, None
            if v is not None:
                self._rc("SetVolume", Channel="Master", DesiredVolume=int(round(v * 100)))

        self._submit(job)

    def _fetch_volume(self):
        if not self.device.rc_url:
            return
        try:
            v = int(self._rc("GetVolume", Channel="Master").get("CurrentVolume", ""))
        except (UpnpError, ValueError):
            return
        vol = max(0.0, min(1.0, v / 100.0))
        if self._pending_volume is not None or (self.volume is not None and abs(vol - self.volume) < 0.005):
            return
        self.volume = vol
        if self._on_volume:
            self._ui(self._on_volume)

    def stop_now(self, wait: bool = False):
        """Para el dispositivo al margen de la cola de órdenes (al cambiar de salida o cerrar)."""
        self._expect_playing = False
        self._gen += 1

        def run():
            try:
                self._avt("Stop")
            except UpnpError:
                pass

        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def shutdown(self):
        self._closed = True
        self._gen += 1
        self._expect_playing = False
        self._q.put(None)

    # -- sondeo del estado --------------------------------------------------

    def _poller(self):
        ticks = 0
        while not self._closed:
            time.sleep(1.0)
            ticks += 1
            try:
                if ticks % 4 == 0 and self._pending_volume is None:
                    self._fetch_volume()  # El volumen también cambia con la rueda o la app del equipo
                self._poll_once()
            except UpnpError:
                pass
            except Exception:
                log.exception("Error en el sondeo UPnP")

    def _no_start_reason(self) -> str:
        if self._current_is_local:
            port = get_media_server().port
            return i18n.t("devices.network_local_blocked", port=port)
        return i18n.t("devices.network_no_start")

    def _poll_once(self):
        if self._closed:
            return
        info = self._avt("GetTransportInfo")
        state = info.get("CurrentTransportState", "")
        now = time.monotonic()

        if state == "PLAYING":
            self._seen_playing = True
        pos_info = self._avt("GetPositionInfo") if state in ("PLAYING", "PAUSED_PLAYBACK", "TRANSITIONING") else {}
        rel = _parse_time(pos_info.get("RelTime", ""))

        if rel is not None and self._next_track is not None and has_advanced(
                pos_info.get("TrackURI", ""), self._next_url, self._last_rel, rel, self._duration):
            # El dispositivo ya suena la pista encadenada: se avisa sin recargar nada
            track = self._next_track
            self._next_track, self._next_url = None, ""
            self._duration = track.duration or 0.0
            self._current_is_local = not getattr(track, "is_stream", False)
            self._last_rel = rel
            self._set_position(rel, state == "PLAYING")
            if self._on_advanced:
                self._ui(self._on_advanced, track)
            return
        if rel is not None:
            self._last_rel = rel

        if rel is not None and now >= self._quiet_until:
            self._set_position(rel, state == "PLAYING")

        if now < self._quiet_until:
            return

        if state in ("STOPPED", "NO_MEDIA_PRESENT") and self._expect_playing:
            if self._seen_playing:
                self._expect_playing = False
                self._seen_playing = False
                self._set_position(0.0, False)
                self._reported = "STOPPED"
                natural_end = (
                    self._duration <= 0
                    or self._last_rel >= max(0.0, self._duration - 6.0)
                )
                if natural_end:
                    self._ui(self._on_finished)
                else:
                    log.info("Pista detenida externamente a los %.1fs (duración %.1fs) en '%s'",
                             self._last_rel, self._duration, self.device.name)
                    self._next_track, self._next_url = None, ""
                    self._ui(self._on_state, "STOPPED")
            elif now - self._load_ts > 15:
                self._expect_playing = False
                self._fail(self._no_start_reason())
            return

        mapped = {"PLAYING": "PLAYING", "PAUSED_PLAYBACK": "PAUSED", "STOPPED": "STOPPED"}.get(state)
        if mapped and mapped != self._reported:
            # Cambio hecho desde fuera (botones o app del propio dispositivo)
            self._reported = mapped
            self._expect_playing = mapped == "PLAYING"
            self._set_position(self._base_pos, mapped == "PLAYING")
            if mapped == "STOPPED":
                self._next_track, self._next_url = None, ""
            self._ui(self._on_state, mapped)
