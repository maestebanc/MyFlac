from myflac.audio.track import load_track


def test_load_untagged_flac_does_not_crash(make_flac):
    # Regresión: sin etiqueta 'title', mutagen lanzaba ValueError con la clave MP4 '©nam'
    path = make_flac(name="03 - Intro.flac", subdir="Artista - Disco")
    track = load_track(path)
    assert track is not None
    assert track.title == "Intro"
    assert track.track_number == 3
    assert track.album == "Disco"
    assert track.artist == "Artista"


def test_load_tagged_hires_flac(make_flac):
    path = make_flac(rate=96000, fmt="S24_32LE", tags={"title": "Tema", "artist": "Grupo", "album": "LP"})
    track = load_track(path)
    assert (track.title, track.artist, track.album) == ("Tema", "Grupo", "LP")
    assert track.sample_rate == 96000
    assert track.bits_per_sample == 24
    assert track.is_hires


def test_load_missing_file_returns_none(tmp_path):
    assert load_track(str(tmp_path / "missing.flac")) is None
