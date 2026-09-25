"""Panel lateral derecho: inspector de metadatos audiófilos y carátula HD en MyFlac."""
from __future__ import annotations

import io
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.track import AudioTrack


class InspectorPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_size_request(290, -1)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(10)
        self.set_margin_end(10)

        self.current_track: AudioTrack | None = None
        self._build_ui()

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        # 1. Carátula del álbum en HD escalada perfectamente
        cover_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cover_container.set_halign(Gtk.Align.CENTER)

        self.cover_frame = Gtk.Box()
        self.cover_frame.add_css_class("album-cover-frame")
        self.cover_frame.set_size_request(200, 200)
        self.cover_frame.set_halign(Gtk.Align.CENTER)
        self.cover_frame.set_valign(Gtk.Align.CENTER)
        self.cover_frame.set_overflow(Gtk.Overflow.HIDDEN)

        # Stack para alternar entre imagen escalada y placeholder
        self.cover_stack = Gtk.Stack()
        self.cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # Widget de imagen con escalado perfecto COVER
        self.cover_picture = Gtk.Picture()
        self.cover_picture.set_can_shrink(True)
        self.cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_picture.set_size_request(200, 200)
        self.cover_stack.add_named(self.cover_picture, "picture")

        # Placeholder cuando no hay carátula
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_size_request(200, 200)
        placeholder_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        placeholder_icon.set_pixel_size(64)
        placeholder_icon.add_css_class("dim-label")
        placeholder.append(placeholder_icon)
        self.cover_stack.add_named(placeholder, "placeholder")

        self.cover_stack.set_visible_child_name("placeholder")
        self.cover_frame.append(self.cover_stack)

        self.cover_dims_label = Gtk.Label(label="")
        self.cover_dims_label.add_css_class("dim-label")

        cover_container.append(self.cover_frame)
        cover_container.append(self.cover_dims_label)
        content.append(cover_container)

        # 2. Resumen de la obra (Título, Artista, Álbum)
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_halign(Gtk.Align.CENTER)

        self.title_label = Gtk.Label(label="Selecciona una pista", xalign=0.5)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.add_css_class("heading")
        self.title_label.set_max_width_chars(25)

        self.artist_label = Gtk.Label(label="", xalign=0.5)
        self.artist_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_label.add_css_class("dim-label")
        self.artist_label.set_max_width_chars(25)

        self.album_label = Gtk.Label(label="", xalign=0.5)
        self.album_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.album_label.add_css_class("dim-label")
        self.album_label.set_max_width_chars(25)

        info_box.append(self.title_label)
        info_box.append(self.artist_label)
        info_box.append(self.album_label)
        content.append(info_box)

        # 3. Ficha Técnica Audiófila Compacta
        self.audiophile_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.audiophile_card.add_css_class("audiophile-card")

        card_title = Gtk.Label(label="Ficha Técnica de Audio", xalign=0.0)
        card_title.add_css_class("audiophile-card-title")
        self.audiophile_card.append(card_title)

        # Rejilla de especificaciones de la fuente
        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(3)
        self.grid.set_column_spacing(8)

        def add_spec_row(row_idx: int, label_text: str) -> Gtk.Label:
            lbl_name = Gtk.Label(label=label_text, xalign=0.0)
            lbl_name.add_css_class("dim-label")
            lbl_val = Gtk.Label(label="—", xalign=1.0)
            lbl_val.add_css_class("audiophile-stat-val")
            lbl_val.set_hexpand(True)
            self.grid.attach(lbl_name, 0, row_idx, 1, 1)
            self.grid.attach(lbl_val, 1, row_idx, 1, 1)
            return lbl_val

        self.val_format = add_spec_row(0, "Formato")
        self.val_rate = add_spec_row(1, "Muestreo")
        self.val_depth = add_spec_row(2, "Resolución")
        self.val_channels = add_spec_row(3, "Canales")
        self.val_bitrate = add_spec_row(4, "Tasa de bits")
        self.val_size = add_spec_row(5, "Tamaño")

        self.audiophile_card.append(self.grid)

        # Separador sutil
        self.audiophile_card.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Sección DAC / Bit-Perfect
        dac_title = Gtk.Label(label="Salida Física / DAC", xalign=0.0)
        dac_title.add_css_class("audiophile-card-title")
        self.audiophile_card.append(dac_title)

        self.dac_grid = Gtk.Grid()
        self.dac_grid.set_row_spacing(3)
        self.dac_grid.set_column_spacing(8)

        def add_dac_row(row_idx: int, label_text: str) -> Gtk.Label:
            lbl_name = Gtk.Label(label=label_text, xalign=0.0)
            lbl_name.add_css_class("dim-label")
            lbl_val = Gtk.Label(label="—", xalign=1.0)
            lbl_val.add_css_class("audiophile-stat-val")
            lbl_val.set_hexpand(True)
            self.dac_grid.attach(lbl_name, 0, row_idx, 1, 1)
            self.dac_grid.attach(lbl_val, 1, row_idx, 1, 1)
            return lbl_val

        self.val_dac_name = add_dac_row(0, "Dispositivo")
        self.val_dac_clock = add_dac_row(1, "Reloj Hardware")
        self.val_dac_format = add_dac_row(2, "Formato PCM")
        self.val_dac_status = add_dac_row(3, "Transporte")

        self.audiophile_card.append(self.dac_grid)
        content.append(self.audiophile_card)

        scrolled.set_child(content)
        self.append(scrolled)

    def set_track(self, track: AudioTrack | None):
        """Actualiza la vista con los metadatos de la pista."""
        self.current_track = track
        if not track:
            self.title_label.set_text("Sin reproducción")
            self.artist_label.set_text("")
            self.album_label.set_text("")
            self.val_format.set_text("—")
            self.val_rate.set_text("—")
            self.val_depth.set_text("—")
            self.val_channels.set_text("—")
            self.val_bitrate.set_text("—")
            self.val_size.set_text("—")
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")
            self.cover_dims_label.set_text("")
            return

        self.title_label.set_text(track.title)
        self.artist_label.set_text(track.artist or "Artista desconocido")
        meta_sub = track.album
        if track.date:
            meta_sub += f" ({track.date})"
        self.album_label.set_text(meta_sub)

        # Ficha técnica de la fuente
        self.val_format.set_text(track.format_name)
        self.val_rate.set_text(f"{track.sample_rate / 1000:g} kHz")
        self.val_depth.set_text(f"{track.bits_per_sample} bits" if track.bits_per_sample > 1 else "1 bit (DSD)")
        self.val_channels.set_text("Estéreo (2 canales)" if track.channels == 2 else f"{track.channels} canales")
        self.val_bitrate.set_text(track.formatted_bitrate)
        self.val_size.set_text(track.formatted_file_size)

        # Carátula escalada con Gtk.Picture
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            try:
                data, mime = cover_info
                with Image.open(io.BytesIO(data)) as img:
                    w, h = img.size
                    fmt_clean = mime.split('/')[-1].upper()
                    self.cover_dims_label.set_text(f"{w} × {h} px · {fmt_clean}")

                bytes_glib = GLib.Bytes.new(data)
                texture = Gdk.Texture.new_from_bytes(bytes_glib)
                self.cover_picture.set_paintable(texture)
                self.cover_stack.set_visible_child_name("picture")
            except Exception:
                self.cover_picture.set_paintable(None)
                self.cover_stack.set_visible_child_name("placeholder")
                self.cover_dims_label.set_text("")
        else:
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")
            self.cover_dims_label.set_text("Sin carátula disponible")

    def update_dac_status(self, info: dict):
        """Actualiza la auditoría de estado del DAC en tiempo real."""
        dev_name = info.get("device_name", "Desconocido")
        if len(dev_name) > 22:
            dev_name = dev_name[:20] + "…"
        self.val_dac_name.set_text(dev_name)

        sink_rate = info.get("sink_rate")
        if sink_rate:
            self.val_dac_clock.set_text(f"{sink_rate / 1000:g} kHz")
        else:
            self.val_dac_clock.set_text("Detenido")

        sink_fmt = info.get("sink_format") or "—"
        self.val_dac_format.set_text(sink_fmt)

        is_bp = info.get("is_bitperfect", False)
        is_excl = info.get("is_exclusive", False)

        if is_bp:
            self.val_dac_status.set_text("✓ 100% Bit-Perfect")
            self.val_dac_status.remove_css_class("error")
            self.val_dac_status.remove_css_class("warning")
            self.val_dac_status.add_css_class("accent")
        elif is_excl:
            self.val_dac_status.set_text("Exclusivo (atenuado)")
            self.val_dac_status.add_css_class("warning")
        else:
            self.val_dac_status.set_text("Compartido / Sistema")
            self.val_dac_status.remove_css_class("accent")
