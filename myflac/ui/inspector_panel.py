"""Panel lateral derecho: inspector de metadatos audiófilos y carátula HD en MyFlac."""
from __future__ import annotations

import io
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.track import AudioTrack
from .. import i18n


class InspectorPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_size_request(280, -1)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(10)
        self.set_margin_end(10)

        self.current_track: AudioTrack | None = None
        self._last_output_info: dict = {}
        self._build_ui()

        # Registrar listener para cambios dinámicos de idioma
        i18n.add_language_listener(self._on_language_changed)

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

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

        # Widget de imagen con escalado COVER
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

        self.title_label = Gtk.Label(label=i18n.t("inspector.select_track"), xalign=0.5)
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

        # 3. Ficha Técnica de Audio
        self.audiophile_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.audiophile_card.add_css_class("audiophile-card")

        self.card_title = Gtk.Label(label=i18n.t("inspector.card_title"), xalign=0.0)
        self.card_title.add_css_class("audiophile-card-title")
        self.audiophile_card.append(self.card_title)

        # Rejilla de especificaciones
        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(8)

        def add_spec_row(row_idx: int, label_key: str) -> tuple[Gtk.Label, Gtk.Label]:
            lbl_name = Gtk.Label(label=i18n.t(label_key), xalign=0.0)
            lbl_name.add_css_class("dim-label")
            lbl_val = Gtk.Label(label="—", xalign=1.0)
            lbl_val.add_css_class("audiophile-stat-val")
            lbl_val.set_hexpand(True)
            self.grid.attach(lbl_name, 0, row_idx, 1, 1)
            self.grid.attach(lbl_val, 1, row_idx, 1, 1)
            return lbl_name, lbl_val

        self.lbl_format, self.val_format = add_spec_row(0, "inspector.format")
        self.lbl_rate, self.val_rate = add_spec_row(1, "inspector.sampling")
        self.lbl_depth, self.val_depth = add_spec_row(2, "inspector.resolution")
        self.lbl_channels, self.val_channels = add_spec_row(3, "inspector.channels")
        self.lbl_bitrate, self.val_bitrate = add_spec_row(4, "inspector.bitrate")
        self.lbl_size, self.val_size = add_spec_row(5, "inspector.size")

        self.audiophile_card.append(self.grid)

        # Separador sutil
        self.audiophile_card.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Sección Salida de Audio / Mezclador del Sistema
        self.output_title = Gtk.Label(label=i18n.t("inspector.output_device"), xalign=0.0)
        self.output_title.add_css_class("audiophile-card-title")
        self.audiophile_card.append(self.output_title)

        self.output_grid = Gtk.Grid()
        self.output_grid.set_row_spacing(4)
        self.output_grid.set_column_spacing(8)

        def add_out_row(row_idx: int, label_key: str) -> tuple[Gtk.Label, Gtk.Label]:
            lbl_name = Gtk.Label(label=i18n.t(label_key), xalign=0.0)
            lbl_name.add_css_class("dim-label")
            lbl_val = Gtk.Label(label="—", xalign=1.0)
            lbl_val.add_css_class("audiophile-stat-val")
            lbl_val.set_hexpand(True)
            self.output_grid.attach(lbl_name, 0, row_idx, 1, 1)
            self.output_grid.attach(lbl_val, 1, row_idx, 1, 1)
            return lbl_name, lbl_val

        self.lbl_out_dev, self.val_out_dev = add_out_row(0, "inspector.device")
        self.lbl_out_mixer, self.val_out_mixer = add_out_row(1, "inspector.mixer")
        self.lbl_out_status, self.val_out_status = add_out_row(2, "inspector.status")

        self.val_out_mixer.set_text(i18n.t("inspector.mixer_name"))
        self.val_out_status.set_text(i18n.t("inspector.status_stopped"))

        self.audiophile_card.append(self.output_grid)
        content.append(self.audiophile_card)

        # Spacer vertical para evitar que los elementos se estiren cuando la ventana se maximiza
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        content.append(spacer)

        scrolled.set_child(content)
        self.append(scrolled)

    def _on_language_changed(self, _lang: str):
        """Actualiza todas las etiquetas estáticas al cambiar de idioma."""
        self.card_title.set_text(i18n.t("inspector.card_title"))
        self.lbl_format.set_text(i18n.t("inspector.format"))
        self.lbl_rate.set_text(i18n.t("inspector.sampling"))
        self.lbl_depth.set_text(i18n.t("inspector.resolution"))
        self.lbl_channels.set_text(i18n.t("inspector.channels"))
        self.lbl_bitrate.set_text(i18n.t("inspector.bitrate"))
        self.lbl_size.set_text(i18n.t("inspector.size"))

        self.output_title.set_text(i18n.t("inspector.output_device"))
        self.lbl_out_dev.set_text(i18n.t("inspector.device"))
        self.lbl_out_mixer.set_text(i18n.t("inspector.mixer"))
        self.lbl_out_status.set_text(i18n.t("inspector.status"))
        self.val_out_mixer.set_text(i18n.t("inspector.mixer_name"))

        if not self.current_track:
            self.title_label.set_text(i18n.t("inspector.select_track"))
        else:
            self.set_track(self.current_track)

        if self._last_output_info:
            self.update_dac_status(self._last_output_info)

    def set_track(self, track: AudioTrack | None):
        """Actualiza la vista con los metadatos de la pista."""
        self.current_track = track
        if not track:
            self.title_label.set_text(i18n.t("inspector.no_playback"))
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
        self.artist_label.set_text(track.artist or i18n.t("inspector.unknown_artist"))
        meta_sub = track.album or i18n.t("inspector.unknown_album")
        if track.date:
            meta_sub += f" ({track.date})"
        self.album_label.set_text(meta_sub)

        # Ficha técnica de la fuente
        self.val_format.set_text(track.format_name)
        self.val_rate.set_text(f"{track.sample_rate / 1000:g} kHz")
        self.val_depth.set_text(f"{track.bits_per_sample} bits" if track.bits_per_sample > 1 else "1 bit (DSD)")
        channels_str = i18n.t("inspector.stereo") if track.channels == 2 else i18n.t("inspector.channels_n", n=track.channels)
        self.val_channels.set_text(channels_str)
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
            self.cover_dims_label.set_text(i18n.t("inspector.no_cover"))

    def update_dac_status(self, info: dict):
        """Actualiza el estado de la salida de audio y dispositivo activo."""
        self._last_output_info = info
        dev_name = info.get("device_name", i18n.t("devices.default_name"))
        if len(dev_name) > 24:
            dev_name = dev_name[:22] + "…"
        self.val_out_dev.set_text(dev_name)

        is_playing = info.get("is_playing", False)
        is_paused = info.get("is_paused", False)
        if is_playing:
            self.val_out_status.set_text(i18n.t("inspector.status_playing"))
            self.val_out_status.add_css_class("accent")
            self.val_out_status.remove_css_class("warning")
        elif is_paused:
            self.val_out_status.set_text(i18n.t("inspector.status_paused"))
            self.val_out_status.add_css_class("warning")
            self.val_out_status.remove_css_class("accent")
        else:
            self.val_out_status.set_text(i18n.t("inspector.status_stopped"))
            self.val_out_status.remove_css_class("accent")
            self.val_out_status.remove_css_class("warning")
