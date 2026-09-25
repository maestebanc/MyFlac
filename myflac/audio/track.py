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
                            self.cover_data = bytes(v[0])
                            self.cover_mime = "image/jpeg"
                            return self.cover_data, self.cover_mime
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


def _clean_tag(val: any) -> str:
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else ""
    return str(val).strip()


def _parse_track_number(val: any) -> tuple[int | None, int | None]:
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
        # Fallback básico si mutagen falla
        return AudioTrack(
            filepath=filepath,
            filename=filename,
            title=base_name,
            file_size_bytes=file_size,
            format_name=fmt or "FLAC",
        )

    if audio is None:
        return AudioTrack(
            filepath=filepath,
            filename=filename,
            title=base_name,
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
    
    # Mutagen almacena en minúsculas en FLAC/Ogg y mayúsculas en ID3
    def get_tag(*keys: str) -> str:
        for k in keys:
            v = tags.get(k) or tags.get(k.upper()) or tags.get(k.lower())
            if v:
                return _clean_tag(v)
        return ""

    title = get_tag("title") or base_name
    artist = get_tag("artist")
    album = get_tag("album")
    album_artist = get_tag("albumartist", "album artist", "band")
    date = get_tag("date", "year")
    genre = get_tag("genre")
    
    raw_track = get_tag("tracknumber", "track")
    track_num, track_total = _parse_track_number(raw_track)
    if track_total is None:
        raw_total = get_tag("totaltracks", "tracktotal")
        if raw_total and raw_total.isdigit():
            track_total = int(raw_total)

    raw_disc = get_tag("discnumber", "disc")
    disc_num, _ = _parse_track_number(raw_disc)

    # Extraer carátula integrada
    cover_data: bytes | None = None
    cover_mime: str = ""

    if isinstance(audio, FLAC) and audio.pictures:
        pic = audio.pictures[0]
        cover_data = pic.data
        cover_mime = pic.mime
    elif hasattr(audio, "tags") and audio.tags:
        # ID3 APIC frame
        for k, v in audio.tags.items():
            if k.startswith("APIC") and hasattr(v, "data"):
                cover_data = v.data
                cover_mime = getattr(v, "mime", "image/jpeg")
                break
            elif k == "covr" and isinstance(v, list) and v:
                cover_data = bytes(v[0])
                cover_mime = "image/jpeg"
                break

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
