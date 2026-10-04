"""Cliente de TIDAL (API oficial, JSON:API): formatos, colección, reproducción e inicio de sesión."""
import json
import stat
import threading
import urllib.request

import pytest

from myflac.streaming import tidal_client as tc
from myflac.streaming.qobuz_client import QobuzError


@pytest.fixture
def client(tmp_path):
    c = tc.TidalClient(config_path=tmp_path / "tidal.json")
    c.client_id = "cid"
    c._tokens = tc._Tokens("tok", "refresh", 9e12)
    c.country = "ES"
    return c


def _artwork(id_, w):
    return {"id": id_, "type": "artworks", "attributes": {"files": [
        {"href": f"https://img/{id_}/80.jpg", "meta": {"width": 80, "height": 80}},
        {"href": f"https://img/{id_}/640.jpg", "meta": {"width": w, "height": w}},
        {"href": f"https://img/{id_}/1280.jpg", "meta": {"width": 1280, "height": 1280}}]}}


ALBUM = {"id": "100", "type": "albums",
         "attributes": {"title": "Oxygène", "releaseDate": "1976-12-05", "albumType": "ALBUM",
                        "mediaTags": ["LOSSLESS", "HIRES_LOSSLESS"], "numberOfItems": 6},
         "relationships": {"artists": {"data": [{"id": "7", "type": "artists"}]},
                           "coverArt": {"data": [{"id": "c1", "type": "artworks"}]},
                           "genres": {"data": [{"id": "g1", "type": "genres"}]}}}
INCLUDED = [{"id": "7", "type": "artists", "attributes": {"name": "Jean-Michel Jarre"}},
            _artwork("c1", 640),
            {"id": "g1", "type": "genres", "attributes": {"genreName": "electronic"}}]


def test_formats():
    assert tc.parse_iso_duration("PT7M40S") == 460
    assert tc.parse_iso_duration("PT1H2M3.5S") == 3723.5
    assert tc.parse_iso_duration(None) == 0
    assert tc.best_image(INCLUDED[1]["attributes"]["files"]) == "https://img/c1/640.jpg"
    assert tc.parse_dash_sample_rate('<Representation audioSamplingRate="96000" codecs="flac"/>') == 96000
    verifier, challenge = tc.pkce_pair()
    import base64, hashlib
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_album_from_json_api(client):
    doc = tc.Document({"data": [ALBUM], "included": INCLUDED})
    album = client._album(doc, doc.data[0])
    assert (album.title, album.artist, album.artist_id, album.release_date) == ("Oxygène", "Jean-Michel Jarre", 7, "1976")
    assert (album.hires, album.genre_name, album.release_type) == (True, "Electronic", "album")
    assert album.cover_url == "https://img/c1/640.jpg"


def test_album_with_tracks(client, monkeypatch):
    def fake_get(path, params=None):
        if path == "albums":
            return tc.Document({"data": [ALBUM], "included": INCLUDED})
        if path == "albums/100/relationships/items":
            return tc.Document({"data": [{"id": "1001", "type": "tracks", "meta": {"trackNumber": 1, "volumeNumber": 1}},
                                         {"id": "1002", "type": "tracks", "meta": {"trackNumber": 2, "volumeNumber": 1}}],
                                "links": {}})
        if path == "tracks":
            assert params["filter[id]"] == ["1001", "1002"]
            return tc.Document({"data": [
                {"id": tid, "type": "tracks", "attributes": {"title": f"Pt. {n}", "duration": "PT5M",
                                                              "mediaTags": ["HIRES_LOSSLESS"]},
                 "relationships": {"albums": {"data": [{"id": "100", "type": "albums"}]},
                                   "artists": {"data": [{"id": "7", "type": "artists"}]}}}
                for tid, n in (("1001", 1), ("1002", 2))], "included": INCLUDED})
        raise AssertionError(path)

    monkeypatch.setattr(client, "_get", fake_get)
    album = client.get_album("100")
    assert [(t.id, t.title, t.track_number, t.duration, t.album_id, t.artist) for t in album.tracks] == [
        (1001, "Pt. 1", 1, 300, "100", "Jean-Michel Jarre"), (1002, "Pt. 2", 2, 300, "100", "Jean-Michel Jarre")]
    assert album.tracks[0].cover_url == "https://img/c1/640.jpg"


def test_pages_are_followed(client, monkeypatch):
    pages = {"userCollectionAlbums/me/relationships/items": {"data": [{"id": "1", "type": "albums"}],
                                                             "links": {"next": "/next?page[cursor]=x"}},
             "/next?page[cursor]=x": {"data": [{"id": "2", "type": "albums"}], "links": {}}}
    monkeypatch.setattr(client, "_get", lambda path, params=None: tc.Document(pages[path]))
    assert client._collection_ids("albums") == ["1", "2"]


