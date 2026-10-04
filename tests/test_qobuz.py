"""Cliente de Qobuz: firma, calidad real del stream, sesión guardada y URL que caducan."""
import hashlib
import stat
import time
from types import SimpleNamespace

import pytest

from myflac.audio.track import STREAM_URL_MAX_AGE_S, AudioTrack
from myflac.streaming import qobuz_client as qc


@pytest.fixture
def client(tmp_path):
    c = qc.QobuzClient(config_path=tmp_path / "qobuz.json")
    c.app_id, c.app_secret = "123456789", "s" * 32
    c.user_auth_token = "token"
    return c


def test_request_signature():
    params = {"track_id": 42, "format_id": 27, "intent": "stream"}
    expected = hashlib.md5(b"trackgetFileUrlformat_id27intentstreamtrack_id421700000000secret").hexdigest()
    assert qc.sign_request("track/getFileUrl", params, "1700000000", "secret") == expected


def test_stream_info_reports_real_quality():
    info = qc.QobuzClient.parse_stream_info(
        {"url": "https://cdn/x", "format_id": 27, "mime_type": "audio/flac", "sampling_rate": 192, "bit_depth": 24},
        27)
    assert (info.sample_rate, info.bit_depth, info.format_id, info.is_sample) == (192000, 24, 27, False)
    info = qc.QobuzClient.parse_stream_info({"url": "u", "format_id": 6, "sampling_rate": 44.1, "bit_depth": 16}, 27)
    assert (info.sample_rate, info.mime_type) == (44100, "audio/flac")
    info = qc.QobuzClient.parse_stream_info({"url": "u", "format_id": 5, "sample": True}, 27)
    assert info.mime_type == "audio/mpeg" and info.is_sample


def test_get_stream_info_requests_max_quality(client, monkeypatch):
    calls = []

    def fake_request(endpoint, params=None, **kw):
        calls.append((endpoint, params))
        return 200, {"url": "https://cdn/x", "format_id": 7, "sampling_rate": 96, "bit_depth": 24}

    monkeypatch.setattr(client, "_request", fake_request)
    info = client.get_stream_info(99)
    endpoint, params = calls[0]
    assert endpoint == "track/getFileUrl"
    assert params["format_id"] == qc.FORMAT_HIRES_192 and params["track_id"] == 99
    assert params["request_sig"] == qc.sign_request(
        "track/getFileUrl", {"format_id": 27, "intent": "stream", "track_id": 99}, params["request_ts"], client.app_secret)
    assert (info.sample_rate, info.bit_depth) == (96000, 24)


def test_expired_session_is_reported(client, monkeypatch):
    monkeypatch.setattr(client, "_request", lambda *a, **k: (401, {"message": "User authentication is required."}))
    with pytest.raises(qc.QobuzAuthError):
        client.get_stream_info(1)


def test_missing_app_credentials(tmp_path):
    c = qc.QobuzClient(config_path=tmp_path / "qobuz.json")
    c.user_auth_token = "token"
    with pytest.raises(qc.QobuzError):
        c.get_stream_info(1)
    assert c.get_featured_albums() == [] and c.last_error


def test_config_is_private(client):
    client.user_email = "yo@example.com"
    client._save_config()
    mode = stat.S_IMODE(client.config_path.stat().st_mode)
    assert mode == 0o600
    again = qc.QobuzClient(config_path=client.config_path)
    assert again.user_auth_token == "token" and again.user_email == "yo@example.com"
    assert again.has_app_credentials


def test_track_parsing(client):
    album = qc.QobuzAlbum(id="1", title="Álbum", artist="Artista", cover_url="c", release_date="2020",
                          hires=True, maximum_bit_depth=24, maximum_sampling_rate=96.0, genre_id=0)
    t = client._parse_track(
        {"id": 5, "title": "Tema", "version": "Remastered", "maximum_sampling_rate": 88.2,
         "maximum_bit_depth": 24, "hires_streamable": True, "streamable": False}, album)
    assert t.title == "Tema (Remastered)" and t.artist == "Artista"
    assert t.sample_rate == 88200 and not t.streamable


def test_audio_track_renews_stream_url(monkeypatch):
    info = SimpleNamespace(url="https://cdn/new", mime_type="audio/flac", bit_depth=24,
                           sample_rate=192000, is_sample=False)
    track = AudioTrack(filepath="", title="T", sample_rate=44100, bits_per_sample=16, is_stream=True)
    track.stream_resolver = lambda: info
    assert track.needs_stream_url()

    track.resolve_stream()
    assert track.filepath == "https://cdn/new" and not track.needs_stream_url()
    assert (track.sample_rate, track.bits_per_sample, track.stream_mime) == (192000, 24, "audio/flac")

    later = time.monotonic() + STREAM_URL_MAX_AGE_S + 1
    monkeypatch.setattr("myflac.audio.track.time.monotonic", lambda: later)
    assert track.needs_stream_url()  # Las URL firmadas caducan: se pide otra antes de usarla


