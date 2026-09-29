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


def test_cover_lookup_is_cached_even_when_missing(tmp_path, monkeypatch):
    # Regresión: en una unidad de red cada búsqueda fallida repetía mutagen + 9 accesos a la carpeta
    from myflac.audio.track import AudioTrack
    import myflac.audio.track as track_module

    track = AudioTrack(filepath=str(tmp_path / "sin-portada.dsf"))
    assert track.cached_cover() is None and not track.cover_loaded
    assert track.get_cover_image_bytes() is None
    assert track.cover_loaded

    calls = []
    monkeypatch.setattr(track_module.os.path, "isfile", lambda p: calls.append(p) or False)
    assert track.get_cover_image_bytes() is None
    assert calls == []  # Segunda consulta: sin tocar el disco


def test_folder_cover_is_found_and_served_from_memory(tmp_path):
    from myflac.audio.track import AudioTrack

    (tmp_path / "front.jpg").write_bytes(b"\xff\xd8jpeg")
    track = AudioTrack(filepath=str(tmp_path / "01.dsf"))
    assert track.get_cover_image_bytes() == (b"\xff\xd8jpeg", "image/jpeg")
    assert track.cached_cover() == (b"\xff\xd8jpeg", "image/jpeg")
