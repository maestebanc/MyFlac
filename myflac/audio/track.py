"""Modelo de pista de audio y extracción de metadatos audiófilos."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
import mutagen
from mutagen.flac import FLAC

from ..constants import COVER_FILENAMES, HIRES_MIN_BIT_DEPTH, HIRES_MIN_SAMPLE_RATE
from ..logger import get_logger

log = get_logger("audio.track")


@dataclass
class AudioTrack:
    filepath: str
    filename: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    date: str = ""
    genre: str = ""
    track_number: int | None = None
    track_total: int | None = None
    disc_number: int | None = None
    duration: float = 0.0  # en segundos
    bitrate: int = 0  # en bps (ej. 2611107)
    sample_rate: int = 44100
    bits_per_sample: int = 16
    channels: int = 2
    format_name: str = "FLAC"
    file_size_bytes: int = 0
    cover_data: bytes | None = field(default=None, repr=False)
    cover_mime: str = ""

    def __post_init__(self):
        if not self.filename and self.filepath:
            self.filename = os.path.basename(self.filepath)

    @property
    def is_hires(self) -> bool:
        """Determina si la pista cumple los estándares de audio de alta resolución."""
        return (
            self.bits_per_sample >= HIRES_MIN_BIT_DEPTH
            or self.sample_rate >= HIRES_MIN_SAMPLE_RATE
            or "DSD" in self.format_name.upper()
        )

    @property
    def badge_text(self) -> str:
        """Etiqueta compacta con especificaciones de audio (ej: '24/88.2k')."""
        if "DSD" in self.format_name.upper():
            return "DSD"
        rate_str = f"{self.sample_rate / 1000:g}k"
        if self.bits_per_sample > 0:
            return f"{self.bits_per_sample}/{rate_str}"
        return rate_str

    @property
    def badge_full(self) -> str:
        """Etiqueta descriptiva para el inspector (ej: 'Hi-Res 24-bit / 88.2 kHz')."""
        rate_str = f"{self.sample_rate / 1000:g} kHz"
        if self.is_hires:
            return f"Hi-Res {self.bits_per_sample}-bit / {rate_str}"
        if self.sample_rate == 44100 and self.bits_per_sample == 16:
            return "Calidad CD 16-bit / 44.1 kHz"
        return f"{self.bits_per_sample}-bit / {rate_str}"

    @property
    def formatted_duration(self) -> str:
        """Duración formateada mm:ss o hh:mm:ss."""
        total_sec = int(round(self.duration))
        hrs = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        if hrs > 0:
            return f"{hrs}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    @property
    def formatted_bitrate(self) -> str:
        """Tasa de bits en kbps."""
        if self.bitrate > 0:
            return f"{int(round(self.bitrate / 1000))} kbps"
        return "VBR"

    @property
    def formatted_file_size(self) -> str:
        """Tamaño de archivo en MB o KB."""
        if self.file_size_bytes <= 0:
            return ""
        mb = self.file_size_bytes / (1024 * 1024)
        if mb >= 1.0:
            return f"{mb:.1f} MB"
        kb = self.file_size_bytes / 1024
        return f"{kb:.0f} KB"

    def get_cover_image_bytes(self) -> tuple[bytes, str] | None:
        """Obtiene los bytes de carátula embebida o archivo local en el directorio."""
        if self.cover_data:
            return self.cover_data, self.cover_mime

        # 1. Si no está en memoria, extraer carátula embebida directamente del archivo de audio
        if self.filepath and os.path.isfile(self.filepath):
            try:
                audio = mutagen.File(self.filepath)
                if isinstance(audio, FLAC) and audio.pictures:
                    pic = audio.pictures[0]
                    self.cover_data = pic.data
                    self.cover_mime = pic.mime or "image/jpeg"
                    return self.cover_data, self.cover_mime
                elif hasattr(audio, "tags") and audio.tags:
                    for k, v in audio.tags.items():
                        if k.startswith("APIC") and hasattr(v, "data"):
                            self.cover_data = v.data
                            self.cover_mime = getattr(v, "mime", "image/jpeg")
                            return self.cover_data, self.cover_mime
                        elif k == "covr" and isinstance(v, list) and v:
                            covr_item = v[0]
                            self.cover_data = bytes(covr_item)
                            img_fmt = getattr(covr_item, "imageformat", None)
                            self.cover_mime = "image/png" if img_fmt == getattr(mutagen.mp4.MP4Cover, "FORMAT_PNG", 14) else "image/jpeg"
                            return self.cover_data, self.cover_mime
                    if "metadata_block_picture" in audio.tags:
                        mbp = audio.tags.get("metadata_block_picture")
                        if mbp:
                            try:
                                from mutagen.flac import Picture
                                raw_b64 = mbp[0] if isinstance(mbp, list) else mbp
                                pic = Picture(base64.b64decode(raw_b64))
                                self.cover_data = pic.data
                                self.cover_mime = pic.mime or "image/jpeg"
                                return self.cover_data, self.cover_mime
                            except Exception:
                                pass
            except Exception as e:
                log.debug("No se pudo extraer carátula embebida de %s: %s", self.filepath, e)

        # 2. Buscar carátula en la misma carpeta si no está embebida
        folder = os.path.dirname(self.filepath)
        for fname in COVER_FILENAMES:
            candidate = os.path.join(folder, fname)
            if os.path.isfile(candidate):
                try:
                    with open(candidate, "rb") as f:
                        data = f.read()
                    mime = "image/png" if fname.endswith(".png") else "image/jpeg"
                    self.cover_data = data
                    self.cover_mime = mime
                    return data, mime
                except Exception:
                    pass
        return None


import base64
import re


def _clean_tag(val: any) -> str:
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else ""
    return str(val).strip()


def _parse_track_number(val: any) -> tuple[int | None, int | None]:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return int(val[0]), int(val[1])
        except (ValueError, TypeError):
            pass
    s = _clean_tag(val)
    if not s:
        return None, None
    if "/" in s:
        p1, p2 = s.split("/", 1)
        try:
            return int(p1), int(p2)
        except ValueError:
            return None, None
    try:
        return int(s), None
    except ValueError:
        return None, None


def _infer_metadata_from_path(
    filepath: str,
    base_name: str,
    title: str = "",
    artist: str = "",
    album: str = "",
    track_num: int | None = None,
) -> tuple[str, str, str, int | None]:
    """Infiere metadatos de título, artista, álbum y pista a partir del nombre de archivo y carpeta."""
    m_num = re.match(r"^(\d{1,3})[\s._-]+(.+)$", base_name)
    if m_num:
        if track_num is None:
            try:
                track_num = int(m_num.group(1))
            except ValueError:
                pass
        rest = m_num.group(2).strip()
    else:
        rest = base_name.strip()

    if " - " in rest:
        parts = rest.split(" - ", 1)
        if not artist:
            artist = parts[0].strip()
        if not title or title == base_name:
            title = parts[1].strip()
    elif not title or title == base_name:
        title = rest

    if not title:
        title = base_name

    if not album:
        folder_name = os.path.basename(os.path.dirname(filepath))
        if folder_name and folder_name not in ("/", ".", ""):
            if " - " in folder_name:
                f_parts = folder_name.split(" - ", 1)
                if not artist:
                    artist = f_parts[0].strip()
                album = f_parts[1].strip()
            else:
                album = folder_name

    return title, artist, album, track_num


def load_track(filepath: str) -> AudioTrack | None:
    """Carga y analiza un archivo de audio extrayendo metadatos y especificaciones técnicas."""
    if not os.path.isfile(filepath):
        return None

    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        file_size = 0

    filename = os.path.basename(filepath)
    base_name, ext = os.path.splitext(filename)
    fmt = ext.lstrip(".").upper()

    try:
        audio = mutagen.File(filepath)
    except Exception:
        audio = None

    if audio is None:
        title, artist, album, track_num = _infer_metadata_from_path(filepath, base_name)
        return AudioTrack(
            filepath=filepath,
            filename=filename,
            title=title,
            artist=artist,
            album=album,
            track_number=track_num,
            file_size_bytes=file_size,
            format_name=fmt or "FLAC",
        )

    info = getattr(audio, "info", None)
    duration = getattr(info, "length", 0.0) or 0.0
    sample_rate = getattr(info, "sample_rate", 44100) or 44100
    channels = getattr(info, "channels", 2) or 2
    bits_per_sample = getattr(info, "bits_per_sample", 16) or 16
    bitrate = getattr(info, "bitrate", 0) or 0

    # Si es DSD (dsf o dff)
    if ext.lower() in (".dsf", ".dff"):
        fmt = "DSD"
        bits_per_sample = 1

    # Extraer tags
    tags = getattr(audio, "tags", None) or {}

    def get_tag(*keys: str) -> str:
        for k in keys:
            for variant in (k, k.upper(), k.lower()):
                try:
                    v = tags.get(variant)
                except ValueError:
                    # Las claves Vorbis solo admiten ASCII: mutagen rechaza claves MP4 como '©nam'
                    continue
                if v:
                    return _clean_tag(v)
        return ""

    # 1. Título
    # Vorbis: title | ID3: TIT2 | MP4: ©nam | RIFF: INAM
    title = get_tag("title", "TIT2", "\xa9nam", "INAM")

    # 2. Artista
    # Vorbis: artist | ID3: TPE1 | MP4: ©ART | RIFF: IART
    artist = get_tag("artist", "TPE1", "\xa9ART", "IART")

    # 3. Álbum
    # Vorbis: album | ID3: TALB | MP4: ©alb | RIFF: IPRD
    album = get_tag("album", "TALB", "\xa9alb", "IPRD")

    # 4. Artista del Álbum
    # Vorbis: albumartist | ID3: TPE2 | MP4: aART
    album_artist = get_tag("albumartist", "album artist", "band", "TPE2", "aART")

    # 5. Año / Fecha
    # Vorbis: date, year | ID3: TDRC, TYER | MP4: ©day | RIFF: ICRD
    date = get_tag("date", "year", "TDRC", "TYER", "\xa9day", "ICRD")

    # 6. Género
    # Vorbis: genre | ID3: TCON | MP4: ©gen | RIFF: IGNR
    genre = get_tag("genre", "TCON", "\xa9gen", "IGNR")

    # 7. Número de pista y total
    raw_track = get_tag("tracknumber", "track", "TRCK", "ITRK")
    if not raw_track and "trkn" in tags:
        # MP4 trkn es [(track_num, track_total)]
        mp4_trkn = tags.get("trkn")
        if mp4_trkn and isinstance(mp4_trkn, (list, tuple)) and len(mp4_trkn) > 0:
            track_num, track_total = _parse_track_number(mp4_trkn[0])
        else:
            track_num, track_total = None, None
    else:
        track_num, track_total = _parse_track_number(raw_track)

    if track_total is None:
        raw_total = get_tag("totaltracks", "tracktotal")
        if raw_total and raw_total.isdigit():
            track_total = int(raw_total)

    # 8. Número de disco
    raw_disc = get_tag("discnumber", "disc", "TPOS")
    if not raw_disc and "disk" in tags:
        mp4_disk = tags.get("disk")
        if mp4_disk and isinstance(mp4_disk, (list, tuple)) and len(mp4_disk) > 0:
            disc_num, _ = _parse_track_number(mp4_disk[0])
        else:
            disc_num = None
    else:
        disc_num, _ = _parse_track_number(raw_disc)

    # 9. Heurística para pistas sin tags completos (ej: WAV, AIFF o MP3 sin ID3)
    if not title or title == base_name or not artist or not album:
        title, artist, album, track_num = _infer_metadata_from_path(
            filepath, base_name, title=title, artist=artist, album=album, track_num=track_num
        )

    # 10. Extraer carátula integrada
    cover_data: bytes | None = None
    cover_mime: str = ""

    if isinstance(audio, FLAC) and audio.pictures:
        pic = audio.pictures[0]
        cover_data = pic.data
        cover_mime = pic.mime or "image/jpeg"
    elif hasattr(audio, "tags") and audio.tags:
        # ID3 APIC frame
        for k, v in audio.tags.items():
            if k.startswith("APIC") and hasattr(v, "data"):
                cover_data = v.data
                cover_mime = getattr(v, "mime", "image/jpeg")
                break
            elif k == "covr" and isinstance(v, list) and v:
                covr_item = v[0]
                cover_data = bytes(covr_item)
                # Formato MP4
                img_fmt = getattr(covr_item, "imageformat", None)
                if img_fmt == getattr(mutagen.mp4.MP4Cover, "FORMAT_PNG", 14):
                    cover_mime = "image/png"
                else:
                    cover_mime = "image/jpeg"
                break
        if not cover_data and "metadata_block_picture" in audio.tags:
            mbp = audio.tags.get("metadata_block_picture")
            if mbp:
                try:
                    from mutagen.flac import Picture
                    raw_b64 = mbp[0] if isinstance(mbp, list) else mbp
                    pic = Picture(base64.b64decode(raw_b64))
                    cover_data = pic.data
                    cover_mime = pic.mime or "image/jpeg"
                except Exception:
                    pass

    track_obj = AudioTrack(
        filepath=filepath,
        filename=filename,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        date=date,
        genre=genre,
        track_number=track_num,
        track_total=track_total,
        disc_number=disc_num,
        duration=duration,
        bitrate=bitrate,
        sample_rate=sample_rate,
        bits_per_sample=bits_per_sample,
        channels=channels,
        format_name=fmt,
        file_size_bytes=file_size,
        cover_data=cover_data,
        cover_mime=cover_mime,
    )
    log.debug(
        "Pista cargada: '%s' - '%s' | Álbum: '%s' | %s %s/%s Hz (%s ch, %s) | Carátula: %s bytes",
        artist,
        title,
        album,
        fmt,
        bits_per_sample,
        sample_rate,
        channels,
        track_obj.formatted_duration,
        len(cover_data) if cover_data else 0,
    )
    return track_obj
