"""Fondo ambiental desenfocado con la foto del artista, detrás de la biblioteca (estilo Roon / Apple Music)."""
from __future__ import annotations

import io
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk
from PIL import Image, ImageFilter

from ..artist_art import ArtistArtService
from ..logger import get_logger

log = get_logger("ui.backdrop")

# La foto se reduce antes de desenfocar (cuesta milisegundos en lugar de cientos): un radio de 5 px
# a 640 px equivale a ~10-12 px a pantalla completa, suave pero con el artista reconocible
BLUR_WORKING_SIZE = 640
BLUR_RADIUS = 5
# Intensidad de la foto (lo que deja ver la capa de oscurecimiento), ajustable en Preferencias:
# Por defecto, un toque discreto (capa oscura del 90 %); cada cual lo sube en Preferencias
DEFAULT_INTENSITY = 10
MIN_INTENSITY = 10
MAX_INTENSITY = 80
# En tema claro la capa clara necesita algo más de opacidad para el mismo contraste
LIGHT_SCRIM_EXTRA = 0.04
# Proporción del color de la foto en la capa de oscurecimiento (el tinte)
TINT_AMOUNT_DARK = 0.12
TINT_AMOUNT_LIGHT = 0.08
BASE_DARK = (12, 13, 17)
BASE_LIGHT = (235, 238, 243)  # Paleta Libadwaita Slate Soft (#ebeef3)
MAX_CACHED_TEXTURES = 8