def test_local_track_never_needs_stream_url():
    assert not AudioTrack(filepath="/music/a.flac", title="A").needs_stream_url()


def _fav_track(i):
    return {"id": i, "title": f"Tema {i}", "duration": 200, "maximum_bit_depth": 24,
            "maximum_sampling_rate": 96, "hires_streamable": True,
            "performer": {"name": "Jean-Michel Jarre"},
            "album": {"id": f"alb{i}", "title": "Oxygène", "image": {"large": f"https://img/{i}.jpg"},
                      "artist": {"name": "Jean-Michel Jarre"}}}


def test_favorite_tracks_are_paged_and_keep_their_album(client, monkeypatch):
    calls = []

    def fake_catalog(endpoint, params):
        calls.append(params["offset"])
        start = params["offset"]
        items = [_fav_track(i) for i in range(start, min(start + params["limit"], 3))]
        return {"tracks": {"items": items, "total": 3}}

    monkeypatch.setattr(client, "_catalog", fake_catalog)
    monkeypatch.setattr(client, "_paged", lambda e, p, k, page=2, max_items=5000:
                        qc.QobuzClient._paged(client, e, p, k, page=2, max_items=max_items))
    tracks = client.get_favorite_tracks()
    assert [t.id for t in tracks] == [0, 1, 2] and calls == [0, 2]
    t = tracks[1]
    assert (t.album_title, t.album_id, t.cover_url, t.sample_rate) == ("Oxygène", "alb1", "https://img/1.jpg", 96000)


def test_playlists_and_artists(client, monkeypatch):
    def fake_catalog(endpoint, params):
        if endpoint == "playlist/getUserPlaylists":
            return {"playlists": {"items": [{"id": 7, "name": "Para correr", "tracks_count": 2,
                                             "owner": {"name": "yo"}, "images300": ["https://img/p.jpg"]}],
                                  "total": 1}}
        if endpoint == "playlist/get" and "extra" not in params:
            return {"id": 7, "name": "Para correr", "tracks_count": 2, "owner": {"name": "yo"}}
        if endpoint == "playlist/get":
            return {"tracks": {"items": [_fav_track(1), _fav_track(2)], "total": 2}}
        if endpoint == "favorite/getUserFavorites":
            return {"artists": {"items": [{"id": 5, "name": "Vangelis", "albums_count": 40,
                                           "image": {"large": "https://img/v.jpg"}}], "total": 1}}
        raise AssertionError(endpoint)

    monkeypatch.setattr(client, "_catalog", fake_catalog)
    (pl,) = client.get_user_playlists()
    assert (pl.kind, pl.title, pl.artist, pl.tracks_count, pl.cover_url) == (
        "playlist", "Para correr", "yo", 2, "https://img/p.jpg")
    full = client.get_playlist("7")
    assert [t.title for t in full.tracks] == ["Tema 1", "Tema 2"]
    (artist,) = client.get_favorite_artists()
    assert (artist.name, artist.albums_count, artist.image_url) == ("Vangelis", 40, "https://img/v.jpg")


def test_artist_releases_are_split_by_type(client, monkeypatch):
    calls = []

    def fake_catalog(endpoint, params):
        calls.append((endpoint, params.get("release_type"), params.get("offset")))
        assert endpoint == "artist/getReleasesList"
        if params["release_type"] == "album":
            first = params["offset"] == 0
            items = [{"id": "a1" if first else "a2", "title": "Oxygène" if first else "Équinoxe",
                      "artist": {"name": {"display": "Jean-Michel Jarre"}},  # formato nuevo de la API
                      "dates": {"original": "1976-12-05"}, "audio_info": {"maximum_bit_depth": 24,
                      "maximum_sampling_rate": 96}, "rights": {"hires_streamable": True}}]
            return {"items": items, "has_more": first}
        return {"items": [{"id": "s1", "title": "Oxygène 4", "artist": {"name": "Jean-Michel Jarre"}}],
                "has_more": False}

    monkeypatch.setattr(client, "_catalog", fake_catalog)
    albums = client.get_artist_releases(5, "album")
    assert [a.title for a in albums] == ["Oxygène", "Équinoxe"]
    a = albums[0]
    assert (a.artist, a.release_date, a.hires, a.maximum_bit_depth, a.maximum_sampling_rate) == (
        "Jean-Michel Jarre", "1976", True, 24, 96.0)
    assert [a.title for a in client.get_artist_releases(5, "epSingle")] == ["Oxygène 4"]
    assert calls[0][1:] == ("album", 0) and calls[1][1:] == ("album", 1)  # sigue tras lo recibido


