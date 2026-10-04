"""Sección de TIDAL: la misma vista que Qobuz con el cliente de la API oficial de TIDAL."""
from __future__ import annotations

import threading
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import i18n
from ..logger import get_logger
from ..streaming.qobuz_client import QobuzError
from ..streaming.tidal_client import DEFAULT_CLIENT_ID, DEFAULT_REDIRECT_URI, get_tidal_client
from .qobuz_view import QobuzView

log = get_logger("ui.tidal_view")


class TidalView(QobuzView):
    SERVICE = "tidal"
    BADGE = "TIDAL"
    CATEGORIES = (("new-releases", "tidal.cat.new_releases"), ("discovery", "tidal.cat.discovery"),
                  ("daily", "tidal.cat.daily"))

    def _make_client(self):
        return get_tidal_client()

    def _open_login_dialog(self, _btn):
        dlg = TidalAccountDialog(self.parent_window, self._on_auth_changed) if self.client.is_logged_in \
            else TidalLoginDialog(self.parent_window, self._on_auth_changed)
        dlg.present()

    def _open_manual_token_dialog(self, _btn):
        TidalLoginDialog(self.parent_window, self._on_auth_changed).present()


class TidalLoginDialog(Adw.PreferencesWindow):
    """
    Conexión con TIDAL: datos de la app de desarrollador (una vez) e inicio de sesión en la web
    de TIDAL, que devuelve el control a MyFlac por la dirección local registrada en la app.
    """

    def __init__(self, parent=None, on_auth_changed: Callable[[], None] | None = None):
        super().__init__()
        self.client = get_tidal_client()
        self.on_auth_changed = on_auth_changed
        self.set_title(i18n.t("tidal.dialog.title"))
        self.set_default_size(540, 460)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        page = Adw.PreferencesPage()
        self.add(page)

        login_group = Adw.PreferencesGroup()
        login_group.set_title(i18n.t("tidal.dialog.login_group"))
        login_group.set_description(i18n.t("tidal.dialog.login_help"))
        page.add(login_group)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.btn_login = Gtk.Button(label=i18n.t("tidal.dialog.login_btn"))
        self.btn_login.add_css_class("suggested-action")
        self.btn_login.add_css_class("pill")
        self.btn_login.set_halign(Gtk.Align.CENTER)
        self.btn_login.connect("clicked", self._on_login_clicked)
        box.append(self.btn_login)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        box.append(self.spinner)
        self.feedback = Gtk.Label(label="")
        self.feedback.set_wrap(True)
        self.feedback.add_css_class("dim-label")
        box.append(self.feedback)
        login_group.add(box)

        # Opcional: otra app de desarrollador propia (MyFlac ya trae la suya)
        app_group = Adw.PreferencesGroup()
        page.add(app_group)
        expander = Adw.ExpanderRow(title=i18n.t("tidal.dialog.app_group"),
                                   subtitle=i18n.t("tidal.dialog.app_help", redirect=DEFAULT_REDIRECT_URI))
        app_group.add(expander)
        custom = self.client.client_id != DEFAULT_CLIENT_ID
        self.client_id_row = Adw.EntryRow(title=i18n.t("tidal.dialog.client_id"))
        self.client_id_row.set_text(self.client.client_id if custom else "")
        expander.add_row(self.client_id_row)
        self.redirect_row = Adw.EntryRow(title=i18n.t("tidal.dialog.redirect_uri"))
        self.redirect_row.set_text(self.client.redirect_uri or DEFAULT_REDIRECT_URI)
        expander.add_row(self.redirect_row)
        expander.set_expanded(custom)

    def _open_url(self, url: str):
        """Abre la web de inicio de sesión de TIDAL en el navegador (desde el hilo de la interfaz)."""
        def launch():
            Gtk.UriLauncher.new(url).launch(self, None, None)
            return False
        GLib.idle_add(launch)

    def _on_login_clicked(self, _btn):
        # Sin app propia se usa la de MyFlac
        self.client.set_app_credentials(self.client_id_row.get_text(), "", self.redirect_row.get_text())
        self.btn_login.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.feedback.set_text(i18n.t("tidal.dialog.waiting_browser"))

        def worker():
            try:
                self.client.login_interactive(self._open_url)
                error = ""
            except QobuzError as e:
                error = str(e)
            except Exception as e:
                log.exception("Error inesperado al iniciar sesión en TIDAL")
                error = str(e)
            GLib.idle_add(lambda: (self._on_done(error), False)[1])

        threading.Thread(target=worker, daemon=True, name="tidal-login").start()

    def _on_done(self, error: str):
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.btn_login.set_sensitive(True)
        if error:
            self.feedback.set_text(error)
            return
        self.feedback.set_text(i18n.t("qobuz.dialog.login_success",
                                      name=self.client.user_display_name or "TIDAL"))
        if self.on_auth_changed:
            self.on_auth_changed()
        GLib.timeout_add(800, lambda: (self.close(), False)[1])


class TidalAccountDialog(Adw.PreferencesWindow):
    """Cuenta de TIDAL conectada y cierre de sesión."""

    def __init__(self, parent=None, on_auth_changed: Callable[[], None] | None = None):
        super().__init__()
        self.client = get_tidal_client()
        self.on_auth_changed = on_auth_changed
        self.set_title(i18n.t("tidal.dialog.account_title"))
        self.set_default_size(480, 320)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        page = Adw.PreferencesPage()
        self.add(page)
        group = Adw.PreferencesGroup()
        group.set_title(i18n.t("qobuz.dialog.status_group"))
        page.add(group)
        user = Adw.ActionRow(title=self.client.user_display_name or i18n.t("qobuz.dialog.user_fallback"),
                             subtitle=self.client.user_email or i18n.t("qobuz.dialog.session_active"))
        user.set_icon_name("avatar-default-symbolic")
        group.add(user)
        country = Adw.ActionRow(title=i18n.t("tidal.dialog.country"), subtitle=self.client.country)
        country.set_icon_name("mark-location-symbolic")
        group.add(country)

        btn = Gtk.Button(label=i18n.t("tidal.dialog.logout_btn"))
        btn.add_css_class("destructive-action")
        btn.add_css_class("pill")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_margin_top(24)
        btn.connect("clicked", self._on_logout)
        group.add(btn)

    def _on_logout(self, _btn):
        self.client.logout()
        if self.on_auth_changed:
            self.on_auth_changed()
        self.close()
