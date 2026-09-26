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


def test_parse_lrc_basic_and_sorted():
    from myflac.lyrics import parse_lrc

    lrc = "[ar:Queen]\n[ti:Song]\n[00:12.50]Second\n[00:01.00]First\n[01:02.345]Third"
    assert parse_lrc(lrc) == [(1.0, "First"), (12.5, "Second"), (62.345, "Third")]


def test_parse_lrc_multiple_stamps_blank_lines_and_offset():
    from myflac.lyrics import parse_lrc

    lrc = "[offset:+500]\n[00:10.00][00:30.00]Chorus\n[00:20.00]\n"
    assert parse_lrc(lrc) == [(9.5, "Chorus"), (19.5, ""), (29.5, "Chorus")]


def test_parse_lrc_without_timestamps_returns_none():
    from myflac.lyrics import parse_lrc

    assert parse_lrc("Just plain text\nno times") is None
    assert parse_lrc("") is None
    assert parse_lrc(None) is None


def test_best_search_result_prefers_synced_with_matching_duration():
    from myflac.lyrics import _best_search_result

    results = [
        {"id": 1, "duration": 240, "syncedLyrics": "[00:01.00]a"},   # otra edición
        {"id": 2, "duration": 181, "plainLyrics": "a"},
        {"id": 3, "duration": 180, "syncedLyrics": "[00:01.00]a"},
    ]
    assert _best_search_result(results, 180.4)["id"] == 3


def test_lrclib_entry_keeps_synced_lyrics():
    svc = LyricsService()
    plain, status, synced = svc._lrclib_entry_to_result({"syncedLyrics": "[00:01.00]Hola\n[00:02.00]Adiós"})
    assert (plain, status) == ("Hola\nAdiós", "ready")
    assert synced.startswith("[00:01.00]")
    assert svc._lrclib_entry_to_result({"instrumental": True}) == (None, "instrumental", None)
