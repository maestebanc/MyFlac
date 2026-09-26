"""Vista de una ficha "Tema", "Disco" o "Artista" del inspector (Wikipedia + Discogs)."""
from __future__ import annotations

from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from ..music_info import InfoCard
from .. import i18n

IMAGE_HEIGHT = 170


def _source_name(url: str) -> str:
    host = urlparse(url).netloc
    if "wikipedia.org" in host:
        return f"Wikipedia ({host.split('.')[0]})"
    if "discogs.com" in host:
        return "Discogs"
    return host or unquote(url)


def _wrapping_label(css_class: str | None = None, selectable: bool = False) -> Gtk.Label:
    label = Gtk.Label(xalign=0.0)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_width_chars(10)
    label.set_selectable(selectable)
    if css_class:
        label.add_css_class(css_class)
    return label


class InfoView(Gtk.Stack):
    """Estados: cargando, ficha (desplazable) y mensaje."""

    def __init__(self):
        super().__init__()
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.set_vexpand(True)

        loading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        loading.set_halign(Gtk.Align.CENTER)
        loading.set_valign(Gtk.Align.CENTER)
        self._spinner = Gtk.Spinner()
        loading.append(self._spinner)
        self._loading_label = Gtk.Label()
        self._loading_label.add_css_class("dim-label")
        loading.append(self._loading_label)
        self.add_named(loading, "loading")

        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scrolled.set_vexpand(True)
        self._scrolled.add_css_class("lyrics-view")
        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._content.set_margin_end(10)
        self._scrolled.set_child(self._content)
        self.add_named(self._scrolled, "content")

        self._message = Gtk.Label(xalign=0.5)
        self._message.set_wrap(True)
        self._message.set_justify(Gtk.Justification.CENTER)
        self._message.set_valign(Gtk.Align.CENTER)
        self._message.add_css_class("dim-label")
        self.add_named(self._message, "message")
        self.show_message("")

    def show_loading(self, text: str):
        self._loading_label.set_text(text)
        self._spinner.start()
        self.set_visible_child_name("loading")

    def show_message(self, text: str):
        self._spinner.stop()
        self._message.set_text(text)
        self.set_visible_child_name("message")

    def show_info(self, info: InfoCard):
        self._spinner.stop()
        child = self._content.get_first_child()
        while child:
            self._content.remove(child)
            child = self._content.get_first_child()

        if info.image_path:
            try:
                picture = Gtk.Picture.new_for_paintable(Gdk.Texture.new_from_filename(info.image_path))
                picture.set_content_fit(Gtk.ContentFit.COVER)
                picture.set_can_shrink(True)
                picture.set_size_request(-1, IMAGE_HEIGHT)
                picture.set_overflow(Gtk.Overflow.HIDDEN)
                picture.add_css_class("notes-image")
                self._content.append(picture)
            except GLib.Error:
                pass
        if info.title:
            title = _wrapping_label("notes-title")
            title.set_text(info.title)
            self._content.append(title)
        if info.description:
            description = _wrapping_label("notes-description")
            description.set_text(info.description[:1].upper() + info.description[1:])
            self._content.append(description)
        if info.markup:
            text = _wrapping_label("inspector-notes-text", selectable=True)
            text.set_markup(info.markup)
            self._content.append(text)

        if info.facts:
            grid = Gtk.Grid(row_spacing=4, column_spacing=10)
            grid.add_css_class("info-facts")
            for row, (label, value) in enumerate(info.facts):
                name = Gtk.Label(label=label, xalign=0.0, yalign=0.0)
                name.add_css_class("dim-label")
                grid.attach(name, 0, row, 1, 1)
                val = _wrapping_label(selectable=True)
                val.set_hexpand(True)
                val.set_markup(value)
                grid.attach(val, 1, row, 1, 1)
            self._content.append(grid)

        for heading, body in info.sections:
            head = Gtk.Label(label=heading.upper(), xalign=0.0)
            head.add_css_class("audiophile-card-title")
            head.add_css_class("info-section-title")
            self._content.append(head)
            text = _wrapping_label("inspector-notes-text", selectable=True)
            text.set_markup(body)
            self._content.append(text)

        if info.sources:
            footer = _wrapping_label()
            footer.add_css_class("dim-label")
            footer.add_css_class("caption")
            links = ", ".join(
                f'<a href="{GLib.markup_escape_text(u)}">{GLib.markup_escape_text(_source_name(u))}</a>'
                for u in info.sources
            )
            text = f"{GLib.markup_escape_text(i18n.t('info.sources'))}: {links}"
            if info.translated_by:
                text += " · " + GLib.markup_escape_text(i18n.t("info.translated", service=info.translated_by))
            footer.set_markup(text)
            self._content.append(footer)

        self._scrolled.get_vadjustment().set_value(0)
        self.set_visible_child_name("content")