def blur_artist_image(path: str) -> tuple[bytes, tuple[int, int, int]]:
    """Devuelve (PNG desenfocado, color medio RGB) de la foto del artista."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((BLUR_WORKING_SIZE, BLUR_WORKING_SIZE), Image.Resampling.LANCZOS)
        blurred = img.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        average = blurred.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
        buffer = io.BytesIO()
        blurred.save(buffer, format="PNG")
        return buffer.getvalue(), tuple(average)


def scrim_opacity(intensity: int, dark: bool) -> float:
    """Opacidad de la capa para una intensidad de foto en % (más intensidad, capa más ligera)."""
    intensity = max(MIN_INTENSITY, min(MAX_INTENSITY, int(intensity)))
    opacity = 1.0 - intensity / 100.0
    if not dark:
        opacity = min(0.95, opacity + LIGHT_SCRIM_EXTRA)
    return round(opacity, 2)


def scrim_color(average: tuple[int, int, int] | None, dark: bool, intensity: int = DEFAULT_INTENSITY) -> str:
    """Color de la capa de oscurecimiento: base del tema teñida con el color medio de la foto."""
    base = BASE_DARK if dark else BASE_LIGHT
    amount = TINT_AMOUNT_DARK if dark else TINT_AMOUNT_LIGHT
    opacity = scrim_opacity(intensity, dark)
    if average is None:
        rgb = base
    else:
        rgb = tuple(round(b * (1 - amount) + a * amount) for b, a in zip(base, average))
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {opacity})"


class ArtistBackdrop(Gtk.Overlay):
    """
    Envuelve un widget (la biblioteca) y pinta detrás la foto del artista ampliada y desenfocada,
    cubierta por una capa oscura teñida para no restar legibilidad al texto.
    """

    _css_serial = 0

    def __init__(self, content: Gtk.Widget, enabled: bool = True, intensity: int = DEFAULT_INTENSITY):
        super().__init__()
        self._enabled = enabled
        self._intensity = intensity
        self._wanted_artist: str | None = None  # artista en reproducción, aunque el fondo esté apagado
        self._artist: str | None = None
        self._image_path: str | None = None
        self._average: tuple[int, int, int] | None = None
        self._has_image = False
        self._textures: dict[str, tuple[Gdk.Texture, tuple[int, int, int]]] = {}

        self._picture = Gtk.Picture()
        self._picture.set_content_fit(Gtk.ContentFit.COVER)
        self._picture.set_can_shrink(True)
        self._picture.set_can_target(False)
        self._picture.add_css_class("artist-backdrop-picture")
        self.set_child(self._picture)

        # Capa de oscurecimiento con un nombre de clase propio para su CSS dinámico
        ArtistBackdrop._css_serial += 1
        self._scrim_class = f"artist-backdrop-scrim-{ArtistBackdrop._css_serial}"
        self._scrim = Gtk.Box()
        self._scrim.set_can_target(False)
        self._scrim.add_css_class(self._scrim_class)
        self.add_overlay(self._scrim)

        # El contenido manda en el tamaño; el fondo se adapta a él
        self.add_overlay(content)
        self.set_measure_overlay(content, True)

        self._css = Gtk.CssProvider()
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10
            )
        self._style_manager = Adw.StyleManager.get_default()
        self._style_manager.connect("notify::dark", lambda *_: self._update_scrim())
        self._show(None, None)

    def set_enabled(self, enabled: bool):
        """Activa o desactiva el fondo (desactivado no descarga ni desenfoca nada)."""
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._artist = None
        if enabled:
            self.set_artist(self._wanted_artist)
        else:
            self._show(None, None)

    def set_intensity(self, intensity: int):
        """Ajusta cuánto se ve la foto (MIN_INTENSITY-MAX_INTENSITY %)."""
        self._intensity = max(MIN_INTENSITY, min(MAX_INTENSITY, int(intensity)))
        self._update_scrim()

    def set_artist(self, artist: str | None):
        """Muestra de fondo la foto del artista (o nada si no hay foto)."""
        artist = (artist or "").strip()
        self._wanted_artist = artist
        if not self._enabled or artist == self._artist:
            return
        self._artist = artist
        if not artist:
            self._show(None, None)
            return
        ArtistArtService.get_default().fetch_artist_image(
            artist, lambda path, a=artist: self._on_image(path) if a == self._artist else None
        )

    def _on_image(self, path: str | None):
        if not path:
            self._show(None, None)
            return
        if path in self._textures:
            texture, average = self._textures[path]
            self._show(texture, average)
            return

        artist = self._artist

        def _worker():
            try:
                png, average = blur_artist_image(path)
            except Exception as e:
                log.warning("No se pudo desenfocar la foto de artista %s: %s", path, e)
                GLib.idle_add(self._on_blurred, artist, path, None, None)
                return
            GLib.idle_add(self._on_blurred, artist, path, png, average)

        threading.Thread(target=_worker, name="artist-backdrop-blur", daemon=True).start()

    def _on_blurred(self, artist: str | None, path: str, png: bytes | None, average) -> bool:
        if png is None:
            if artist == self._artist:
                self._show(None, None)
            return False
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
        if len(self._textures) >= MAX_CACHED_TEXTURES:
            self._textures.pop(next(iter(self._textures)))
        self._textures[path] = (texture, average)
        if artist == self._artist:
            self._show(texture, average)
        return False

    def _show(self, texture: Gdk.Texture | None, average: tuple[int, int, int] | None):
        self._average = average
        self._has_image = texture is not None
        if texture is None:
            self._picture.remove_css_class("visible")
        else:
            self._picture.set_paintable(texture)
            self._picture.add_css_class("visible")
        self._update_scrim()

    def _update_scrim(self):
        # Sombra de texto solo sobre foto y en tema oscuro, para leer bien sobre zonas claras
        dark = self._style_manager.get_dark()
        if self._has_image and dark:
            self.add_css_class("has-backdrop-dark")
        else:
            self.remove_css_class("has-backdrop-dark")
        # Sin foto no hay capa: la biblioteca conserva su aspecto habitual
        color = scrim_color(self._average, dark, self._intensity) if self._has_image else "transparent"
        self._css.load_from_string(
            f".{self._scrim_class} {{ background-color: {color}; transition: background-color 800ms ease; }}"
        )
