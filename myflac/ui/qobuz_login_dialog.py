"""Diálogos de inicio de sesión y gestión de cuenta de Qobuz (GTK4 / Libadwaita).

La ventana de acceso web necesita WebKitGTK 6.0, que es opcional: si no está instalado se usa el
acceso con correo y contraseña (o token), que no depende de él.
"""
from __future__ import annotations

import json
import threading
from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..logger import get_logger
from ..streaming.qobuz_client import QobuzError, get_qobuz_client
from .. import i18n

log = get_logger("ui.qobuz_login")

WEB_OAUTH_URL = "https://www.qobuz.com/signin/oauth?ext_app_id={app_id}&redirect_url=https://play.qobuz.com"


def _webkit():
    """Módulo WebKit 6.0 o None si no está instalado."""
    try:
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit
        return WebKit
    except (ValueError, ImportError):
        return None


def _run_in_thread(job: Callable[[], None], done: Callable[[str], None]):
    """Ejecuta `job` fuera del hilo de la interfaz; `done` recibe el error ('' si fue bien)."""
    def worker():
        try:
            job()
            error = ""
        except QobuzError as e:
            error = str(e)
        except Exception as e:
            log.exception("Error inesperado con Qobuz")
            error = i18n.t("qobuz.err.network", error=e)
        GLib.idle_add(lambda: (done(error), False)[1])

    threading.Thread(target=worker, daemon=True, name="qobuz-auth").start()


class QobuzWebLoginWindow(Adw.Window):
    """
    Inicio de sesión en la web oficial de Qobuz (usuario y contraseña, Google o Apple). Captura la
    sesión en cuanto el usuario entra y se cierra sola.
    """

    def __init__(self, parent=None, on_auth_changed: Callable[[], None] | None = None):
        super().__init__()
        self.WebKit = _webkit()
        self.client = get_qobuz_client()
        self.on_auth_changed = on_auth_changed
        self._auth_completed = False
        self._poll_timer_id = 0

        self.set_title(i18n.t("qobuz.dialog.web_window_title"))
        self.set_default_size(1050, 760)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self.connect("close-request", self._on_close_request)
        self._build_ui()

    def _on_close_request(self, _win) -> bool:
        self._stop_polling()
        return False

    def _stop_polling(self):
        if self._poll_timer_id:
            GLib.source_remove(self._poll_timer_id)
            self._poll_timer_id = 0

    def _build_ui(self):
        WebKit = self.WebKit
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(
            title=i18n.t("qobuz.dialog.web_window_title"),
            subtitle=i18n.t("qobuz.dialog.web_subtitle"),
        )
        header.set_title_widget(self.title_widget)

        btn_other = Gtk.Button(label=i18n.t("qobuz.dialog.other_methods_btn"))
        btn_other.add_css_class("flat")
        btn_other.set_tooltip_text(i18n.t("qobuz.manual_token_btn"))
        btn_other.connect("clicked", self._open_manual_dialog)
        header.pack_end(btn_other)
        vbox.append(header)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.add_css_class("osd")
        vbox.append(self.progress_bar)

        self.wv = WebKit.WebView()
        self.wv.get_settings().set_enable_javascript(True)
        self.wv.set_hexpand(True)
        self.wv.set_vexpand(True)
        self.wv.connect("notify::estimated-load-progress", self._on_progress_changed)
        self.wv.connect("load-changed", self._on_load_changed)
        vbox.append(self.wv)
        self.set_content(vbox)

        self.wv.load_uri(WEB_OAUTH_URL.format(app_id=self.client.app_id))

    def _on_progress_changed(self, view, _param):
        p = view.get_estimated_load_progress()
        self.progress_bar.set_fraction(p)
        self.progress_bar.set_visible(p < 1.0)

    def _on_load_changed(self, view, event):
        if event != self.WebKit.LoadEvent.FINISHED or self._auth_completed:
            return
        uri = view.get_uri() or ""
        log.debug("Acceso web de Qobuz: página cargada %s", uri.split("?", 1)[0])
        if "play.qobuz.com" in uri:
            self.title_widget.set_subtitle(i18n.t("qobuz.dialog.syncing"))
            self._start_session_polling(view)

    def _start_session_polling(self, view):
        self._stop_polling()
        attempts = [0]

        def on_read_done(source, res):
            if self._auth_completed:
                return
            try:
                val = source.evaluate_javascript_finish(res).to_string()
                data = json.loads(val) if val and val.startswith("{") else {}
            except Exception as e:
                log.debug("No se pudo leer la sesión del reproductor web: %s", e)
                return
            token = data.get("token") or data.get("user_auth_token")
            if not token:
                return
            self._auth_completed = True
            self._stop_polling()
            user = data.get("user") if isinstance(data.get("user"), dict) else {}
            email = data.get("email") or user.get("email") or ""
            name = data.get("display_name") or user.get("display_name") or user.get("login") or email
            self.client.set_auth_data(token, email, name)
            _run_in_thread(self.client.complete_web_login, self._on_login_completed)

        def poll_step():
            if self._auth_completed:
                return False
            attempts[0] += 1
            if attempts[0] > 120:  # ~40 s
                log.warning("No se encontró la sesión en el reproductor web de Qobuz")
                self.title_widget.set_subtitle(i18n.t("qobuz.dialog.session_not_found"))
                self._poll_timer_id = 0
                return False
            view.evaluate_javascript("localStorage.getItem('localuser') || ''", -1, None, None, None,
                                     on_read_done)
            return True

        self._poll_timer_id = GLib.timeout_add(350, poll_step)

    def _on_login_completed(self, error: str):
        if error:
            self.title_widget.set_subtitle(error)
            self._auth_completed = False
            return
        name = self.client.user_display_name or self.client.user_email
        self.title_widget.set_subtitle(i18n.t("qobuz.dialog.login_success", name=name))
        if self.on_auth_changed:
            self.on_auth_changed()
        GLib.timeout_add(800, lambda: (self.close(), False)[1])

    def _open_manual_dialog(self, _btn):
        dlg = QobuzManualTokenDialog(parent=self, on_auth_changed=self._on_manual_success)
        dlg.present()

    def _on_manual_success(self):
        if self.on_auth_changed:
            self.on_auth_changed()
        self.close()