def test_artist_releases_fallback_classifies_full_discography(client, monkeypatch):
    def fake_catalog(endpoint, params):
        if endpoint == "artist/getReleasesList":
            return None  # Sin la lista por tipos
        return {"albums": {"items": [
            {"id": "1", "title": "Oxygène", "release_type": "album"},
            {"id": "2", "title": "Oxygène 4", "release_type": "single"},
            {"id": "3", "title": "Live in Houston", "release_type": "live"},
        ]}}

    monkeypatch.setattr(client, "_catalog", fake_catalog)
    assert [a.title for a in client.get_artist_releases(5, "album")] == ["Oxygène"]
    assert [a.title for a in client.get_artist_releases(5, "epSingle")] == ["Oxygène 4"]
    assert [a.title for a in client.get_artist_releases(5, "live")] == ["Live in Houston"]


def test_add_and_remove_favorites(client, monkeypatch):
    calls = []

    def fake_request(endpoint, params=None, form=None, **kw):
        calls.append((endpoint, form))
        if endpoint == "favorite/getUserFavoriteIds":
            return 200, {"albums": ["a1"], "tracks": [11], "artists": [5]}
        return 200, {"status": "success"}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.is_favorite("albums", "a1") is None  # Aún sin cargar
    client.load_favorite_ids()
    assert client.is_favorite("albums", "a1") and client.is_favorite("tracks", 11)
    assert not client.is_favorite("artists", 6)

    client.set_favorite("artists", 6, add=True)
    client.set_favorite("tracks", 11, add=False)
    assert calls[-2] == ("favorite/create", {"artist_ids": "6"})
    assert calls[-1] == ("favorite/delete", {"track_ids": "11"})
    assert client.is_favorite("artists", 6) and not client.is_favorite("tracks", 11)


def test_favorite_error_is_reported(client, monkeypatch):
    monkeypatch.setattr(client, "_request", lambda *a, **k: (400, {"status": "error", "message": "Invalid"}))
    with pytest.raises(qc.QobuzError):
        client.set_favorite("albums", "x", add=True)


def test_audio_track_carries_qobuz_id(client):
    t = qc.QobuzTrack(id=42, title="T", artist="A", album_title="B", duration=1, track_number=1,
                      hires=False, bit_depth=16, sample_rate=44100)
    assert client.to_audio_track(t).stream_id == "qobuz:42"


def test_artist_ids_and_artist_search(client, monkeypatch):
    def fake_catalog(endpoint, params):
        if params.get("type") == "artists":
            return {"artists": {"items": [{"id": 9, "name": "Zazie", "albums_count": 121}]}}
        return {"albums": {"items": [{"id": "z1", "title": "Zen", "artist": {"id": 9, "name": "Zazie"}}]}}

    monkeypatch.setattr(client, "_catalog", fake_catalog)
    (artist,) = client.search_artists("zazie")
    assert (artist.id, artist.name) == (9, "Zazie")
    (album,) = client.search_catalog("zazie")
    assert album.artist_id == 9
    t = client._parse_track({"id": 1, "title": "x", "album": {"id": "z1", "artist": {"id": 9, "name": "Zazie"}}})
    assert t.artist_id == 9


def test_booklets_from_goodies():
    goodies = [
        {"name": "Livret Numérique", "file_format_id": 21,
         "original_url": "https://static.qobuz.com/goodies/12/000123.pdf", "url": "https://x/123"},
        {"name": "Vídeo", "file_format_id": 5, "url": "https://x/video.mp4"},
        {"description": "Partitura", "url": "https://static.qobuz.com/goodies/score.PDF?x=1"},
    ]
    booklets = qc.parse_booklets(goodies)
    assert [(b.name, b.url) for b in booklets] == [
        ("Livret Numérique", "https://static.qobuz.com/goodies/12/000123.pdf"),
        ("Partitura", "https://static.qobuz.com/goodies/score.PDF?x=1"),
    ]
    assert qc.parse_booklets(None) == []


def test_album_includes_booklets(client, monkeypatch):
    monkeypatch.setattr(client, "_catalog", lambda e, p: {
        "id": "a1", "title": "Oxygène", "artist": {"name": "JMJ"}, "tracks": {"items": []},
        "goodies": [{"name": "Livret", "file_format_id": 21, "url": "https://s/1.pdf"}]})
    assert [b.url for b in client.get_album("a1").booklets] == ["https://s/1.pdf"]
