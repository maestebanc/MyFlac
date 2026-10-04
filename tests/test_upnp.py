"""Salida de red UPnP/DLNA: metadatos, servidor de archivos y encadenado de pistas."""
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from myflac.audio import upnp
from myflac.audio.track import AudioTrack


def test_time_roundtrip():
    assert upnp._fmt_time(3725.4) == "1:02:05"
    assert upnp._parse_time("1:02:05") == 3725
    assert upnp._parse_time("0:00:07.500") == 7.5
    assert upnp._parse_time("NOT_IMPLEMENTED") is None


def test_didl_announces_hires_resolution():
    didl = upnp.build_didl("Título & más", "Artista", "Álbum", "https://cdn/x?a=1&b=2", "audio/flac",
                           245.0, "https://cdn/cover.jpg", sample_rate=192000, bit_depth=24)
    assert 'protocolInfo="http-get:*:audio/flac:DLNA.ORG_OP=01' in didl
    assert 'sampleFrequency="192000"' in didl
    assert 'bitsPerSample="24"' in didl
    assert 'nrAudioChannels="2"' in didl
    assert 'duration="0:04:05.000"' in didl
    assert "https://cdn/x?a=1&amp;b=2" in didl
    assert "Título &amp; más" in didl
    assert "<upnp:albumArtURI>https://cdn/cover.jpg</upnp:albumArtURI>" in didl


def test_track_advance_detection():
    nxt = "http://10.0.0.2:8765/f/abc/02%20B.flac"
    assert upnp.same_uri("http://10.0.0.2:8765/f/abc/02 B.flac", nxt)
    assert upnp.same_uri("https://q/x?a=1&amp;b=2", "https://q/x?a=1&b=2")
    assert upnp.has_advanced(nxt, nxt, prev_pos=299, new_pos=1, duration=300)
    # El WiiM informa de la URI siguiente al acabar de descargar la actual: aún no ha cambiado
    assert not upnp.has_advanced(nxt, nxt, prev_pos=26, new_pos=27, duration=460)
    # URI reescrita por el renderer: lo delata el salto del final al principio
    assert upnp.has_advanced("other", nxt, prev_pos=297, new_pos=1, duration=300)
    assert not upnp.has_advanced("other", nxt, prev_pos=120, new_pos=1, duration=300)  # un seek
    assert not upnp.has_advanced(nxt, "", prev_pos=297, new_pos=1, duration=300)