class QobuzAccountDialog(Adw.PreferencesWindow):
    """Estado de la cuenta conectada y cierre de sesión."""

    def __init__(self, parent=None, on_auth_changed: Callable[[], None] | None = None):
        super().__init__()
        self.client = get_qobuz_client()
        self.on_auth_changed = on_auth_changed

        self.set_title(i18n.t("qobuz.dialog.title"))
        self.set_default_size(480, 360)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        page = Adw.PreferencesPage()
        self.add(page)

        group = Adw.PreferencesGroup()
        group.set_title(i18n.t("qobuz.dialog.status_group"))
        page.add(group)

        user_row = Adw.ActionRow(
            title=self.client.user_display_name or self.client.user_email or i18n.t("qobuz.dialog.user_fallback"),
            subtitle=self.client.user_email or i18n.t("qobuz.dialog.session_active"),
        )
        user_row.set_icon_name("avatar-default-symbolic")
        group.add(user_row)

        sub_row = Adw.ActionRow(
            title=i18n.t("qobuz.dialog.subscription_type"),
            subtitle=self.client.subscription_label or i18n.t("qobuz.dialog.subscription_unknown"),
        )
        sub_row.set_icon_name("audio-card-symbolic")
        group.add(sub_row)

        btn_logout = Gtk.Button(label=i18n.t("qobuz.dialog.logout_btn"))
        btn_logout.add_css_class("destructive-action")
        btn_logout.add_css_class("pill")
        btn_logout.set_halign(Gtk.Align.CENTER)
        btn_logout.set_margin_top(24)
        btn_logout.connect("clicked", self._on_logout_clicked)
        group.add(btn_logout)

    def _on_logout_clicked(self, _btn):
        self.client.logout()
        if self.on_auth_changed:
            self.on_auth_changed()
        self.close()


