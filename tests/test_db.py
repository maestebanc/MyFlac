import pytest

from myflac.audio.track import AudioTrack
from myflac.library.db import LibraryDB


@pytest.fixture
def db(tmp_path):
    return LibraryDB(str(tmp_path / "library.db"))


def _track(path, title, artist, album, number):
    return AudioTrack(filepath=path, title=title, artist=artist, album=album, track_number=number)


def test_folders_add_and_remove_cascades_tracks(db, tmp_path):
    folder = str(tmp_path / "music")
    assert db.add_library_folder(folder)
    db.upsert_tracks([_track(f"{folder}/a.flac", "A", "X", "Album", 1)], folder_path=folder)
    assert db.get_library_folders() == [folder]

    assert db.remove_library_folder(folder)
    assert db.get_library_folders() == []
    assert db.get_tracks() == []


def test_upsert_is_idempotent_and_updates(db, tmp_path):
    path = str(tmp_path / "a.flac")
    db.upsert_tracks([_track(path, "Old", "X", "Album", 1)])
    db.upsert_tracks([_track(path, "New", "X", "Album", 1)])
    tracks = db.get_tracks()
    assert len(tracks) == 1
    assert tracks[0].title == "New"


def test_artists_albums_and_search(db, tmp_path):
    db.upsert_tracks([
        _track(str(tmp_path / "1.flac"), "One", "Queen", "A Night at the Opera", 1),
        _track(str(tmp_path / "2.flac"), "Two", "Queen", "A Night at the Opera", 2),
        _track(str(tmp_path / "3.flac"), "Three", "Björk", "Homogenic", 1),
    ])
    artists = dict(db.get_artists())
    assert artists == {"Björk": 1, "Queen": 2}

    albums = [a[0] for a in db.get_albums(artist_filter="Queen")]
    assert albums == ["A Night at the Opera"]

    assert [a for a, _ in db.get_artists(search_query="homo")] == ["Björk"]


def test_delete_tracks_by_paths(db, tmp_path):
    paths = [str(tmp_path / f"{i}.flac") for i in range(3)]
    db.upsert_tracks([_track(p, p, "X", "Y", i) for i, p in enumerate(paths)])
    assert db.delete_tracks_by_paths(paths[:2]) == 2
    assert [t.filepath for t in db.get_tracks()] == [paths[2]]


def test_metadata_version_upgrade_rereads_unchanged_files(db, tmp_path, make_flac):
    import os

    from myflac.audio.track import METADATA_VERSION
    from myflac.library.scanner import LibraryScanner

    folder = tmp_path / "lib"
    path = make_flac(name="song.flac", subdir="lib", tags={"title": "Real", "artist": "Artista"})
    db.add_library_folder(str(folder))
    # Fila guardada por un lector antiguo: mismo mtime y tamaño, pero sin artista
    db.upsert_tracks([AudioTrack(filepath=path, title="song", artist="", album="", file_size_bytes=os.path.getsize(path))])
    assert db.get_metadata_version() == 0

    scanner = LibraryScanner(db)
    scanner._run_scan([str(folder)], quick=True, on_progress=None)
    track = db.get_tracks()[0]
    assert (track.title, track.artist) == ("Real", "Artista")
    assert db.get_metadata_version() == METADATA_VERSION

    # Ya actualizada, un escaneo rápido vuelve a saltarse los archivos sin cambios
    db.upsert_tracks([AudioTrack(filepath=path, title="song", artist="", album="", file_size_bytes=os.path.getsize(path))])
    scanner._run_scan([str(folder)], quick=True, on_progress=None)
    assert db.get_tracks()[0].artist == ""


def test_full_scan_purges_deleted_files(db, tmp_path, make_flac):
    import os

    from myflac.library.scanner import LibraryScanner

    folder = tmp_path / "lib"
    keep = make_flac(name="keep.flac", subdir="lib")
    gone = make_flac(name="gone.flac", subdir="lib")
    scanner = LibraryScanner(db)
    scanner._run_scan([str(folder)], quick=False, on_progress=None)
    os.remove(gone)
    scanner._run_scan([str(folder)], quick=False, on_progress=None)
    assert [t.filepath for t in db.get_tracks()] == [keep]