def test_artist_releases_split(client, monkeypatch):
    def album(i, kind, year):
        return {"id": i, "type": "albums", "attributes": {"title": i, "albumType": kind, "releaseDate": f"{year}-01-01"}}

    def fake_get(path, params=None):
        if path.startswith("artists/7/relationships/albums"):
            return tc.Document({"data": [{"id": x, "type": "albums"} for x in "abc"]})
        return tc.Document({"data": [album("a", "ALBUM", 1976), album("b", "SINGLE", 1977), album("c", "ALBUM", 1978)]})

    monkeypatch.setattr(client, "_get", fake_get)
    assert [a.title for a in client.get_artist_releases(7, "album")] == ["c", "a"]
    assert [a.title for a in client.get_artist_releases(7, "epSingle")] == ["b"]


def test_favorites_payload(client, monkeypatch):
    calls = []
    monkeypatch.setattr(client, "_http", lambda m, p, params=None, body=None: (calls.append((m, p, body)), (201, {}))[1])
    client._fav_ids = {"albums": set(), "tracks": set(), "artists": set()}
    client.set_favorite("artists", 7, add=True)
    client.set_favorite("albums", "100", add=False)
    assert calls == [("POST", "userCollectionArtists/me/relationships/items", {"data": [{"id": "7", "type": "artists"}]}),
                     ("DELETE", "userCollectionAlbums/me/relationships/items", {"data": [{"id": "100", "type": "albums"}]})]
    assert client.is_favorite("artists", 7) and not client.is_favorite("albums", "100")


def test_stream_drm_and_preview(client, monkeypatch):
    manifest = {"id": "1", "type": "trackManifests",
                "attributes": {"uri": "https://cdn/x.mpd", "formats": ["FLAC_HIRES"], "trackPresentation": "FULL"}}
    monkeypatch.setattr(client, "_get", lambda path, params=None: tc.Document({"data": manifest}))

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return b'<MPD><Representation audioSamplingRate="192000"/></MPD>'
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())
    info = client.get_stream_info(1)
    assert (info.url, info.mime_type, info.sample_rate, info.bit_depth, info.is_sample) == (
        "https://cdn/x.mpd", "application/dash+xml", 192000, 24, False)

    manifest["attributes"]["trackPresentation"] = "PREVIEW"
    assert client.get_stream_info(1).is_sample
    manifest["attributes"]["drmData"] = {"drmSystem": "WIDEVINE"}
    with pytest.raises(QobuzError):
        client.get_stream_info(1)


def test_audio_track_ids(client):
    from myflac.streaming.qobuz_client import QobuzTrack
    t = client.to_audio_track(QobuzTrack(id=5, title="T", artist="A", album_title="B", duration=1,
                                         track_number=1, hires=True, bit_depth=24, sample_rate=96000))
    assert t.stream_id == "tidal:5" and t.stream_service == "tidal" and t.needs_stream_url()


def test_myflac_app_is_used_by_default(tmp_path):
    """Sin configurar nada se usa la app de MyFlac (cliente público: solo Client ID, sin secreto)."""
    c = tc.TidalClient(config_path=tmp_path / "t.json")
    assert c.client_id == tc.DEFAULT_CLIENT_ID and c.has_app_credentials and not c.client_secret
    c.set_app_credentials("", "", "")  # Campos de «Avanzado» vacíos
    assert c.client_id == tc.DEFAULT_CLIENT_ID and c.redirect_uri == tc.DEFAULT_REDIRECT_URI
    url = c.authorization_url("challenge", "state")
    assert f"client_id={tc.DEFAULT_CLIENT_ID}" in url and "client_secret" not in url


def test_login_with_pkce(tmp_path, monkeypatch):
    c = tc.TidalClient(config_path=tmp_path / "t.json")
    c.set_app_credentials("cid", "", "http://localhost:18723/callback")
    seen = {}

    def fake_token(form):
        seen.update(form)
        c._tokens = tc._Tokens("access", "refresh", 9e12)

    monkeypatch.setattr(c, "_token_request", fake_token)
    monkeypatch.setattr(c, "_load_profile", lambda: None)

    def browser(url):
        # El «navegador»: TIDAL devuelve el código a la dirección local con el mismo state
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert q["code_challenge_method"] == ["S256"] and "playback" in q["scope"][0]
        threading.Thread(target=lambda: urllib.request.urlopen(
            f"http://localhost:18723/callback?code=abc&state={q['state'][0]}", timeout=5).read()).start()

    c.login_interactive(browser, timeout=10)
    assert seen["code"] == "abc" and seen["grant_type"] == "authorization_code" and seen["code_verifier"]
    assert c.is_logged_in
    assert stat.S_IMODE(c.config_path.stat().st_mode) == 0o600
    assert json.loads(c.config_path.read_text())["client_id"] == "cid"


