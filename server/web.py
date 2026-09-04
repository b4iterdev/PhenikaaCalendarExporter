from __future__ import annotations

import html
import io
import json
import secrets
import shutil
import tempfile
import urllib.parse
import zipfile
from datetime import date, datetime
from email.parser import BytesParser
from email.policy import default
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from phenikaa_exporter import export_calendar_files, parse_bootstrap_html
from phenikaa_login import LoginTimeout

from server.config import ServerConfig, academic_year_range
from server.crypto import TokenVault, token_fingerprint
from server.db import (
    Database,
    GOOGLE_PRIMARY_CLEANUP_PENDING,
    OwnerSessionExistsError,
    STATUS_NEEDS_HUMAN,
    STATUS_PENDING_LOGIN,
)
from server.google import LEGACY_CLEANUP_SCOPE, SCOPE
from server.legal import privacy_policy_body, terms_body
from server.login_broker import LoginBroker, validate_event
from server.oidc import OidcClient, SignedSessions, new_authorization_state

APP_COOKIE = "phenikaa_server_session"
OIDC_COOKIE = "phenikaa_oidc_transaction"
GOOGLE_OAUTH_COOKIE = "phenikaa_google_oauth_transaction"
LANGUAGE_COOKIE = "phenikaa_ui_language"
STATUS_LABELS = {
    "pending_login": "Action required",
    "active": "Connected",
    "needs_human": "Attention needed",
    "disabled": "Disabled",
}
MAX_EXPORT_FORM_BYTES = 1024 * 1024


class GoogleCalendarWebService(Protocol):
    def authorization_url(self, state: str, scope: str = SCOPE) -> str:
        raise NotImplementedError

    def exchange_code(self, session_id: str, code: str, requested_scope: str = SCOPE) -> None:
        pass

    def disconnect(self, session_id: str) -> None:
        pass


class SyncRequester(Protocol):
    def request_sync(self, session_id: str) -> None:
        pass


