"""
Icono de MyFlac en la barra superior (bandeja del sistema) mediante el protocolo StatusNotifierItem,
el que muestra la extensión AppIndicator de GNOME (y KDE, XFCE...). Menú con dbusmenu.

- Clic izquierdo: ventanita de reproducción (portada, barra de progreso, controles y Salir).
- Clic derecho: menú bajo el icono con la pista, el tiempo, los controles, Mostrar MyFlac y Salir.
- Rueda del ratón sobre el icono: volumen.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from ..audio.engine import PlaybackState
from ..constants import APP_ID
from ..logger import get_logger
from .. import i18n

if TYPE_CHECKING:
    from ..app import MyFlacApplication

log = get_logger("ui.tray")

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
# El icono de MyFlac (en color), como el resto de aplicaciones de la bandeja
ICON_NAME = APP_ID
VOLUME_STEP = 0.05

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
  </interface>
</node>
"""

# Identificadores de los elementos del menú
ID_TRACK, ID_TIME, ID_PLAY, ID_PREV, ID_NEXT, ID_SHOW, ID_SUPER, ID_MINI, ID_QUIT = 1, 2, 4, 5, 6, 8, 9, 10, 12
ID_SEP1, ID_SEP2, ID_SEP3 = 3, 7, 11
MENU_ORDER = [ID_TRACK, ID_TIME, ID_SEP1, ID_PLAY, ID_PREV, ID_NEXT, ID_SEP2, ID_SHOW, ID_SUPER, ID_MINI, ID_SEP3, ID_QUIT]


def _format_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _icon_pixmaps() -> list[tuple[int, int, bytes]]:
    """Icono de MyFlac como mapas de píxeles ARGB (por si el panel no encuentra el icono por nombre)."""
    display = Gdk.Display.get_default()
    if display is None:
        return []
    theme = Gtk.IconTheme.get_for_display(display)
    pixmaps = []
    for size in (22, 32, 48):
        paintable = theme.lookup_icon(ICON_NAME, None, size, 1, Gtk.TextDirection.NONE, 0)
        icon_file = paintable.get_file() if paintable else None
        if icon_file is None or icon_file.get_path() is None:
            continue
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_file.get_path(), size, size)
        except GLib.Error:
            continue
        if not pixbuf.get_has_alpha():
            pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
        rgba = pixbuf.get_pixels()
        stride, width, height = pixbuf.get_rowstride(), pixbuf.get_width(), pixbuf.get_height()
        argb = bytearray()
        for y in range(height):
            row = rgba[y * stride: y * stride + width * 4]
            for x in range(0, width * 4, 4):
                argb += bytes((row[x + 3], row[x], row[x + 1], row[x + 2]))  # RGBA -> ARGB
        pixmaps.append((width, height, bytes(argb)))
    return pixmaps