def test_rate_limit_is_retried(client, monkeypatch):
    """HTTP 429: se espera lo que indique TIDAL y se reintenta, sin error para el usuario."""
    import io
    import urllib.error
    calls = []

    class Ok:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"data": []}'

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "0.5"}, io.BytesIO(b""))
        return Ok()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tc, "_MIN_REQUEST_INTERVAL_S", 0.0)
    sleeps = []
    monkeypatch.setattr(tc.time, "sleep", sleeps.append)
    assert client._http("GET", "albums") == (200, {"data": []})
    assert len(calls) == 3 and sleeps and all(s <= 0.6 for s in sleeps)


def test_details_are_cached(client, monkeypatch):
    calls = []

    def fake_get(path, params=None):
        calls.append(tuple(params["filter[id]"]))
        return tc.Document({"data": [{"id": i, "type": "albums", "attributes": {"title": i}} for i in params["filter[id]"]]})

    monkeypatch.setattr(client, "_get", fake_get)
    client._albums_by_ids(["1", "2"])
    client._albums_by_ids(["2", "3"])
    assert calls == [("1", "2"), ("3",)]  # El 2 ya estaba: no se vuelve a pedir


def test_preview_reason_is_kept(client, monkeypatch):
    manifest = {"id": "1", "type": "trackManifests", "attributes": {
        "uri": "https://cdn/x.mpd", "formats": ["FLAC"], "trackPresentation": "PREVIEW",
        "previewReason": "FULL_REQUIRES_HIGHER_ACCESS_TIER"}}
    monkeypatch.setattr(client, "_get", lambda path, params=None: tc.Document({"data": manifest}))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("sin red")))
    info = client.get_stream_info(1)
    assert info.is_sample and info.preview_reason == "FULL_REQUIRES_HIGHER_ACCESS_TIER"


def test_hires_without_invented_rates(client):
    """TIDAL solo dice «Hi-Res»: no se inventa la frecuencia; la real llega al reproducir."""
    from types import SimpleNamespace
    from myflac.ui.qobuz_view import QobuzView
    doc = tc.Document({"data": [ALBUM], "included": INCLUDED})
    album = client._album(doc, doc.data[0])
    assert album.hires_badge == "24-Bit Hi-Res"
    track = client._track(doc, {"id": "1", "type": "tracks", "attributes": {"mediaTags": ["HIRES_LOSSLESS"]}}, album)
    assert track.sample_rate == 0 and QobuzView._quality_str(track) == "24-Bit Hi-Res"
    audio = client.to_audio_track(track)
    assert audio.badge_full == "Hi-Res 24-bit" and audio.badge_text == "24-bit"
    audio.stream_resolver = lambda: SimpleNamespace(url="https://cdn/x.mpd", mime_type="application/dash+xml",
                                                    bit_depth=24, sample_rate=48000, is_sample=False, preview_reason="")
    audio.resolve_stream()
    assert audio.badge_full == "Hi-Res 24-bit / 48 kHz" and audio.bitrate == 48000 * 24 * 2


def test_explore_mixes_are_playlists(client, monkeypatch):
    """Las mezclas de TIDAL son listas: Novedades → discos de sus temas; Mezclas diarias → las mezclas."""
    def fake_get(path, params=None):
        if path.endswith("Mixes/me/relationships/items"):
            return tc.Document({"data": [{"id": "mixA", "type": "playlists"}, {"id": "mixB", "type": "playlists"}]})
        if path == "playlists/mixA/relationships/items":
            return tc.Document({"data": [{"id": "1001", "type": "tracks"}, {"id": "1002", "type": "tracks"}]})
        if path == "playlists/mixB/relationships/items":
            return tc.Document({"data": [{"id": "1002", "type": "tracks"}]})
        if path == "tracks":
            return tc.Document({"data": [{"id": t, "type": "tracks", "attributes": {"title": t},
                                          "relationships": {"albums": {"data": [{"id": "100", "type": "albums"}]}}}
                                         for t in params["filter[id]"]], "included": [ALBUM] + INCLUDED})
        if path == "albums":
            return tc.Document({"data": [ALBUM], "included": INCLUDED})
        if path == "playlists":
            return tc.Document({"data": [{"id": i, "type": "playlists", "attributes": {"name": f"Mix {i}", "numberOfItems": 50}}
                                         for i in params["filter[id]"]]})
        raise AssertionError(path)

    monkeypatch.setattr(client, "_get", fake_get)
    assert [a.title for a in client.get_featured_albums("new-releases")] == ["Oxygène"]
    daily = client.get_featured_albums("daily")
    assert [(m.title, m.kind) for m in daily] == [("Mix mixA", "playlist"), ("Mix mixB", "playlist")]