class CalendarExporter(Protocol):
    def __call__(
        self,
        session: dict[str, Any],
        start: date,
        end: date,
        output_dir: Path | str,
        prefix: str,
        calendar_name: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


class ServerApplication:
    def __init__(
        self,
        config: ServerConfig,
        database: Database,
        vault: TokenVault,
        signed_sessions: SignedSessions,
        broker: LoginBroker,
        sync_engine: SyncRequester,
        oidc: OidcClient | None,
        google: GoogleCalendarWebService | None = None,
        calendar_exporter: CalendarExporter = export_calendar_files,
    ) -> None:
        self.config = config
        self.database = database
        self.vault = vault
        self.signed_sessions = signed_sessions
        self.broker = broker
        self.sync_engine = sync_engine
        self.oidc = oidc
        self.google = google
        self.calendar_exporter = calendar_exporter

    def handler(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "PhenikaaCalendarServer/1.0"

            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                application.handle_get(self)

            def do_POST(self) -> None:
                application.handle_post(self)

        return Handler

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urllib.parse.urlsplit(handler.path)
        path = parsed.path
        if path == "/healthz":
            self._json(handler, 200, {"ok": True})
            return
        if path == "/static/styles.css":
            self._stylesheet(handler)
            return
        if path == "/favicon.ico":
            self._empty(handler, 204)
            return
        if path == "/privacy":
            self._html(handler, 200, self._layout("Privacy Policy", privacy_policy_body(self.config.policy_contact)))
            return
        if path == "/terms":
            self._html(handler, 200, self._layout("Terms of Service", terms_body(self.config.policy_contact)))
            return
        if path == "/auth/login":
            self._start_oidc(handler)
            return
        if path == "/auth/callback":
            self._finish_oidc(handler, urllib.parse.parse_qs(parsed.query))
            return
        if path == "/auth/google/callback":
            self._finish_google_oauth(handler, urllib.parse.parse_qs(parsed.query))
            return
        identity = self._identity(handler)
        if identity is None:
            if path == "/":
                self._landing(handler)
                return
            self._redirect(handler, "/auth/login")
            return
        user = self.database.get_or_create_user(str(identity["sub"]), str(identity.get("name") or identity["sub"]))
        if path == "/language":
            language = (urllib.parse.parse_qs(parsed.query).get("lang") or [""])[0]
            if language not in ("en", "vi"):
                self._error(handler, 400, "unsupported language")
                return
            target = (urllib.parse.parse_qs(parsed.query).get("return") or ["/"])[0]
            if target not in ("/", "/settings"):
                target = "/"
            self._redirect_language(handler, target, language)
            return
        if path == "/":
            self._dashboard(handler, user, identity)
            return
        if path == "/settings":
            self._settings(handler, user, identity)
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "sessions":
            session = self._owned_session(handler, parts[1], int(user["id"]))
            if session is None:
                return
            if len(parts) == 3 and parts[2] == "login":
                self._login_page(handler, session, identity)
                return
            if len(parts) == 3 and parts[2] == "stream":
                self._stream(handler, str(session["id"]))
                return
            if len(parts) == 3 and parts[2] == "status.json":
                self._status(handler, session)
                return
            if len(parts) == 4 and parts[2] == "google" and parts[3] == "connect":
                self._start_google_oauth(handler, session)
                return
            if len(parts) == 4 and parts[2] == "download" and parts[3] in ("calendar.json", "calendar.ics"):
                self._download(handler, str(session["id"]), parts[3])
                return
        self._error(handler, 404, "not found")

    def handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        path = urllib.parse.urlsplit(handler.path).path
        identity = self._identity(handler)
        if identity is None:
            self._error(handler, 401, "authentication required")
            return
        try:
            form = self._read_export_form(handler) if path == "/export" else self._read_form(handler)
        except OverflowError:
            self._error(handler, 413, "export form is too large")
            return
        except (UnicodeError, ValueError):
            self._error(handler, 400, "invalid form submission")
            return
        if not self._csrf_valid(handler, identity, form):
            self._error(handler, 403, "invalid CSRF token")
            return
        if path == "/export":
            self._export(handler, form)
            return
        user = self.database.get_or_create_user(str(identity["sub"]), str(identity.get("name") or identity["sub"]))
        if path == "/auth/logout":
            self._redirect(handler, "/", clear_cookie=True)
            return
        if path == "/account/delete":
            if str(form.get("confirmation") or "") != "DELETE":
                self._error(handler, 400, "type DELETE to confirm account deletion")
                return
            for session in self.database.list_sessions(int(user["id"])):
                session_id = str(session["id"])
                lock = self.broker.try_profile_lock(session_id)
                if lock is None:
                    self._error(handler, 409, "session is busy; retry after login or sync finishes")
                    return
                try:
                    if self.google is not None and self.database.get_google_connection(session_id) is not None:
                        self.google.disconnect(session_id)
                    self.broker.delete_profile(session_id)
                    shutil.rmtree(self.config.exports_dir / session_id, ignore_errors=True)
                    self.broker.forget_attempt(session_id)
                finally:
                    lock.release()
            self.database.delete_user(int(user["id"]))
            self._redirect(handler, "/", clear_cookie=True)
            return
        if path == "/sessions":
            default_start, default_end = academic_year_range()
            try:
                start, end = self._validated_range(
                    str(form.get("range_start") or default_start.isoformat()),
                    str(form.get("range_end") or default_end.isoformat()),
                )
            except ValueError as error:
                self._error(handler, 400, str(error))
                return
            try:
                session_id = self.database.create_session(
                    int(user["id"]),
                    label=str(form.get("label") or "Phenikaa account")[:80],
                    range_start=start,
                    range_end=end,
                    sync_interval_hours=self.config.sync_interval_hours,
                )
            except OwnerSessionExistsError:
                self._error(handler, 409, "user already has a Phenikaa session")
                return
            self._redirect(handler, f"/sessions/{session_id}/login")
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[0] == "sessions":
            session = self._owned_session(handler, parts[1], int(user["id"]))
            if session is None:
                return
            action = parts[2]
            if action == "event":
                attempt = self.broker.get_attempt(str(session["id"]))
                try:
                    event = validate_event(self._read_json(handler))
                except (json.JSONDecodeError, UnicodeError):
                    event = None
                if attempt is None or event is None or not attempt.push_event(event):
                    self._error(handler, 400, "event rejected")
                else:
                    self._empty(handler, 204)
                return
            if action == "sync":
                self.sync_engine.request_sync(str(session["id"]))
                self._redirect(handler, "/")
                return
            if action == "settings":
                try:
                    start, end = self._validated_range(
                        str(form.get("range_start") or session["range_start"]),
                        str(form.get("range_end") or session["range_end"]),
                    )
                except ValueError as error:
                    self._error(handler, 400, str(error))
                    return
                self.database.update_session_range(
                    str(session["id"]),
                    range_start=start,
                    range_end=end,
                )
                self._redirect(handler, "/")
                return
            if action == "delete":
                session_id = str(session["id"])
                lock = self.broker.try_profile_lock(session_id)
                if lock is None:
                    self._error(handler, 409, "session is busy; retry after login or sync finishes")
                    return
                try:
                    self.broker.delete_profile(session_id)
                    shutil.rmtree(self.config.exports_dir / session_id, ignore_errors=True)
                    self.database.delete_session(session_id)
                    self.broker.forget_attempt(session_id)
                finally:
                    lock.release()
                self._redirect(handler, "/")
                return
        if len(parts) == 4 and parts[0] == "sessions" and parts[2] == "google" and parts[3] == "disconnect":
            session = self._owned_session(handler, parts[1], int(user["id"]))
            if session is None:
                return
            if self.google is None:
                self._error(handler, 503, "Google Calendar is not configured")
                return
            lock = self.broker.try_profile_lock(str(session["id"]))
            if lock is None:
                self._error(handler, 409, "session is busy; retry after login or sync finishes")
                return
            try:
                self.google.disconnect(str(session["id"]))
            except Exception:
                self._error(handler, 502, "Google Calendar disconnect failed")
                return
            finally:
                lock.release()
            self._redirect(handler, "/")
            return
        self._error(handler, 404, "not found")

    def _identity(self, handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
        if self.config.auth_mode == "disabled":
            return {"sub": "local-development-user", "name": "Local user", "csrf": "development"}
        value = self._cookie(handler, APP_COOKIE)
        return self.signed_sessions.verify(value) if value else None

    def _start_oidc(self, handler: BaseHTTPRequestHandler) -> None:
        if self.config.auth_mode == "disabled":
            self._redirect(handler, "/")
            return
        if self.oidc is None:
            self._error(handler, 503, "OIDC is not configured")
            return
        state, nonce, verifier, challenge = new_authorization_state()
        transaction = self.signed_sessions.create(
            {"state": state, "nonce": nonce, "verifier": verifier}, lifetime=600
        )
        url = self.oidc.authorization_url(state, nonce, challenge)
        self._redirect(handler, url, set_cookie=(OIDC_COOKIE, transaction, 600))

    def _finish_oidc(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> None:
        transaction = self.signed_sessions.verify(self._cookie(handler, OIDC_COOKIE) or "")
        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        if not transaction or not secrets.compare_digest(state, str(transaction.get("state", ""))) or not code:
            self._error(handler, 400, "invalid OIDC callback")
            return
        if self.oidc is None:
            self._error(handler, 503, "OIDC is not configured")
            return
        try:
            claims = self.oidc.exchange_code(code, str(transaction["verifier"]), str(transaction["nonce"]))
        except Exception:
            self._error(handler, 502, "OIDC authentication failed")
            return
        csrf = secrets.token_urlsafe(24)
        app_session = self.signed_sessions.create({
            "sub": str(claims["sub"]),
            "name": str(claims.get("name") or claims.get("email") or claims["sub"]),
            "csrf": csrf,
        })
        self._redirect(handler, "/", set_cookie=(APP_COOKIE, app_session, 8 * 60 * 60))

    def _start_google_oauth(self, handler: BaseHTTPRequestHandler, session: dict[str, Any]) -> None:
        if self.google is None:
            self._error(handler, 503, "Google Calendar is not configured")
            return
        state = secrets.token_urlsafe(32)
        requested_scope = self._google_requested_scope(str(session["id"]))
        transaction = self.signed_sessions.create(
            {"state": state, "session_id": str(session["id"]), "requested_scope": requested_scope}, lifetime=600
        )
        self._redirect(
            handler,
            self.google.authorization_url(state, requested_scope),
            set_cookie=(GOOGLE_OAUTH_COOKIE, transaction, 600),
        )


    def _google_requested_scope(self, session_id: str) -> str:
        state = self.database.get_google_calendar_state(session_id)
        if state is not None and state.get("migration_state") == GOOGLE_PRIMARY_CLEANUP_PENDING:
            return LEGACY_CLEANUP_SCOPE
        return SCOPE

    def _finish_google_oauth(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> None:
        clear_google_cookie = GOOGLE_OAUTH_COOKIE
        if self.google is None:
            self._error(handler, 503, "Google Calendar is not configured", clear_cookie=clear_google_cookie)
            return
        identity = self._identity(handler)
        if identity is None:
            self._error(handler, 401, "authentication required", clear_cookie=clear_google_cookie)
            return
        google_error = (query.get("error") or [""])[0]
        if google_error:
            self._error(
                handler,
                400,
                "Google OAuth failed: " + str(google_error)[:120],
                clear_cookie=clear_google_cookie,
            )
            return
        transaction = self.signed_sessions.verify(self._cookie(handler, GOOGLE_OAUTH_COOKIE) or "")
        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        if not transaction or not secrets.compare_digest(state, str(transaction.get("state", ""))) or not code:
            self._error(handler, 400, "invalid Google OAuth callback", clear_cookie=clear_google_cookie)
            return
        user = self.database.get_or_create_user(str(identity["sub"]), str(identity.get("name") or identity["sub"]))
        session = self.database.get_session(str(transaction.get("session_id") or ""))
        if session is None or int(session["owner_user_id"]) != int(user["id"]):
            self._error(handler, 404, "session not found", clear_cookie=clear_google_cookie)
            return
        lock = getattr(self.broker, "try_profile_lock")(str(session["id"]), blocking=True)
        if lock is None:
            self._error(handler, 409, "session is busy; retry after login or sync finishes", clear_cookie=clear_google_cookie)
            return
        try:
            self.google.exchange_code(str(session["id"]), code, str(transaction.get("requested_scope") or SCOPE))
        except Exception:
            self._error(handler, 502, "Google OAuth token exchange failed", clear_cookie=clear_google_cookie)
            return
        finally:
            lock.release()
        self.sync_engine.request_sync(str(session["id"]))
        self._redirect(handler, "/", clear_cookie=clear_google_cookie)

    def _dashboard(self, handler: BaseHTTPRequestHandler, user: dict[str, Any], identity: dict[str, Any]) -> None:
        csrf = html.escape(str(identity["csrf"]))
        language = self._language(handler)
        vi = language == "vi"
        text = {
            "sessions": "Các phiên lịch của bạn" if vi else "Your calendar sessions",
            "description": "Kết nối, cấu hình và xuất lịch học của bạn từ một nơi." if vi else "Connect, configure, and export your academic calendar from one place.",
            "export_eyebrow": "Xuất một lần" if vi else "One-shot export",
            "export_title": "Tải xuống không đồng bộ" if vi else "Download without syncing",
            "export_description": "Thông tin đăng nhập chỉ được giữ trong bộ nhớ cho yêu cầu này và không được thêm vào phiên trên máy chủ." if vi else "Credentials stay in memory for this request and are not added to a server session.",
            "from": "Từ" if vi else "From", "to": "Đến" if vi else "To",
            "saved": "Trang đã xác thực" if vi else "Saved authenticated page",
            "html": "HTML index.aspx đã xác thực" if vi else "Authenticated index.aspx HTML",
            "file_hint": "Chọn mã nguồn trang đã lưu có chứa AXYZCLRVN. Tệp có token riêng tư; hãy xóa tệp sau khi hoàn tất." if vi else "Choose the saved page source containing AXYZCLRVN. The file contains a private token; delete it when finished.",
            "manual": "Phiên thủ công" if vi else "Manual session", "user_id": "ID người dùng" if vi else "User ID",
            "manual_hint": "Cung cấp cả hai trường và để trống trường trang đã lưu." if vi else "Provide both fields and leave the saved-page field empty.",
            "export": "Xuất tệp lịch" if vi else "Export calendar files", "or": "hoặc" if vi else "or",
        }
        rows = []
        summary = []
        for session in self.database.list_sessions(int(user["id"])):
            sid = html.escape(str(session["id"]))
            label = html.escape(str(session["label"]))
            status = html.escape(str(session["status"]))
            status_label = html.escape(self._status_label(str(session["status"]), language))
            error = html.escape(str(session.get("last_sync_error") or ""))
            google = self._google_status_markup(str(session["id"]), csrf, language)
            is_active = str(session["status"]) == "active"
            export_dir = self.config.exports_dir / str(session["id"])
            has_exports = is_active and (export_dir / "calendar.ics").is_file() and (export_dir / "calendar.json").is_file()
            downloads = "" if not has_exports else f"""
            <div class="session-section"><h3>{'Tệp đã xuất' if vi else 'Exports'}</h3><div class="action-row"><a class="button button--quiet" href="/sessions/{sid}/download/calendar.ics">Download ICS</a><a class="button button--quiet" href="/sessions/{sid}/download/calendar.json">Download JSON</a></div></div>"""
            sync_action = "" if not is_active else f"""<form method="post" action="/sessions/{sid}/sync"><input type="hidden" name="csrf" value="{csrf}"><button class="button button--primary">{'Đồng bộ lịch' if vi else 'Sync calendar'}</button></form>"""
            last_sync = html.escape(self._friendly_timestamp(session.get("last_sync_at"), language))
            summary.append(f"<div class=\"summary-item\"><span>{label}</span><strong>{status_label}</strong><small>{last_sync}</small></div>")
            rows.append(f"""
            <article class="session-card"><div class="session-card__head"><div><p class="eyebrow">Phenikaa account</p><h2>{label}</h2></div><span class="status status--{status}">{status_label}</span></div>
            <p class="session-card__error">{error}</p><div class="session-section session-section--connection"><h3>{'Kết nối' if vi else 'Connection'}</h3><div class="action-row"><a class="button button--primary" href="/sessions/{sid}/login">{'Kết nối lại tài khoản' if is_active and vi else 'Reconnect account' if is_active else 'Đăng nhập để kết nối' if vi else 'Sign in to connect'}</a>{sync_action}</div></div>
            <div class="session-section"><h3>{'Khoảng thời gian lịch' if vi else 'Calendar range'}</h3><form class="range-form" method="post" action="/sessions/{sid}/settings"><input type="hidden" name="csrf" value="{csrf}">
            <div class="field-group"><label>{text['from']} <input type="date" name="range_start" value="{html.escape(str(session.get('range_start') or ''))}"></label><label>{text['to']} <input type="date" name="range_end" value="{html.escape(str(session.get('range_end') or ''))}"></label></div>
            <button class="button button--primary">{'Lưu khoảng thời gian' if vi else 'Save date range'}</button></form></div>
            {downloads}<div class="session-section"><h3>Google Calendar</h3><div class="integration">{google}</div></div></article>""")
        start, end = academic_year_range()
        new_session_form = "" if rows else f"""
         <section class="setup-card"><p class="eyebrow">{'KẾT NỐI ĐẦU TIÊN' if vi else 'FIRST CONNECTION'}</p><h2>{'Phiên mới: kết nối tài khoản Phenikaa' if vi else 'New session: connect a Phenikaa account'}</h2><p>{'Chọn khoảng thời gian học tập, sau đó đăng nhập một lần. Máy chủ mã hóa và tự động theo dõi phiên của bạn.' if vi else 'Choose an academic window, then sign in once. The server keeps the session encrypted and watches it for refreshes.'}</p><form method="post" action="/sessions">
        <input type="hidden" name="csrf" value="{csrf}"><label>Name <input name="label" value="Phenikaa account"></label>
         <label>{text['from']} <input type="date" name="range_start" value="{start.isoformat()}"></label>
         <label>{text['to']} <input type="date" name="range_end" value="{end.isoformat()}"></label><button class="button button--primary">{'Tạo và đăng nhập' if vi else 'Create and sign in'}</button></form></section>
        """
        summary_markup = f"<section class=\"summary-grid\">{''.join(summary)}</section>" if summary else ""
        export_form = f"""<section class=\"export-panel\"><div class=\"section-heading\"><div><p class=\"eyebrow\">{text['export_eyebrow']}</p><h2>{text['export_title']}</h2></div><p class=\"page-description\">{text['export_description']}</p></div>
         <form class=\"export-form\" method=\"post\" action=\"/export\" enctype=\"multipart/form-data\"><input type=\"hidden\" name=\"csrf\" value=\"{csrf}\">
        <div class=\"date-row\"><label>From <input required type=\"date\" name=\"range_start\" value=\"{start.isoformat()}\"></label>
        <label>To <input required type=\"date\" name=\"range_end\" value=\"{end.isoformat()}\"></label></div>
         <div class=\"credential-grid\"><fieldset><legend>{text['saved']}</legend><label>{text['html']}<input type=\"file\" name=\"bootstrap_file\" accept=\".html,text/html\"></label><p class=\"hint\">{text['file_hint']}</p></fieldset>
        <div class=\"or\" aria-hidden=\"true\">{text['or']}</div><fieldset><legend>{text['manual']}</legend><label>{text['user_id']}<input name=\"userId\" autocomplete=\"off\"></label><label>Token JWT<input type=\"password\" name=\"tokenJWT\" autocomplete=\"off\"></label><p class=\"hint\">{text['manual_hint']}</p></fieldset></div>
        <button class=\"button button--primary\" type=\"submit\">{text['export']}</button></form></section>"""
        body = f"""
        {self._navigation(user, identity, "dashboard", language)}
         <main><div class="section-heading"><div><p class="eyebrow">{'PHIÊN LỊCH' if vi else 'Calendar sessions'}</p><h2>{text['sessions']}</h2><p class="page-description">{text['description']}</p></div></div>{export_form}{summary_markup}{new_session_form}
         {''.join(rows) or f'<section class="empty-state"><p class="eyebrow">{"CHƯA CÓ NGUỒN HOẠT ĐỘNG" if vi else "NO ACTIVE SOURCE"}</p><h2>{"Không gian làm việc đã sẵn sàng." if vi else "Your workspace is ready."}</h2><p>{"Kết nối tài khoản Phenikaa ở trên để bắt đầu theo dõi và xuất lịch học của bạn." if vi else "Connect your Phenikaa account above to begin observing and exporting your academic calendar."}</p></section>'}</main>"""
        self._html(handler, 200, self._layout("Calendar sessions", body), no_store=True)

    def _landing(self, handler: BaseHTTPRequestHandler) -> None:
        body = """
        <header class="site-header"><a class="brand" href="/"><span class="brand-mark">P</span><span>PHENIKAA <b>CALENDAR</b></span></a><a class="button button--primary" href="/auth/login">Login</a></header>
        <main><section class="landing-hero"><div><p class="eyebrow">Your semester, made portable</p><h1>Carry your timetable beyond the portal.</h1>
        <p class="hero-lede">Turn Phenikaa classes and exams into calendar files you control. Export once for Apple Calendar, Google Calendar, Outlook, or a spreadsheet. Syncing is entirely optional.</p>
        <p><a class="button button--primary" href="/auth/login">Login to export</a></p></div>
        <div class="calendar-mark" aria-hidden="true"><span>AUG</span><strong>24</strong><small>06:45 · Machine learning</small></div></section>
        <section class="feature-grid" aria-label="How it works"><article><span class="step">01</span><h2>Use your session</h2><p>Bring a saved authenticated page or provide your current portal token manually. Your password is never requested.</p></article>
        <article><span class="step">02</span><h2>Choose your range</h2><p>Select the dates you need, from a single week to the full academic year.</p></article>
        <article><span class="step">03</span><h2>Keep the files</h2><p>Download ICS, XLSX, and JSON together. The one-shot export does not connect to Google or start synchronization.</p></article></section></main>"""
        self._html(handler, 200, self._layout("Phenikaa Calendar Exporter", body), no_store=True)

    def _export(self, handler: BaseHTTPRequestHandler, form: dict[str, str]) -> None:
        try:
            start_value, end_value = self._validated_range(
                str(form.get("range_start") or ""), str(form.get("range_end") or "")
            )
        except ValueError as error:
            self._error(handler, 400, str(error))
            return
        bootstrap_html = str(form.get("bootstrap_html") or "").strip()
        user_id = str(form.get("userId") or "").strip()
        token = str(form.get("tokenJWT") or "").strip()
        has_html = bool(bootstrap_html)
        has_manual = bool(user_id or token)
        if has_html == has_manual:
            self._error(handler, 400, "provide either saved HTML or manual credentials")
            return
        if has_manual and not (user_id and token):
            self._error(handler, 400, "manual credentials require userId and tokenJWT")
            return
        try:
            session = parse_bootstrap_html(bootstrap_html) if has_html else {"userId": user_id, "tokenJWT": token}
        except (ValueError, UnicodeError, json.JSONDecodeError):
            self._error(handler, 400, "saved HTML does not contain valid Phenikaa session data")
            return
        try:
            with tempfile.TemporaryDirectory() as directory:
                summary = self.calendar_exporter(
                    session,
                    date.fromisoformat(start_value),
                    date.fromisoformat(end_value),
                    directory,
                    "calendar",
                    "Phenikaa Learning Calendar",
                )
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for extension in ("json", "xlsx", "ics"):
                        archive.write(str(summary[extension]), arcname=f"calendar.{extension}")
                body = output.getvalue()
        except Exception:
            self._error(handler, 502, "calendar export failed; check the credentials and date range")
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header("Content-Disposition", 'attachment; filename="phenikaa-calendar-export.zip"')
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _settings(self, handler: BaseHTTPRequestHandler, user: dict[str, Any], identity: dict[str, Any]) -> None:
        language = self._language(handler)
        csrf = html.escape(str(identity["csrf"]))
        vi = language == "vi"
        delete_title = "Xóa tài khoản" if language == "vi" else "Delete account"
        delete_copy = (
            "Xóa phiên Phenikaa, dữ liệu xuất và kết nối Google của bạn. Hành động này không thể hoàn tác."
            if language == "vi"
            else "Delete your Phenikaa session, exports, and Google connections. This cannot be undone."
        )
        session_settings = "".join(
            f"""<div class="managed-session"><div><strong>{html.escape(str(session["label"]))}</strong><p>{html.escape(self._status_label(str(session["status"]), language))}</p></div><form method="post" action="/sessions/{html.escape(str(session["id"]))}/delete"><input type="hidden" name="csrf" value="{csrf}"><button class="button button--danger">{'Xóa phiên' if vi else 'Delete session'}</button></form></div>"""
            for session in self.database.list_sessions(int(user["id"]))
        )
        session_management = f"<section class=\"settings-card\"><p class=\"eyebrow\">{'QUẢN LÝ PHIÊN' if vi else 'SESSION MANAGEMENT'}</p><h2>{'Các phiên Phenikaa' if vi else 'Phenikaa sessions'}</h2>{session_settings or f'<p class=\"text-muted\">{"Chưa có phiên nào được kết nối." if vi else "No sessions connected."}</p>'}</section>"
        body = f"""
        {self._navigation(user, identity, "settings", language)}
        <main><div class="section-heading"><div><p class="eyebrow">{'TÙY CHỈNH' if vi else 'PREFERENCES'}</p><h2>{'Cài đặt' if vi else 'Settings'}</h2></div><span class="section-rule"></span></div>
        {session_management}<section class="settings-card danger-zone"><p class="eyebrow">{'KHU VỰC NGUY HIỂM' if vi else 'DANGER ZONE'}</p><h2>{delete_title}</h2><p class="text-muted">{delete_copy}</p><form method="post" action="/account/delete"><input type="hidden" name="csrf" value="{csrf}"><label>{'Nhập DELETE để xác nhận' if vi else 'Type DELETE to confirm'} <input name="confirmation" autocomplete="off" required></label><button class="button button--danger">{delete_title}</button></form></section></main>"""
        self._html(handler, 200, self._layout("Settings", body), no_store=True)

    def _navigation(self, user: dict[str, Any], identity: dict[str, Any], active: str, language: str) -> str:
        csrf = html.escape(str(identity["csrf"]))
        dashboard_label = "Bảng điều khiển" if language == "vi" else "Dashboard"
        settings_label = "Cài đặt" if language == "vi" else "Settings"
        sign_out = "Đăng xuất" if language == "vi" else "Sign out"
        active_dashboard = " nav-link--active" if active == "dashboard" else ""
        active_settings = " nav-link--active" if active == "settings" else ""
        return f"""<header class="site-header"><a class="brand" href="/"><span class="brand-mark">P</span><span>PHENIKAA <b>CALENDAR</b></span></a><nav class="app-nav"><a class="nav-link{active_dashboard}" href="/">{dashboard_label}</a><a class="nav-link{active_settings}" href="/settings">{settings_label}</a></nav><div class="header-meta"><div class="language-toggle"><a class="language-option{' language-option--active' if language == 'vi' else ''}" href="/language?lang=vi&return=%2F{('settings' if active == 'settings' else '')}">VI</a><a class="language-option{' language-option--active' if language == 'en' else ''}" href="/language?lang=en&return=%2F{('settings' if active == 'settings' else '')}">EN</a></div><span>{html.escape(str(user['display_name']))}</span><form method="post" action="/auth/logout"><input type="hidden" name="csrf" value="{csrf}"><button class="text-button">{sign_out}</button></form></div></header>"""

    def _language(self, handler: BaseHTTPRequestHandler) -> str:
        return "vi" if self._cookie(handler, LANGUAGE_COOKIE) == "vi" else "en"

    def _status_label(self, status: str, language: str) -> str:
        if language == "vi":
            return {"pending_login": "Cần thao tác", "active": "Đã kết nối", "needs_human": "Cần chú ý", "disabled": "Đã tắt"}.get(status, "Không rõ")
        return STATUS_LABELS.get(status, "Unknown")

    def _friendly_timestamp(self, value: object, language: str = "en") -> str:
        if not value:
            return "Đồng bộ lần cuối: Chưa có" if language == "vi" else "Last synced: Not yet"
        try:
            timestamp = datetime.fromisoformat(str(value))
        except ValueError:
            return "Đồng bộ lần cuối: Không rõ" if language == "vi" else "Last synced: Unknown"
        formatted = timestamp.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
        return ("Đồng bộ lần cuối: " if language == "vi" else "Last synced: ") + formatted

    def _google_status_markup(self, session_id: str, csrf: str, language: str = "en") -> str:
        sid = html.escape(session_id)
        vi = language == "vi"
        if self.google is None:
            return f"<p>Google Calendar: <strong>{'Không khả dụng' if vi else 'Unavailable'}</strong></p>"
        connection = self.database.get_google_connection(session_id)
        if connection is None:
            return f"<p>Google Calendar: <strong>{'Chưa kết nối' if vi else 'Not connected'}</strong> <a href=\"/sessions/{sid}/google/connect\">{'Kết nối' if vi else 'Connect'}</a></p>"
        last_error = html.escape(str(connection.get("last_error") or ""))
        error = f"<p>{last_error}</p>" if last_error else ""
        return f"""<p>Google Calendar: <strong>{'Đã kết nối' if vi else 'Connected'}</strong></p>{error}
            <form method="post" action="/sessions/{sid}/google/disconnect"><input type="hidden" name="csrf" value="{csrf}"><button class="button button--danger">{'Ngắt kết nối Google' if vi else 'Disconnect Google'}</button></form>"""

    def _login_page(self, handler: BaseHTTPRequestHandler, session: dict[str, Any], identity: dict[str, Any]) -> None:
        sid = str(session["id"])

        def complete(captured: dict[str, Any]) -> None:
            token = str(captured["tokenJWT"])
            self.database.update_session_credentials(
                sid, str(captured["userId"]), self.vault.encrypt(token), str(token_fingerprint(token))
            )
            self.sync_engine.request_sync(sid)

        def failed(error: BaseException) -> None:
            status = STATUS_PENDING_LOGIN if isinstance(error, LoginTimeout) else STATUS_NEEDS_HUMAN
            self.database.update_session_status(sid, status, str(error)[:160])

        self.broker.start_login(sid, complete, failed)
        csrf = json.dumps(str(identity["csrf"]))
        body = f"""<header><h1>Phenikaa sign-in</h1></header><main>
        <p>Sign in on the streamed portal below. Keyboard and pointer input is relayed through this server to Phenikaa and is not stored.</p>
        <img id="frame" src="/sessions/{sid}/stream" tabindex="0" alt="Phenikaa portal">
        <p id="status">Waiting for sign-in...</p></main><script>
        const csrf={csrf}, img=document.getElementById('frame');
        function send(ev){{fetch('/sessions/{sid}/event',{{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':csrf}},body:JSON.stringify(ev)}})}}
        img.onclick=e=>{{const r=img.getBoundingClientRect();send({{type:'click',x:(e.clientX-r.left)*img.naturalWidth/r.width,y:(e.clientY-r.top)*img.naturalHeight/r.height}});img.focus()}};
        document.onkeydown=e=>{{if(['Shift','Control','Alt','Meta','CapsLock'].includes(e.key))return;e.preventDefault();send(e.key.length===1?{{type:'char',key:e.key}}:{{type:'special',key:e.key}})}};
        document.onpaste=e=>{{const text=e.clipboardData.getData('text');if(text)send({{type:'insert',text}})}};
        setInterval(async()=>{{const r=await fetch('/sessions/{sid}/status.json');const s=await r.json();document.getElementById('status').textContent=s.status;if(s.status==='active')location='/' }},1500);
        </script>"""
        self._html(handler, 200, self._layout("Phenikaa sign-in", body), no_store=True)

    def _stream(self, handler: BaseHTTPRequestHandler, session_id: str) -> None:
        attempt = self.broker.get_attempt(session_id)
        if attempt is None:
            self._error(handler, 404, "no active login")
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        sequence = -1
        try:
            while not attempt.finished.is_set():
                jpeg, sequence = attempt.latest_frame(sequence)
                if jpeg is None:
                    continue
                handler.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n")
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _status(self, handler: BaseHTTPRequestHandler, session: dict[str, Any]) -> None:
        current = self.database.get_session(str(session["id"])) or session
        self._json(handler, 200, {
            "id": current["id"], "status": current["status"],
            "last_sync_at": current.get("last_sync_at"), "last_sync_status": current.get("last_sync_status"),
            "token_fingerprint": current.get("token_fingerprint"),
        })

    def _download(self, handler: BaseHTTPRequestHandler, session_id: str, filename: str) -> None:
        path = self.config.exports_dir / session_id / filename
        if not path.is_file():
            self._error(handler, 404, "export not available")
            return
        content_type = "text/calendar; charset=utf-8" if filename.endswith(".ics") else "application/json; charset=utf-8"
        body = path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _owned_session(self, handler: BaseHTTPRequestHandler, session_id: str, user_id: int) -> dict[str, Any] | None:
        session = self.database.get_session(session_id)
        if session is None or int(session["owner_user_id"]) != user_id:
            self._error(handler, 404, "session not found")
            return None
        return session

    def _csrf_valid(self, handler: BaseHTTPRequestHandler, identity: dict[str, Any], form: dict[str, str]) -> bool:
        supplied = handler.headers.get("X-CSRF-Token") or form.get("csrf") or ""
        return secrets.compare_digest(str(identity.get("csrf", "")), supplied)

    def _validated_range(self, start_value: str, end_value: str) -> tuple[str, str]:
        try:
            start = date.fromisoformat(start_value)
            end = date.fromisoformat(end_value)
        except ValueError as error:
            raise ValueError("date range must use YYYY-MM-DD") from error
        if start > end:
            raise ValueError("start date must not be after end date")
        return start.isoformat(), end.isoformat()

    def _read_form(self, handler: BaseHTTPRequestHandler) -> dict[str, str]:
        length = min(int(handler.headers.get("Content-Length") or 0), 64 * 1024)
        if "application/json" in (handler.headers.get("Content-Type") or ""):
            return {}
        values = urllib.parse.parse_qs(handler.rfile.read(length).decode("utf-8")) if length else {}
        return {key: items[0] for key, items in values.items() if items}

    def _read_export_form(self, handler: BaseHTTPRequestHandler) -> dict[str, str]:
        content_type = handler.headers.get("Content-Type") or ""
        try:
            length = int(handler.headers.get("Content-Length") or 0)
        except ValueError as error:
            raise ValueError("invalid content length") from error
        if length > MAX_EXPORT_FORM_BYTES:
            raise OverflowError("export form is too large")
        if length <= 0:
            return {}
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete form submission")
        if content_type.startswith("multipart/form-data"):
            return self._parse_export_multipart(content_type, raw)
        if "application/x-www-form-urlencoded" not in content_type:
            raise ValueError("unsupported content type")
        values = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=False)
        return {key: items[0] for key, items in values.items() if items}

    def _parse_export_multipart(self, content_type: str, raw: bytes) -> dict[str, str]:
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw
        )
        if not message.is_multipart():
            raise ValueError("invalid multipart form")
        values: dict[str, str] = {}
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not field_name or field_name in values:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                values[field_name] = payload.decode(charset)
            except (LookupError, UnicodeDecodeError) as error:
                raise ValueError("invalid multipart field") from error
        if "bootstrap_file" in values:
            values["bootstrap_html"] = values.pop("bootstrap_file")
        return values

    def _read_json(self, handler: BaseHTTPRequestHandler) -> Any:
        length = min(int(handler.headers.get("Content-Length") or 0), 64 * 1024)
        return json.loads(handler.rfile.read(length)) if length else None

    def _cookie(self, handler: BaseHTTPRequestHandler, name: str) -> str | None:
        jar = cookies.SimpleCookie(handler.headers.get("Cookie"))
        item = jar.get(name)
        return item.value if item else None

    def _redirect(
        self,
        handler: BaseHTTPRequestHandler,
        location: str,
        *,
        set_cookie: tuple[str, str, int] | None = None,
        clear_cookie: str | bool = False,
    ) -> None:
        handler.send_response(303)
        handler.send_header("Location", location)
        if set_cookie:
            name, value, lifetime = set_cookie
            handler.send_header("Set-Cookie", f"{name}={value}; Path=/; Max-Age={lifetime}; HttpOnly; Secure; SameSite=Lax")
        if clear_cookie:
            cookie_name = APP_COOKIE if clear_cookie is True else str(clear_cookie)
            handler.send_header("Set-Cookie", f"{cookie_name}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _redirect_language(self, handler: BaseHTTPRequestHandler, location: str, language: str) -> None:
        handler.send_response(303)
        handler.send_header("Location", location)
        handler.send_header("Set-Cookie", f"{LANGUAGE_COOKIE}={language}; Path=/; Max-Age=31536000; SameSite=Lax")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _send_clear_cookie(self, handler: BaseHTTPRequestHandler, clear_cookie: str | None) -> None:
        if clear_cookie:
            handler.send_header("Set-Cookie", f"{clear_cookie}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")

    def _layout(self, title: str, body: str) -> str:
        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><link rel="stylesheet" href="/static/styles.css"></head><body>{body}</body></html>"""

    def _legacy_layout(self, title: str, body: str) -> str:
        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
        :root{{color-scheme:light;background:aliceblue;color:navy;font:16px/1.5 Arial,sans-serif}}*{{box-sizing:border-box}}body{{margin:0;background:aliceblue}}header,main,footer{{max-width:1180px;margin:auto;padding:24px}}.site-header{{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid lightsteelblue;padding-top:20px;padding-bottom:20px}}.brand{{display:flex;align-items:center;gap:10px;color:navy;text-decoration:none;font-size:12px;letter-spacing:.12em;font-weight:700}}.brand b{{font-weight:400}}.brand-mark{{display:grid;place-items:center;width:30px;height:30px;background:navy;color:white;font-family:Georgia,serif;font-size:18px}}.header-meta{{display:flex;align-items:center;gap:18px;color:slategray;font-size:13px}}.text-button{{border:0;background:transparent;color:navy;padding:0;cursor:pointer;font-size:13px}}.hero{{display:flex;justify-content:center;padding:clamp(50px,9vw,105px) 0 90px;border-bottom:1px solid lightsteelblue}}.eyebrow{{margin:0 0 14px;color:royalblue;font-size:11px;font-weight:700;letter-spacing:.16em}}h1,h2,p{{margin-top:0}}h1{{margin-bottom:24px;color:navy;font-family:Georgia,serif;font-size:clamp(44px,7vw,84px);font-weight:400;line-height:.98;letter-spacing:-.055em}}h1 em{{color:royalblue;font-style:normal}}.hero__lede{{max-width:530px;color:slategray;font-size:18px;line-height:1.6}}.hero__formats{{display:flex;align-items:center;gap:12px;margin-top:34px;color:slategray;font-size:10px;letter-spacing:.14em}}.hero__formats b{{padding:8px 10px;border:1px solid lightsteelblue;background:white;color:navy;font-family:monospace;font-size:12px;letter-spacing:0}}.hero__instrument{{width:100%;max-width:700px;padding:18px;background:navy;color:white;border:1px solid navy;box-shadow:14px 14px 0 lightsteelblue}}.instrument__top,.instrument__readout{{display:flex;justify-content:space-between;gap:12px;font-family:monospace;font-size:10px;letter-spacing:.08em}}.live-dot{{color:lightskyblue}}.instrument__grid{{display:grid;grid-template-columns:38px 1fr;gap:12px;margin:34px 0 24px}}.instrument__axis{{display:flex;flex-direction:column;justify-content:space-between;color:lightskyblue;font:10px/1 monospace}}.instrument__rows{{display:grid;grid-template-columns:repeat(5,1fr);grid-template-rows:repeat(6,26px);gap:5px;background:royalblue;padding:5px}}.instrument__rows i{{display:block;background:white;opacity:.92}}.instrument__rows i:nth-child(2),.instrument__rows i:nth-child(8),.instrument__rows i:nth-child(14){{grid-column:span 2;background:lightskyblue}}.instrument__rows i:nth-child(4),.instrument__rows i:nth-child(10){{background:cornflowerblue}}.instrument__readout{{border-top:1px solid royalblue;padding-top:14px}}.instrument__readout div{{display:grid;gap:5px}}.instrument__readout small{{color:lightskyblue;font-size:9px}}.instrument__readout strong{{font-size:11px}}.section-heading{{display:flex;align-items:end;gap:24px;padding:65px 0 8px}}h2{{color:navy;font-family:Georgia,serif;font-size:32px;font-weight:400;letter-spacing:-.03em}}.section-rule{{height:1px;flex:1;margin-bottom:12px;background:lightsteelblue}}article,section{{background:white;padding:28px;margin:18px 0;border:1px solid lightsteelblue;box-shadow:0 8px 24px rgba(0,0,128,.05)}}.setup-card{{max-width:920px}}.setup-card p:not(.eyebrow),.empty-state p:not(.eyebrow){{max-width:620px;color:slategray}}form{{display:flex;gap:14px;flex-wrap:wrap;align-items:end;margin:18px 0}}label{{display:grid;gap:6px;color:slategray;font-size:12px;font-weight:700}}input,button{{font:inherit;padding:10px 12px;border:1px solid lightsteelblue}}input{{background:white;color:navy}}.button{{display:inline-block;text-decoration:none;cursor:pointer;font-size:12px;font-weight:700;letter-spacing:.02em}}.button--primary{{background:navy;color:white;border-color:navy}}.button--secondary{{background:royalblue;color:white;border-color:royalblue}}.button--quiet{{background:white;color:navy}}.button--danger{{background:white;color:firebrick;border-color:rosybrown}}.session-card__head,.session-card__links,.session-card__footer{{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}}.session-card__head h2{{margin-bottom:0}}.status{{padding:6px 9px;background:aliceblue;color:royalblue;font:11px monospace;letter-spacing:.08em}}.status--needs_human{{color:firebrick;background:mistyrose}}.session-card__error{{min-height:1.5em;color:firebrick}}.session-card__links{{justify-content:flex-start;margin:22px 0}}.integration{{padding:15px 0;border-top:1px solid lightsteelblue;border-bottom:1px solid lightsteelblue}}.integration p{{margin:0;color:slategray;font-size:13px}}.integration a{{color:royalblue}}.range-form{{margin-bottom:8px}}.session-card__footer{{justify-content:flex-start;margin-top:10px}}.empty-state{{border-style:dashed}}.empty-state h2{{margin-bottom:8px}}a{{color:royalblue}}code{{overflow-wrap:anywhere}}footer{{font-size:.9rem;border-top:1px solid lightsteelblue;color:slategray}}footer a{{margin-right:16px}}img{{display:block;width:100%;background:black;outline:none;min-height:160px}}@media(max-width:760px){{header,main,footer{{padding-left:18px;padding-right:18px}}.site-header{{align-items:flex-start}}.header-meta{{align-items:flex-end;flex-direction:column;gap:5px}}.hero{{padding-top:55px;padding-bottom:60px}}.hero__instrument{{box-shadow:8px 8px 0 lightsteelblue}}.hero__formats{{align-items:flex-start;flex-wrap:wrap}}.hero__formats span{{width:100%}}.section-heading{{padding-top:45px}}.section-rule{{display:none}}form label,form input,form .button{{width:100%}}.session-card__links .button{{width:100%;text-align:center}}.range-form{{display:grid}}}}
         </style><style>:root{{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}body{{font-family:inherit;letter-spacing:-.01em}}h1,h2{{font-family:inherit;font-weight:700;letter-spacing:-.04em}}code,.instrument__top,.instrument__readout,.instrument__axis,.status,.eyebrow,.hero__formats,.brand{{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace}}article,section{{border-radius:16px;box-shadow:0 12px 30px rgba(0,0,128,.06)}}.site-header{{border-radius:0 0 16px 16px}}.brand-mark{{border-radius:9px}}input,button,.button{{border-radius:10px}}.button--primary,.button--secondary{{box-shadow:0 4px 10px rgba(0,0,128,.12)}}.status{{border-radius:999px}}.setup-card,.session-card,.empty-state{{padding:32px}}footer{{display:none}}</style></head><body>{body}</body></html>"""

    def _stylesheet(self, handler: BaseHTTPRequestHandler) -> None:
        path = Path(__file__).with_name("static") / "styles.css"
        if not path.is_file():
            self._error(handler, 404, "stylesheet not available")
            return
        body = path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "text/css; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _html(self, handler: BaseHTTPRequestHandler, status: int, text: str, *, no_store: bool = False) -> None:
        body = text.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if no_store:
            handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _json(self, handler: BaseHTTPRequestHandler, status: int, value: object, *, clear_cookie: str | None = None) -> None:
        body = json.dumps(value).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Cache-Control", "no-store")
        self._send_clear_cookie(handler, clear_cookie)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _empty(self, handler: BaseHTTPRequestHandler, status: int) -> None:
        handler.send_response(status)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _error(self, handler: BaseHTTPRequestHandler, status: int, message: str, *, clear_cookie: str | None = None) -> None:
        self._json(handler, status, {"error": message}, clear_cookie=clear_cookie)


def make_server(application: ServerApplication) -> ThreadingHTTPServer:
    class Server(ThreadingHTTPServer):
        daemon_threads = True

    return Server((application.config.host, application.config.port), application.handler())
