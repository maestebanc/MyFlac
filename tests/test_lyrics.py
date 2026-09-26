from myflac.lyrics import LyricsService


def test_strip_lrc_timestamps():
    synced = "[00:12.34]First line\n[00:15.00] Second line\n[01:02]Third\n"
    assert LyricsService()._strip_lrc_timestamps(synced) == "First line\nSecond line\nThird"


def test_strip_lrc_keeps_plain_text_and_blank_lines():
    synced = "[00:01.00]Verse\n[00:02.00]\n[00:03.00]Chorus"
    assert LyricsService()._strip_lrc_timestamps(synced) == "Verse\n\nChorus"


def test_cache_key_is_case_and_whitespace_insensitive():
    svc = LyricsService()
    assert svc._get_cache_key("Queen", "Bohemian  Rhapsody") == svc._get_cache_key("queen", "bohemian rhapsody")
    assert svc._get_cache_key("Queen", "A") != svc._get_cache_key("Queen", "B")


def test_cache_round_trip_uses_xdg_cache(tmp_path):
    svc = LyricsService()
    assert svc._cache_dir.startswith(__import__("os").environ["XDG_CACHE_HOME"])
    key = svc._get_cache_key("Artist", "Title")
    svc._write_cache(key, {"lyrics": "hola", "instrumental": False})
    assert svc._read_cache(key)["lyrics"] == "hola"