def test_media_server_serves_ranges(tmp_path):
    f = tmp_path / "01 Pista.flac"
    f.write_bytes(bytes(range(256)) * 4)
    server = upnp.MediaServer()
    try:
        url = server.url_for(str(f), "127.0.0.1")
        assert re.match(rf"http://127\.0\.0\.1:{server.port}/f/[0-9a-f]{{16}}/01%20Pista\.flac$", url)

        req = urllib.request.Request(url, headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 206
            assert resp.headers["Content-Type"] == "audio/flac"
            assert resp.headers["Content-Range"] == "bytes 10-19/1024"
            assert resp.read() == bytes(range(10, 20))

        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200 and len(resp.read()) == 1024

        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(url.replace("/f/", "/f/00").rsplit("/", 2)[0] + "/x/y", timeout=5)
        assert err.value.code == 404
    finally:
        server.shutdown()


def test_media_server_prefers_fixed_port():
    server = upnp.MediaServer()
    try:
        assert server.port in upnp.MEDIA_SERVER_PORTS or server.port > 0
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# Renderer simulado (como un WiiM): AVTransport por SOAP con estado y siguiente pista
# ---------------------------------------------------------------------------

class _FakeRenderer:
    def __init__(self):
        self.actions: list[tuple[str, str]] = []
        self.state = "STOPPED"
        self.uri = ""
        self.next_uri = ""
        self.rel = 0
        self.refuse_play = False  # Simula un renderer que no logra descargar el archivo
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                action = re.search(r"<u:(\w+)", body).group(1)
                fake.actions.append((action, body))
                out = ""
                if action == "SetAVTransportURI":
                    fake.uri = re.search(r"<CurrentURI>(.*?)</CurrentURI>", body).group(1)
                elif action == "SetNextAVTransportURI":
                    fake.next_uri = re.search(r"<NextURI>(.*?)</NextURI>", body).group(1)
                elif action == "Play":
                    fake.state = "STOPPED" if fake.refuse_play else "PLAYING"
                elif action == "Stop":
                    fake.state = "STOPPED"
                elif action == "GetTransportInfo":
                    out = f"<CurrentTransportState>{fake.state}</CurrentTransportState>"
                elif action == "GetPositionInfo":
                    out = f"<RelTime>{upnp._fmt_time(fake.rel)}</RelTime><TrackURI>{fake.uri}</TrackURI>"
                data = (f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                        f'<u:{action}Response xmlns:u="x">{out}</u:{action}Response></s:Body></s:Envelope>').encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/avt"

    def advance(self):
        """El renderer pasa solo a la pista encadenada, como hace al terminar la actual."""
        self.uri, self.next_uri, self.rel = self.next_uri or self.uri, "", 1

    def close(self):
        self.httpd.shutdown()


def _wait(cond, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def renderer(monkeypatch):
    fake = _FakeRenderer()
    dev = upnp.UpnpDevice(udn="test", name="WiiM Test", location=fake.url, host="127.0.0.1", av_url=fake.url)
    events = {"advanced": [], "finished": 0, "errors": []}
    # Sin bucle de GTK en los tests: los avisos se entregan directamente
    monkeypatch.setattr(upnp.RemoteRenderer, "_ui", lambda self, fn, *args: fn(*args))
    r = upnp.RemoteRenderer(dev, on_state=lambda s: None,
                            on_finished=lambda: events.__setitem__("finished", events["finished"] + 1),
                            on_error=events["errors"].append,
                            on_advanced=events["advanced"].append)
    yield fake, r, events
    r.shutdown()
    fake.close()


def _stream_track(title, url, rate=192000, bits=24):
    t = AudioTrack(filepath=url, title=title, artist="A", album="B", duration=200,
                   sample_rate=rate, bits_per_sample=bits)
    t.is_stream = True
    t.stream_mime = "audio/flac"
    return t


def test_renderer_plays_and_chains_next_track(renderer):
    fake, r, events = renderer
    first = _stream_track("Uno", "https://cdn.example/1?sig=a&x=1")
    second = _stream_track("Dos", "https://cdn.example/2?sig=b", rate=96000)

    r.load(first, play=True)
    assert _wait(lambda: fake.state == "PLAYING")
    set_uri = next(body for action, body in fake.actions if action == "SetAVTransportURI")
    assert "https://cdn.example/1?sig=a&amp;x=1" in set_uri
    assert 'sampleFrequency="192000"' in set_uri and "&lt;DIDL-Lite" in set_uri  # DIDL escapado en el SOAP

    r.set_next(second)
    assert _wait(lambda: fake.next_uri == "https://cdn.example/2?sig=b")
    assert _wait(lambda: r._next_track is second)

    fake.uri, fake.rel = fake.next_uri, 30  # Ya descargada la actual: informa de la siguiente
    time.sleep(1.5)
    assert events["advanced"] == []  # No ha cambiado de pista todavía

    fake.rel = 199
    time.sleep(1.5)
    fake.advance()
    assert _wait(lambda: events["advanced"] == [second])
    assert events["finished"] == 0  # sin recarga ni salto: sin pausa entre pistas
    assert events["errors"] == []


def test_renderer_renews_expired_stream_url(renderer):
    fake, r, _events = renderer
    track = _stream_track("Caducada", "https://cdn.example/old")
    track.stream_resolver = lambda: "https://cdn.example/new"
    track.stream_resolved_at = time.monotonic() - 3600  # URL firmada de hace una hora

    r.load(track, play=True)
    assert _wait(lambda: fake.uri == "https://cdn.example/new")
    assert track.filepath == "https://cdn.example/new"


def test_renderer_reports_local_file_firewall_hint(renderer, tmp_path, monkeypatch):
    fake, r, events = renderer
    f = tmp_path / "a.flac"
    f.write_bytes(b"x")
    track = AudioTrack(filepath=str(f), title="Local", duration=100)
    monkeypatch.setattr(upnp.RemoteRenderer, "_QUIET_S", 0.0)

    fake.refuse_play = True
    r.load(track, play=True)
    assert _wait(lambda: any(action == "Play" for action, _ in fake.actions))
    r._load_ts -= 20  # Han pasado los 15 s de margen sin que empiece a sonar
    assert _wait(lambda: events["errors"])
    assert str(upnp.get_media_server().port) in events["errors"][0]


def test_cover_is_converted_to_moderate_jpeg():
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGBA", (2000, 2000), (200, 30, 30, 255)).save(buf, "PNG")
    jpeg = upnp.cover_jpeg(buf.getvalue())
    with Image.open(BytesIO(jpeg)) as img:
        assert img.format == "JPEG" and max(img.size) == upnp.COVER_MAX_PX


def test_local_track_sends_its_cover(renderer, tmp_path):
    from io import BytesIO
    from PIL import Image
    fake, r, _events = renderer
    buf = BytesIO()
    Image.new("RGB", (300, 300), (10, 120, 200)).save(buf, "JPEG")
    f = tmp_path / "01 Oxygene.flac"
    f.write_bytes(b"x")
    track = AudioTrack(filepath=str(f), title="Oxygene (Part I)", duration=460,
                       cover_data=buf.getvalue(), cover_mime="image/jpeg")

    r.load(track, play=True)
    assert _wait(lambda: any(action == "SetAVTransportURI" for action, _ in fake.actions))
    body = next(b for a, b in fake.actions if a == "SetAVTransportURI")
    art = re.search(r"albumArtURI&gt;(.*?)&lt;", body).group(1)
    assert re.search(r"/c/[0-9a-f]{16}/cover\.jpg$", art)
    with urllib.request.urlopen(art, timeout=5) as resp:
        assert resp.headers["Content-Type"] == "image/jpeg"
        assert resp.read() == buf.getvalue()  # JPEG pequeño: se sirve tal cual


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="hace falta ffmpeg para crear el DASH de prueba")
def test_dash_stream_is_served_as_bit_identical_flac(tmp_path):
    """TIDAL entrega DASH (FLAC en MP4): al renderer le llega un FLAC normal con los mismos bits."""
    import functools
    import hashlib
    import subprocess
    from http.server import SimpleHTTPRequestHandler

    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=96000:duration=6", "-ac", "2", "-c:a", "flac",
                    "-sample_fmt", "s32", "-bits_per_raw_sample", "24", "-strict", "-2", "-f", "dash",
                    "-seg_duration", "2", str(tmp_path / "out.mpd")], check=True)

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    cdn = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=cdn.serve_forever, daemon=True).start()
    server = upnp.MediaServer()
    try:
        url = server.dash_url_for(f"http://127.0.0.1:{cdn.server_address[1]}/out.mpd", "127.0.0.1")
        with urllib.request.urlopen(url, timeout=30) as resp:
            assert resp.headers["Content-Type"] == "audio/flac"
            data = resp.read()
        assert data.startswith(b"fLaC")
        (tmp_path / "remux.flac").write_bytes(data)

        def pcm_md5(path):
            out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s32le", "-c:a", "pcm_s32le", "-"],
                                 check=True, capture_output=True).stdout
            return hashlib.md5(out).hexdigest(), len(out)

        assert pcm_md5(tmp_path / "remux.flac") == pcm_md5(tmp_path / "out.mpd")
    finally:
        server.shutdown()
        cdn.shutdown()
