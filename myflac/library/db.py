"""Gestor de base de datos SQLite para la Biblioteca Musical de MyFlac."""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

from ..audio.track import AudioTrack
from ..logger import get_logger

log = get_logger("library.db")


def get_default_db_path() -> str:
    """Devuelve la ruta estándar de la base de datos de la biblioteca."""
    data_dir = os.path.join(GLib.get_user_data_dir(), "myflac")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "library.db")


class LibraryDB:
    """Gestor de persistencia SQLite para pistas, artistas, álbumes y carpetas de biblioteca."""

    def __init__(self, db_path: str | None = None):
        raw_path = db_path or get_default_db_path()
        if raw_path == ":memory:":
            self.db_path = f"file:memdb_{id(self)}?mode=memory&cache=shared"
            self._uri = True
            self._mem_conn = sqlite3.connect(self.db_path, uri=True, check_same_thread=False)
        else:
            self.db_path = raw_path
            self._uri = False
            self._mem_conn = None
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, uri=self._uri, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if not self._uri:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS library_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    file_size INTEGER NOT NULL,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    album_artist TEXT,
                    date TEXT,
                    genre TEXT,
                    track_number INTEGER,
                    track_total INTEGER,
                    disc_number INTEGER,
                    duration REAL DEFAULT 0.0,
                    bitrate INTEGER DEFAULT 0,
                    sample_rate INTEGER DEFAULT 44100,
                    bits_per_sample INTEGER DEFAULT 16,
                    channels INTEGER DEFAULT 2,
                    format_name TEXT DEFAULT 'FLAC',
                    has_cover INTEGER DEFAULT 0,
                    folder_path TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tracks_filepath ON tracks(filepath);
                CREATE INDEX IF NOT EXISTS idx_tracks_album_artist ON tracks(album_artist);
                CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
                CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album);
                CREATE INDEX IF NOT EXISTS idx_tracks_folder ON tracks(folder_path);
            """)
        log.info("Base de datos inicializada en: %s", self.db_path)

    # -------------------------------------------------------------------------
    # Gestión de carpetas de biblioteca
    # -------------------------------------------------------------------------
    def get_library_folders(self) -> list[str]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT path FROM library_folders ORDER BY path ASC;")
            return [row["path"] for row in cur.fetchall()]

    def add_library_folder(self, path: str) -> bool:
        norm_path = os.path.abspath(path)
        with self._lock, self._get_connection() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO library_folders (path) VALUES (?);",
                    (norm_path,),
                )
                log.info("Carpeta añadida a la biblioteca: %s", norm_path)
                return True
            except Exception as e:
                log.error("Error al añadir carpeta a biblioteca: %s", e)
                return False

    def remove_library_folder(self, path: str) -> bool:
        norm_path = os.path.abspath(path)
        with self._lock, self._get_connection() as conn:
            try:
                conn.execute("DELETE FROM library_folders WHERE path = ?;", (norm_path,))
                # Eliminar pistas asociadas a esa carpeta
                conn.execute(
                    "DELETE FROM tracks WHERE folder_path = ? OR filepath LIKE ? || '/%';",
                    (norm_path, norm_path),
                )
                log.info("Carpeta y pistas eliminadas de la biblioteca: %s", norm_path)
                return True
            except Exception as e:
                log.error("Error al eliminar carpeta de biblioteca: %s", e)
                return False

    # -------------------------------------------------------------------------
    # Caché y Sincronización Ultrarrápida
    # -------------------------------------------------------------------------
    def get_file_cache(self) -> dict[str, tuple[float, int]]:
        """Devuelve {filepath: (mtime, file_size)} para comparación instantánea."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT filepath, mtime, file_size FROM tracks;")
            return {row["filepath"]: (row["mtime"], row["file_size"]) for row in cur.fetchall()}

    def upsert_tracks(self, tracks: list[AudioTrack], folder_path: str = "") -> int:
        """Inserta o actualiza un lote de pistas en la base de datos."""
        if not tracks:
            return 0

        rows = []
        for t in tracks:
            try:
                mtime = os.path.getmtime(t.filepath)
            except OSError:
                mtime = 0.0

            rows.append((
                t.filepath,
                t.filename,
                mtime,
                t.file_size_bytes,
                t.title,
                t.artist,
                t.album,
                t.album_artist,
                t.date,
                t.genre,
                t.track_number,
                t.track_total,
                t.disc_number,
                t.duration,
                t.bitrate,
                t.sample_rate,
                t.bits_per_sample,
                t.channels,
                t.format_name,
                1 if (t.cover_data or t.get_cover_image_bytes()) else 0,
                folder_path or os.path.dirname(t.filepath),
            ))

        sql = """
            INSERT INTO tracks (
                filepath, filename, mtime, file_size, title, artist, album,
                album_artist, date, genre, track_number, track_total, disc_number,
                duration, bitrate, sample_rate, bits_per_sample, channels,
                format_name, has_cover, folder_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filepath) DO UPDATE SET
                filename=excluded.filename,
                mtime=excluded.mtime,
                file_size=excluded.file_size,
                title=excluded.title,
                artist=excluded.artist,
                album=excluded.album,
                album_artist=excluded.album_artist,
                date=excluded.date,
                genre=excluded.genre,
                track_number=excluded.track_number,
                track_total=excluded.track_total,
                disc_number=excluded.disc_number,
                duration=excluded.duration,
                bitrate=excluded.bitrate,
                sample_rate=excluded.sample_rate,
                bits_per_sample=excluded.bits_per_sample,
                channels=excluded.channels,
                format_name=excluded.format_name,
                has_cover=excluded.has_cover,
                folder_path=excluded.folder_path;
        """

        with self._lock, self._get_connection() as conn:
            conn.executemany(sql, rows)

        log.debug("Upsert completado para %d pistas", len(rows))
        return len(rows)

    def delete_tracks_by_paths(self, filepaths: list[str]) -> int:
        if not filepaths:
            return 0
        with self._lock, self._get_connection() as conn:
            # En bloques de 500 para evitar límites de parámetros SQLite
            count = 0
            for i in range(0, len(filepaths), 500):
                batch = filepaths[i : i + 500]
                placeholders = ",".join("?" * len(batch))
                cur = conn.execute(
                    f"DELETE FROM tracks WHERE filepath IN ({placeholders});",
                    batch,
                )
                count += cur.rowcount
            log.info("Eliminadas %d pistas huérfanas de la base de datos", count)
            return count

    def clear_database(self) -> None:
        """Restablece la base de datos a cero (borra todas las pistas indexadas)."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM tracks;")
                conn.isolation_level = None
                conn.execute("VACUUM;")
            finally:
                conn.close()
        log.info("Base de datos de pistas restablecida a cero")

    # -------------------------------------------------------------------------
    # Consultas para el Navegador Multicolumnas estilo iTunes
    # -------------------------------------------------------------------------
    def get_artists(self, search_query: str = "") -> list[tuple[str, int]]:
        """
        Devuelve lista de (display_artist, track_count).
        Regla: usa album_artist si existe; en su defecto artist; fallback 'Desconocido'.
        """
        sql = """
            SELECT
                COALESCE(NULLIF(album_artist, ''), NULLIF(artist, ''), 'Desconocido') AS disp_artist,
                COUNT(*) AS track_count
            FROM tracks
        """
        params: list[Any] = []
        if search_query:
            sql += " WHERE (title LIKE ? OR artist LIKE ? OR album LIKE ? OR album_artist LIKE ?)"
            q = f"%{search_query}%"
            params.extend([q, q, q, q])

        sql += """
            GROUP BY disp_artist
            ORDER BY disp_artist COLLATE NOCASE ASC;
        """

        with self._lock, self._get_connection() as conn:
            cur = conn.execute(sql, params)
            return [(row["disp_artist"], row["track_count"]) for row in cur.fetchall()]

    def get_albums(self, artist_filter: str | None = None, search_query: str = "") -> list[tuple[str, str, int]]:
        """
        Devuelve lista de (album_name, year, track_count).
        Si artist_filter no es None (y no es 'ALL'/'TODOS'), filtra por el artista del álbum correspondiente.
        """
        sql = """
            SELECT
                COALESCE(NULLIF(album, ''), 'Sin Álbum') AS disp_album,
                COALESCE(MAX(date), '') AS disp_year,
                COUNT(*) AS track_count
            FROM tracks
            WHERE 1=1
        """
        params: list[Any] = []

        if artist_filter and artist_filter != "__ALL__":
            sql += " AND COALESCE(NULLIF(album_artist, ''), NULLIF(artist, ''), 'Desconocido') = ?"
            params.append(artist_filter)

        if search_query:
            sql += " AND (title LIKE ? OR artist LIKE ? OR album LIKE ? OR album_artist LIKE ?)"
            q = f"%{search_query}%"
            params.extend([q, q, q, q])

        sql += """
            GROUP BY disp_album
            ORDER BY disp_album COLLATE NOCASE ASC;
        """

        with self._lock, self._get_connection() as conn:
            cur = conn.execute(sql, params)
            return [(row["disp_album"], row["disp_year"], row["track_count"]) for row in cur.fetchall()]

    def get_tracks(
        self,
        artist_filter: str | None = None,
        album_filter: str | None = None,
        search_query: str = "",
    ) -> list[AudioTrack]:
        """
        Obtiene las pistas que coinciden con los filtros del navegador de columnas.
        """
        sql = "SELECT * FROM tracks WHERE 1=1"
        params: list[Any] = []

        if artist_filter and artist_filter != "__ALL__":
            sql += " AND COALESCE(NULLIF(album_artist, ''), NULLIF(artist, ''), 'Desconocido') = ?"
            params.append(artist_filter)

        if album_filter and album_filter != "__ALL__":
            if album_filter == "Sin Álbum":
                sql += " AND (album IS NULL OR album = '')"
            else:
                sql += " AND album = ?"
                params.append(album_filter)

        if search_query:
            sql += " AND (title LIKE ? OR artist LIKE ? OR album LIKE ? OR album_artist LIKE ? OR filename LIKE ?)"
            q = f"%{search_query}%"
            params.extend([q, q, q, q, q])

        sql += """
            ORDER BY
                COALESCE(NULLIF(album_artist, ''), NULLIF(artist, ''), '') COLLATE NOCASE ASC,
                album COLLATE NOCASE ASC,
                COALESCE(disc_number, 1) ASC,
                COALESCE(track_number, 9999) ASC,
                filename COLLATE NOCASE ASC;
        """

        tracks: list[AudioTrack] = []
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(sql, params)
            for row in cur.fetchall():
                t = AudioTrack(
                    filepath=row["filepath"],
                    filename=row["filename"],
                    title=row["title"] or "",
                    artist=row["artist"] or "",
                    album=row["album"] or "",
                    album_artist=row["album_artist"] or "",
                    date=row["date"] or "",
                    genre=row["genre"] or "",
                    track_number=row["track_number"],
                    track_total=row["track_total"],
                    disc_number=row["disc_number"],
                    duration=row["duration"] or 0.0,
                    bitrate=row["bitrate"] or 0,
                    sample_rate=row["sample_rate"] or 44100,
                    bits_per_sample=row["bits_per_sample"] or 16,
                    channels=row["channels"] or 2,
                    format_name=row["format_name"] or "FLAC",
                    file_size_bytes=row["file_size"] or 0,
                )
                tracks.append(t)
        return tracks

    def get_stats(self) -> dict[str, Any]:
        """Estadísticas globales de la biblioteca."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_tracks,
                    COUNT(DISTINCT COALESCE(NULLIF(album_artist, ''), NULLIF(artist, ''), 'Desconocido')) as total_artists,
                    COUNT(DISTINCT album) as total_albums,
                    COALESCE(SUM(duration), 0.0) as total_duration,
                    COUNT(CASE WHEN bits_per_sample >= 24 OR sample_rate >= 48000 OR format_name = 'DSD' THEN 1 END) as hires_tracks
                FROM tracks;
            """).fetchone()

            return {
                "total_tracks": row["total_tracks"],
                "total_artists": row["total_artists"],
                "total_albums": row["total_albums"],
                "total_duration": row["total_duration"],
                "hires_tracks": row["hires_tracks"],
            }
