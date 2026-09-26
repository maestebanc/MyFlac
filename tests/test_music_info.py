import pytest

from myflac import discogs
from myflac.audio.track import AudioTrack
from myflac.music_info import InfoCard, MusicInfoService, WikiPage, _clean_album, _clean_title, html_to_markup

TRACK = AudioTrack(filepath="/x/01.flac", title="Flume", artist="Bon Iver", album="For Emma, Forever Ago (Deluxe)")
WIKI = WikiPage(title="For Emma, Forever Ago", description="álbum de Bon Iver",
                markup="<i>For Emma, Forever Ago</i> es el primer álbum de Bon Iver.", url="https://es.wikipedia.org/wiki/For_Emma")
RELEASE = {
    "uri": "https://www.discogs.com/release/1", "year": 2007, "country": "US",
    "labels": [{"name": "Jagjaguwar (2)", "catno": "JAG115"}],
    "formats": [{"name": "CD", "descriptions": ["Album"]}],
    "notes": "Recorded in a [b]cabin[/b] in Wisconsin by [a=Justin Vernon].",
    "extraartists": [{"name": "Justin Vernon", "role": "Recorded By", "tracks": ""},
                     {"name": "Christy Smith (2)", "role": "Drums", "tracks": "1 to 3"}],
    "tracklist": [{"position": "1", "title": "Flume", "duration": "3:39", "type_": "track",
                   "extraartists": [{"name": "Justin Vernon", "role": "Vocals"}]},
                  {"position": "4", "title": "Skinny Love", "duration": "3:58", "type_": "track"}],
}
ALBUM = {"master": {"year": 2007, "genres": ["Rock"], "styles": ["Folk Rock"], "uri": "https://www.discogs.com/master/9"},
         "release": RELEASE}


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc = MusicInfoService()
    svc._cache_dir = str(tmp_path)
    monkeypatch.setattr(svc, "_download_image", lambda url: "")
    # Traducción automática simulada (sin red)
    from myflac import translate
    monkeypatch.setattr(translate.Translator, "translate", lambda self, text, target, source="en": (f"[{target}] {text}", "Google"))
    monkeypatch.setattr(svc, "_wikipedia", lambda kind, track, lang: WIKI if kind == "album" else None)
    monkeypatch.setattr(discogs, "find_master", lambda artist, album: ALBUM)
    monkeypatch.setattr(discogs, "find_artist", lambda name: {
        "uri": "https://www.discogs.com/artist/5", "profile": "American [i]indie folk[/i] band.",
        "members": [{"name": "Justin Vernon", "active": True}, {"name": "Old Member", "active": False}],
        "aliases": [{"name": "Volcano Choir (2)"}]})
    return svc


def test_album_card_combines_wikipedia_and_discogs(service):
    info = service._build("album", TRACK, "es")
    facts = dict(info.facts)
    assert info.title == "For Emma, Forever Ago" and info.markup == WIKI.markup
    assert facts["Año"] == "2007" and facts["Sello"] == "Jagjaguwar (JAG115)" and facts["Estilos"] == "Folk rock"
    sections = dict(info.sections)
    assert "<b>Grabación</b>: Justin Vernon" in sections["Créditos"]
    # Texto libre traducido automáticamente (sin el formato original) y marcado como tal
    assert sections["Notas de la edición"] == "[es] Recorded in a cabin in Wisconsin by Justin Vernon."
    assert info.translated_by == "Google"
    assert info.sources == [WIKI.url, "https://www.discogs.com/master/9"]


def test_track_card_has_track_and_album_credits(service):
    info = service._build("track", TRACK, "es")
    facts = dict(info.facts)
    assert facts["Posición"] == "1" and facts["Duración"] == "3:39" and facts["Disco"] == "For Emma, Forever Ago (2007)"
    credits = dict(info.sections)["Créditos"]
    assert "<b>Voz</b>: Justin Vernon" in credits and "<b>Batería</b>: Christy Smith" in credits


def test_artist_card_only_active_members(service):
    info = service._build("artist", TRACK, "es")
    facts = dict(info.facts)
    assert facts["Miembros"] == "Justin Vernon" and facts["Alias"] == "Volcano Choir"
    assert dict(info.sections)["Perfil en Discogs"] == "[es] American indie folk band."


def test_temporary_failures_are_not_cached(service, monkeypatch):
    def limited(artist, album):
        raise discogs.DiscogsRateLimited()
    monkeypatch.setattr(discogs, "find_master", limited)
    info = service._build("album", TRACK, "es")
    assert info.status == "ok" and info.temporary and info.markup == WIKI.markup and not info.facts


def test_nothing_found_is_empty(service, monkeypatch):
    monkeypatch.setattr(service, "_wikipedia", lambda kind, track, lang: None)
    monkeypatch.setattr(discogs, "find_master", lambda artist, album: None)
    assert service._build("album", TRACK, "es").status == "empty"


def test_discogs_markup_and_credit_ranges():
    assert discogs.discogs_to_markup("A [b]b[/b] & [l=Label (3)] [a123] [url=https://x.org]web[/url]") == \
        'A <b>b</b> &amp; Label  <a href="https://x.org">web</a>'
    assert discogs._credit_applies("A1 to B2", "A3") and discogs._credit_applies("1, 3", "3")
    assert not discogs._credit_applies("A1 to A4", "B1") and not discogs._credit_applies("", "1")


def test_cleaning_and_html():
    assert _clean_album("Bad (Deluxe Edition)") == "Bad" and _clean_title("Bad (2012 Remaster)") == "Bad"
    assert html_to_markup('<p><b>X</b> es <i>un grupo</i><sup class="reference">[1]</sup>.</p>') == "<b>X</b> es <i>un grupo</i>."


def test_obsolete_gemini_key_is_removed(tmp_path, monkeypatch):
    import json

    from myflac import config
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"language": "es", "gemini_api_key": "SECRETO"}))
    monkeypatch.setattr(config, "_config_path", lambda: str(path))
    assert "gemini_api_key" not in config.load_config()
    assert "gemini_api_key" not in json.loads(path.read_text())


def test_untranslatable_text_keeps_english_and_retries_later(service, monkeypatch):
    from myflac import translate
    monkeypatch.setattr(translate.Translator, "translate", lambda self, text, target, source="en": (None, ""))
    info = service._build("artist", TRACK, "es")
    assert dict(info.sections)["Perfil en Discogs"] == "American <i>indie folk</i> band."
    assert info.temporary and not info.translated_by
