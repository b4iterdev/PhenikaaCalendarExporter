from __future__ import annotations

import html
import json
import secrets
import shutil
import urllib.parse
from datetime import date
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

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
    ) -> None:
        self.config = config
        self.database = database
        self.vault = vault
        self.signed_sessions = signed_sessions
        self.broker = broker
        self.sync_engine = sync_engine
        self.oidc = oidc
        self.google = google

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
            self._redirect(handler, "/auth/login")
            return
        user = self.database.get_or_create_user(str(identity["sub"]), str(identity.get("name") or identity["sub"]))
        if path == "/":
            self._dashboard(handler, user, identity)
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
        identity = self._identity(handler)
        if identity is None:
            self._error(handler, 401, "authentication required")
            return
        form = self._read_form(handler)
        if not self._csrf_valid(handler, identity, form):
            self._error(handler, 403, "invalid CSRF token")
            return
        user = self.database.get_or_create_user(str(identity["sub"]), str(identity.get("name") or identity["sub"]))
        path = urllib.parse.urlsplit(handler.path).path
        if path == "/auth/logout":
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
        rows = []
        for session in self.database.list_sessions(int(user["id"])):
            sid = html.escape(str(session["id"]))
            label = html.escape(str(session["label"]))
            status = html.escape(str(session["status"]))
            error = html.escape(str(session.get("last_sync_error") or ""))
            google = self._google_status_markup(str(session["id"]), csrf)
            rows.append(f"""
            <article><h2>{label}</h2><p>Status: <strong>{status}</strong></p>
            <p>{error}</p><p><a href="/sessions/{sid}/login">Open sign-in</a> ·
            <a href="/sessions/{sid}/download/calendar.ics">ICS</a> ·
            <a href="/sessions/{sid}/download/calendar.json">JSON</a></p>
            {google}
            <form method="post" action="/sessions/{sid}/settings"><input type="hidden" name="csrf" value="{csrf}">
            <label>From <input type="date" name="range_start" value="{html.escape(str(session.get('range_start') or ''))}"></label>
            <label>To <input type="date" name="range_end" value="{html.escape(str(session.get('range_end') or ''))}"></label>
            <button>Save range</button></form>
            <form method="post" action="/sessions/{sid}/sync"><input type="hidden" name="csrf" value="{csrf}"><button>Sync now</button></form>
            <form method="post" action="/sessions/{sid}/delete"><input type="hidden" name="csrf" value="{csrf}"><button class="danger">Delete</button></form></article>""")
        start, end = academic_year_range()
        new_session_form = "" if rows else f"""
        <section><h2>New session</h2><form method="post" action="/sessions">
        <input type="hidden" name="csrf" value="{csrf}"><label>Name <input name="label" value="Phenikaa account"></label>
        <label>From <input type="date" name="range_start" value="{start.isoformat()}"></label>
        <label>To <input type="date" name="range_end" value="{end.isoformat()}"></label><button>Create and sign in</button></form></section>
        """
        body = f"""
        <header><h1>Phenikaa Calendar Server</h1><p>{html.escape(str(user['display_name']))}</p></header>
        <main>{new_session_form}
        {''.join(rows) or '<p>No sessions yet.</p>'}</main>"""
        self._html(handler, 200, self._layout("Calendar sessions", body), no_store=True)

    def _google_status_markup(self, session_id: str, csrf: str) -> str:
        sid = html.escape(session_id)
        if self.google is None:
            return "<p>Google Calendar: <strong>Unavailable</strong></p>"
        connection = self.database.get_google_connection(session_id)
        if connection is None:
            return f"<p>Google Calendar: <strong>Not connected</strong> <a href=\"/sessions/{sid}/google/connect\">Connect</a></p>"
        last_error = html.escape(str(connection.get("last_error") or ""))
        error = f"<p>{last_error}</p>" if last_error else ""
        return f"""<p>Google Calendar: <strong>Connected</strong></p>{error}
            <form method="post" action="/sessions/{sid}/google/disconnect"><input type="hidden" name="csrf" value="{csrf}"><button class="danger">Disconnect Google</button></form>"""

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

    def _send_clear_cookie(self, handler: BaseHTTPRequestHandler, clear_cookie: str | None) -> None:
        if clear_cookie:
            handler.send_header("Set-Cookie", f"{clear_cookie}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")

    def _layout(self, title: str, body: str) -> str:
        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
        :root{{color-scheme:light;background:#f4f0e8;color:#17202a;font:16px/1.5 Georgia,serif}}body{{margin:0}}header,main,footer{{max-width:1100px;margin:auto;padding:24px}}header{{border-bottom:3px solid #9c2f24}}article,section{{background:#fff;padding:20px;margin:18px 0;border:1px solid #d4cbbd;box-shadow:4px 4px 0 #d9cdbb}}form{{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:12px 0}}label{{display:grid;gap:4px}}input,button{{font:inherit;padding:8px;border:1px solid #776d61}}button{{background:#17365d;color:white;cursor:pointer}}button.danger{{background:#9c2f24}}a{{color:#17365d}}article p a{{display:inline-block;padding:6px 2px;margin-right:6px}}code{{overflow-wrap:anywhere}}footer{{font-size:.95rem;border-top:1px solid #d4cbbd}}footer a{{margin-right:12px}}img{{display:block;width:100%;background:#111;outline:none;min-height:160px}}</style></head><body>{body}<footer><a href="/privacy">Privacy Policy</a><a href="/terms">Terms of Service</a></footer></body></html>"""

    def _html(self, handler: BaseHTTPRequestHandler, status: int, text: str, *, no_store: bool = False) -> None:
        body = text.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
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