class TrayIcon:
    """Icono en la barra superior con menú; se registra en el StatusNotifierWatcher de la sesión."""

    def __init__(self, app: MyFlacApplication):
        self.app = app
        self._conn: Gio.DBusConnection | None = None
        self._ids: list[int] = []
        self._watch_id = 0
        self._timer_id = 0
        self._revision = 1
        self._pixmaps: list[tuple[int, int, bytes]] | None = None
        self._props: dict[int, dict[str, GLib.Variant]] = {}
        self.popup = None  # Ventana de reproducción (doble clic), se crea al primer uso
        # Hay icono de MyFlac en la barra (extensión propia o bandeja): cerrar la ventana no detiene la música
        self.visible_in_panel = False

    @property
    def pixmaps(self) -> list[tuple[int, int, bytes]]:
        if self._pixmaps is None:
            self._pixmaps = _icon_pixmaps()
        return self._pixmaps

    # ------------------------------------------------------------------ ciclo de vida
    def start(self):
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
            menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
            self._ids.append(self._conn.register_object(ITEM_PATH, sni, self._on_sni_call, self._on_sni_property, None))
            self._ids.append(self._conn.register_object(MENU_PATH, menu, self._on_menu_call, self._on_menu_property, None))
        except GLib.Error as e:
            log.warning("No se pudo publicar el icono de la barra superior: %s", e.message)
            return
        self._build_menu_props()
        # El vigilante (la extensión AppIndicator) puede no estar aún o reiniciarse: se registra cada vez
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._conn, WATCHER_NAME, Gio.BusNameWatcherFlags.NONE, self._on_watcher_appeared, None
        )
        engine = self.app.window.engine
        engine.add_track_listener(self._on_player_changed)
        engine.add_state_listener(self._on_player_changed)
        i18n.add_language_listener(lambda *_: self._refresh(layout=True))
        self._timer_id = GLib.timeout_add_seconds(1, self._on_tick)

    def shutdown(self):
        """Quita el icono y cierra la ventanita (al salir de MyFlac)."""
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._conn:
            for reg in self._ids:
                self._conn.unregister_object(reg)
        self._ids.clear()
        if self.popup is not None:
            self.popup.shutdown()
            self.popup = None

    def _on_watcher_appeared(self, conn, _name, _owner):
        # Registro por ruta: el vigilante usa el nombre único de esta conexión (no hace falta poseer
        # un nombre org.kde.StatusNotifierItem-*, lo que simplifica los permisos del Flatpak)
        conn.call(
            WATCHER_NAME, WATCHER_PATH, WATCHER_NAME, "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (ITEM_PATH,)), None, Gio.DBusCallFlags.NONE, 5000, None,
            self._on_registered, None,
        )

    def _on_registered(self, conn, result, _data):
        try:
            conn.call_finish(result)
            self.visible_in_panel = True
            log.info("Icono de MyFlac publicado en la barra superior")
        except GLib.Error as e:
            log.warning("El vigilante de la bandeja rechazó el icono: %s", e.message)

    # ------------------------------------------------------------------ acciones
    @property
    def _window(self):
        return self.app.window

    def _toggle_popup(self):
        from .tray_player import TrayPlayerWindow
        if self.popup is None:
            self.popup = TrayPlayerWindow(self.app)
        self.popup.toggle()

    def _show_main(self):
        if self.popup is not None:
            self.popup.set_visible(False)
        self._window.show_main_view()

    def _show_super(self):
        if self.popup is not None:
            self.popup.set_visible(False)
        self._window.show_super_view()

    def _show_mini(self):
        if self.popup is not None:
            self.popup.set_visible(False)
        self._window.show_mini_view()

    def _activate(self, item_id: int):
        engine = self._window.engine
        if item_id == ID_PLAY:
            self._window._toggle_play_pause()
        elif item_id == ID_PREV:
            self._window._play_previous()
        elif item_id == ID_NEXT:
            self._window._play_next()
        elif item_id == ID_SHOW:
            self._show_main()
        elif item_id == ID_SUPER:
            self._show_super()
        elif item_id == ID_MINI:
            self._show_mini()
        elif item_id == ID_QUIT:
            self.app.activate_action("quit")
        elif item_id == ID_TRACK and engine.current_track:
            self._toggle_popup()

    # ------------------------------------------------------------------ StatusNotifierItem
    def _on_sni_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "Activate":
            GLib.idle_add(lambda: (self._toggle_popup(), False)[1])
        elif method == "SecondaryActivate":
            GLib.idle_add(lambda: (self._window._toggle_play_pause(), False)[1])
        elif method == "Scroll":
            delta, orientation = params.unpack()
            if orientation.lower() == "vertical" and delta:
                step = VOLUME_STEP if delta < 0 else -VOLUME_STEP  # rueda hacia arriba: subir
                GLib.idle_add(lambda: (self._window.change_volume(step), False)[1])
        invocation.return_value(None)

    def _on_sni_property(self, _conn, _sender, _path, _iface, prop):
        track = self._window.engine.current_track if self.app.window else None
        if prop == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if prop == "Id":
            return GLib.Variant("s", "myflac")
        if prop == "Title":
            return GLib.Variant("s", "MyFlac")
        if prop == "Status":
            return GLib.Variant("s", "Active")
        if prop == "WindowId":
            return GLib.Variant("u", 0)
        if prop == "IconName":
            return GLib.Variant("s", ICON_NAME)
        if prop == "IconPixmap":
            return GLib.Variant("a(iiay)", self.pixmaps)
        if prop == "IconThemePath":
            return GLib.Variant("s", "")
        if prop in ("OverlayIconName", "AttentionIconName"):
            return GLib.Variant("s", "")
        if prop == "ToolTip":
            text = f"{track.title} — {track.artist}" if track else ""
            return GLib.Variant("(sa(iiay)ss)", (ICON_NAME, [], "MyFlac", text))
        if prop == "ItemIsMenu":
            return GLib.Variant("b", False)
        if prop == "Menu":
            return GLib.Variant("o", MENU_PATH)
        return None

    # ------------------------------------------------------------------ menú (dbusmenu)
    def _build_menu_props(self):
        engine = self._window.engine
        track = engine.current_track
        playing = engine.state == PlaybackState.PLAYING
        track_label = f"{track.title} — {track.artist}" if track else i18n.t("inspector.no_playback")
        props = {
            ID_TRACK: {"label": GLib.Variant("s", track_label), "enabled": GLib.Variant("b", bool(track))},
            ID_TIME: {"label": GLib.Variant("s", self._time_label()), "enabled": GLib.Variant("b", False),
                      "visible": GLib.Variant("b", bool(track))},
            ID_PLAY: {"label": GLib.Variant("s", i18n.t("tray.pause") if playing else i18n.t("tray.play")),
                      "icon-name": GLib.Variant("s", "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")},
            ID_PREV: {"label": GLib.Variant("s", i18n.t("tray.previous")), "icon-name": GLib.Variant("s", "media-skip-backward-symbolic")},
            ID_NEXT: {"label": GLib.Variant("s", i18n.t("tray.next")), "icon-name": GLib.Variant("s", "media-skip-forward-symbolic")},
            ID_SHOW: {"label": GLib.Variant("s", i18n.t("tray.show"))},
            ID_SUPER: {"label": GLib.Variant("s", i18n.t("tray.super_player")), "icon-name": GLib.Variant("s", "view-fullscreen-symbolic")},
            ID_MINI: {"label": GLib.Variant("s", i18n.t("tray.mini_player")), "icon-name": GLib.Variant("s", "window-pop-out-symbolic")},
            ID_QUIT: {"label": GLib.Variant("s", i18n.t("tray.quit")), "icon-name": GLib.Variant("s", "application-exit-symbolic")},
        }
        cover = self._cover_png(track)
        if cover:
            props[ID_TRACK]["icon-data"] = GLib.Variant("ay", cover)
        for sep in (ID_SEP1, ID_SEP2, ID_SEP3):
            props[sep] = {"type": GLib.Variant("s", "separator")}
        self._props = props

    def _cover_png(self, track) -> bytes:
        """Miniatura de la portada para el menú."""
        cover = track.get_cover_image_bytes() if track else None
        if not cover:
            return b""
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(cover[0])
            loader.close()
            pixbuf = loader.get_pixbuf().scale_simple(48, 48, GdkPixbuf.InterpType.BILINEAR)
            ok, data = pixbuf.save_to_bufferv("png", [], [])
            return bytes(data) if ok else b""
        except GLib.Error:
            return b""

    def _time_label(self) -> str:
        engine = self._window.engine
        if not engine.current_track:
            return ""
        return f"{_format_time(engine.position)} / {_format_time(engine.get_duration())}"

    def _layout(self) -> tuple:
        """Estructura (id, propiedades, hijos) de la raíz del menú, lista para GLib.Variant."""
        children = [GLib.Variant("(ia{sv}av)", (item, self._props.get(item, {}), [])) for item in MENU_ORDER]
        return (0, {"children-display": GLib.Variant("s", "submenu")}, children)

    def _refresh(self, layout: bool = False):
        """Reenvía al panel las propiedades que hayan cambiado."""
        if not self._conn or not self._ids:
            return
        old = self._props
        self._build_menu_props()
        if layout:
            self._revision += 1
            self._conn.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated",
                                   GLib.Variant("(ui)", (self._revision, 0)))
            return
        changed = []
        for item, props in self._props.items():
            before = old.get(item, {})
            diff = {k: v for k, v in props.items() if k not in before or not before[k].equal(v)}
            if diff:
                changed.append((item, diff))
        if changed:
            self._conn.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "ItemsPropertiesUpdated",
                                   GLib.Variant("(a(ia{sv})a(ias))", (changed, [])))

    def _on_player_changed(self, *_args):
        self._refresh(layout=True)  # la portada y el título cambian el menú entero
        if self._conn and self._ids:
            self._conn.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip", None)

    def _on_tick(self) -> bool:
        self._refresh()
        return True

    def _on_menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._revision, self._layout())))
        elif method == "GetGroupProperties":
            ids, _names = params.unpack()
            wanted = ids or list(self._props)
            result = [(i, self._props.get(i, {})) for i in wanted if i in self._props]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            item, name = params.unpack()
            value = self._props.get(item, {}).get(name, GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item, event, _data, _time = params.unpack()
            if event == "clicked":
                GLib.idle_add(lambda: (self._activate(item), False)[1])
            invocation.return_value(None)
        elif method == "EventGroup":
            events = params.unpack()[0]
            for item, event, _data, _time in events:
                if event == "clicked":
                    GLib.idle_add(lambda i=item: (self._activate(i), False)[1])
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            self._refresh()
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            self._refresh()
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _on_menu_property(self, _conn, _sender, _path, _iface, prop):
        if prop == "Version":
            return GLib.Variant("u", 3)
        if prop == "TextDirection":
            return GLib.Variant("s", "ltr")
        if prop == "Status":
            return GLib.Variant("s", "normal")
        if prop == "IconThemePath":
            return GLib.Variant("as", [])
        return None