class QobuzManualTokenDialog(Adw.PreferencesWindow):
    """Inicio de sesión con correo y contraseña, o con un token de usuario."""

    def __init__(self, parent=None, on_auth_changed: Callable[[], None] | None = None):
        super().__init__()
        self.client = get_qobuz_client()
        self.on_auth_changed = on_auth_changed

        self.set_title(i18n.t("qobuz.manual_token_dialog_title"))
        self.set_default_size(500, 460)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        page = Adw.PreferencesPage()
        self.add(page)

        # Correo y contraseña (la contraseña no se guarda: solo el token que devuelve Qobuz)
        login_group = Adw.PreferencesGroup()
        login_group.set_title(i18n.t("qobuz.dialog.login_group"))
        login_group.set_description(i18n.t("qobuz.dialog.login_description"))
        page.add(login_group)

        self.email_entry = Adw.EntryRow(title=i18n.t("qobuz.dialog.email_user_row"))
        login_group.add(self.email_entry)
        self.password_entry = Adw.PasswordEntryRow(title=i18n.t("qobuz.dialog.password_row"))
        self.password_entry.connect("entry-activated", self._on_login_clicked)
        login_group.add(self.password_entry)

        self.btn_login = Gtk.Button(label=i18n.t("qobuz.dialog.login_btn"))
        self.btn_login.add_css_class("suggested-action")
        self.btn_login.add_css_class("pill")
        self.btn_login.set_halign(Gtk.Align.CENTER)
        self.btn_login.set_margin_top(12)
        self.btn_login.connect("clicked", self._on_login_clicked)
        login_group.add(self.btn_login)

        # Token de usuario (opciones avanzadas)
        token_group = Adw.PreferencesGroup()
        token_group.set_title(i18n.t("qobuz.dialog.advanced_token_row"))
        page.add(token_group)

        self.token_entry = Adw.PasswordEntryRow(title=i18n.t("qobuz.dialog.token_row"))
        self.token_entry.connect("entry-activated", self._on_connect_clicked)
        token_group.add(self.token_entry)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        self.btn_connect = Gtk.Button(label=i18n.t("qobuz.dialog.connect_token_btn"))
        self.btn_connect.add_css_class("pill")
        self.btn_connect.set_halign(Gtk.Align.CENTER)
        self.btn_connect.connect("clicked", self._on_connect_clicked)
        box.append(self.btn_connect)

        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        box.append(self.spinner)

        self.feedback_label = Gtk.Label(label="")
        self.feedback_label.set_wrap(True)
        self.feedback_label.add_css_class("dim-label")
        box.append(self.feedback_label)
        token_group.add(box)

    def _busy(self, busy: bool, text: str = ""):
        self.btn_login.set_sensitive(not busy)
        self.btn_connect.set_sensitive(not busy)
        self.spinner.set_visible(busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.feedback_label.set_text(text)

    def _on_login_clicked(self, _widget):
        email = self.email_entry.get_text().strip()
        password = self.password_entry.get_text()
        if not email or not password:
            self.feedback_label.set_text(i18n.t("qobuz.dialog.prompt_creds"))
            return
        self._busy(True, i18n.t("qobuz.dialog.logging_in"))
        _run_in_thread(lambda: self.client.login_with_password(email, password), self._on_done)

    def _on_connect_clicked(self, _widget):
        token = self.token_entry.get_text().strip()
        if not token:
            self.feedback_label.set_text(i18n.t("qobuz.dialog.prompt_token"))
            return
        self._busy(True, i18n.t("qobuz.dialog.verifying"))
        _run_in_thread(lambda: self.client.set_auth_token(token), self._on_done)

    def _on_done(self, error: str):
        if error:
            self._busy(False, error)
            return
        name = self.client.user_display_name or self.client.user_email or "Qobuz"
        self._busy(False, i18n.t("qobuz.dialog.login_success", name=name))
        self.password_entry.set_text("")
        if self.on_auth_changed:
            self.on_auth_changed()
        GLib.timeout_add(800, lambda: (self.close(), False)[1])


def QobuzLoginDialog(parent=None, on_auth_changed: Callable[[], None] | None = None) -> Gtk.Window:
    """
    Con sesión iniciada abre el estado de la cuenta. Sin sesión, la web oficial de Qobuz si
    WebKitGTK está instalado y hay credenciales de aplicación; si no, el acceso con correo o token.
    """
    client = get_qobuz_client()
    if client.is_logged_in:
        return QobuzAccountDialog(parent=parent, on_auth_changed=on_auth_changed)
    if _webkit() is not None and client.has_app_credentials:
        return QobuzWebLoginWindow(parent=parent, on_auth_changed=on_auth_changed)
    return QobuzManualTokenDialog(parent=parent, on_auth_changed=on_auth_changed)
