import http.client
import io
from http import cookies
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
import zipfile
from datetime import date
from importlib.util import find_spec
from pathlib import Path

if find_spec("jwt") is None or find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from cryptography.fernet import Fernet

import phenikaa_exporter as pe
from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database
from server.google import LEGACY_CLEANUP_SCOPE, SCOPE
from server.login_broker import LoginBroker
from server.oidc import SignedSessions
from server.refresh import ProfileLocks
from server.sync import SyncEngine
from server.web import ServerApplication, make_server


class FakeGoogleService:
    def __init__(self):
        self.states: list[str] = []
        self.scopes: list[str] = []
        self.exchanges: list[tuple[str, str, str]] = []
        self.disconnects: list[str] = []

    def authorization_url(self, state: str, scope: str = SCOPE) -> str:
        self.states.append(state)
        self.scopes.append(scope)
        return "https://accounts.example/auth?" + urllib.parse.urlencode({"state": state, "scope": scope})

    def exchange_code(self, session_id: str, code: str, requested_scope: str = SCOPE) -> None:
        self.exchanges.append((session_id, code, requested_scope))

    def disconnect(self, session_id: str) -> None:
        self.disconnects.append(session_id)


class RecordingSync:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def request_sync(self, session_id: str) -> None:
        self.requested.append(session_id)


class WebSmokeTests(unittest.TestCase):
    def _start_app(self, directory, *, auth_mode="disabled", google=None, locks=None, calendar_exporter=None):
        config = ServerConfig(state_dir=Path(directory), host="127.0.0.1", port=0, auth_mode=auth_mode)
        config.ensure_dirs()
        database = Database(config.db_path)
        vault = TokenVault(Fernet.generate_key())
        signed_sessions = SignedSessions(b"x" * 32)
        broker = LoginBroker(config, locks=locks or ProfileLocks())
        sync = RecordingSync()
        options = {"calendar_exporter": calendar_exporter} if calendar_exporter is not None else {}
        app = ServerApplication(config, database, vault, signed_sessions, broker, sync, None, google, **options)
        server = make_server(app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return config, database, signed_sessions, sync, server, thread

    def _stop_app(self, database, server, thread):
        server.shutdown()
        thread.join()
        server.server_close()
        database.close()

    def _request(self, server, method, path, *, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        result = response.status, dict(response.getheaders()), payload
        connection.close()
        return result

    def _cookie_value(self, header, name):
        jar = cookies.SimpleCookie(header)
        return jar[name].value

    def _app_cookie(self, signed_sessions, subject="subject", name="User", csrf="csrf-token"):
        return signed_sessions.create({"sub": subject, "name": name, "csrf": csrf})

    def test_legal_pages_are_public_in_oidc_mode_and_include_footer_links(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, _signed_sessions, _sync, server, thread = self._start_app(directory, auth_mode="oidc")
            config.policy_contact = "Ops <privacy@example.edu>"
            try:
                for path, title, phrase in (
                    ("/privacy", b"Privacy Policy", b"Google API Services User Data Policy"),
                    ("/terms", b"Terms of Service", b"https://www.googleapis.com/auth/calendar.events"),
                ):
                    status, headers, body = self._request(server, "GET", path)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
                    self.assertNotIn("Location", headers)
                    self.assertIn(title, body)
                    self.assertIn(phrase, body)
                    self.assertIn(b"Ops &lt;privacy@example.edu&gt;", body)
                    self.assertIn(b'href="/static/styles.css"', body)
                    self.assertNotIn(b'href="/privacy"', body)
                    self.assertNotIn(b'href="/terms"', body)
                status, headers, body = self._request(server, "GET", "/static/styles.css")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "text/css; charset=utf-8")
                self.assertIn(b"font-family", body)
            finally:
                self._stop_app(database, server, thread)

    def test_disabled_auth_dashboard_and_session_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ServerConfig(state_dir=Path(directory), host="127.0.0.1", port=0, auth_mode="disabled")
            config.ensure_dirs()
            database = Database(config.db_path)
            vault = TokenVault(Fernet.generate_key())
            locks = ProfileLocks()
            sync = SyncEngine(config, database, vault, locks=locks, fetcher=lambda *_args: [])
            broker = LoginBroker(config, locks=locks)
            app = ServerApplication(config, database, vault, SignedSessions(b"x" * 32), broker, sync, None)
            server = make_server(app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/dashboard")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                payload = response.read()
                self.assertIn(b"New session", payload)
                invalid = urllib.parse.urlencode({
                    "csrf": "development", "label": "Invalid", "range_start": "2027-01-01", "range_end": "2026-01-01"
                })
                connection.request(
                    "POST", "/sessions", body=invalid,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                self.assertEqual(database.list_sessions(), [])
                body = urllib.parse.urlencode({"csrf": "development", "label": "My calendar"})
                connection.request(
                    "POST", "/sessions", body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 303)
                response.read()
                sessions = database.list_sessions()
                self.assertEqual(len(sessions), 1)
                session_id = sessions[0]["id"]
                connection.request("GET", "/dashboard")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                payload = response.read()
                self.assertNotIn(b"New session", payload)
                self.assertNotIn(b"Create and sign in", payload)
                connection.request(
                    "POST", "/sessions", body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 409)
                self.assertIn(b"already has a Phenikaa session", response.read())
                self.assertEqual([row["id"] for row in database.list_sessions()], [session_id])
                connection.request(
                    "POST", f"/sessions/{session_id}/event", body=b"{broken",
                    headers={"Content-Type": "application/json", "X-CSRF-Token": "development"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                export_dir = config.exports_dir / session_id
                export_dir.mkdir(parents=True)
                (export_dir / "calendar.json").write_text("[]")
                connection.request("GET", f"/sessions/{session_id}/download/calendar.json")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                response.read()
                lock = broker.try_profile_lock(session_id)
                assert lock is not None
                delete_body = urllib.parse.urlencode({"csrf": "development"})
                try:
                    connection.request(
                        "POST", f"/sessions/{session_id}/delete", body=delete_body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 409)
                    response.read()
                finally:
                    lock.release()
                connection.close()
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
                database.close()

    def test_public_export_and_authenticated_dashboard_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, signed_sessions, _sync, server, thread = self._start_app(directory, auth_mode="oidc")
            try:
                status, headers, body = self._request(server, "GET", "/")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertIn(b'href="/auth/login"', body)
                self.assertIn(b'action="/export"', body)
                self.assertIn(b'name="bootstrap_file"', body)
                self.assertIn(b'name="userId"', body)
                self.assertIn(b'name="tokenJWT"', body)
                self.assertIn(b'class="export-shell"', body)
                self.assertIn(b'class="file-dropzone"', body)
                self.assertIn(b'Drop an HTML file here or click to choose', body)
                self.assertIn(b'<legend>HTML file</legend>', body)
                self.assertIn(b'Access token', body)
                self.assertIn(b'class="or"', body)
                status, _headers, body = self._request(
                    server, "GET", "/", headers={"Cookie": "phenikaa_ui_language=vi"}
                )
                self.assertEqual(status, 200)
                self.assertIn("Tạo lịch nhanh".encode("utf-8"), body)
                self.assertIn("TẠO LỊCH NHANH".encode("utf-8"), body)
                self.assertIn("Mã Token".encode("utf-8"), body)
                self.assertIn("Kéo thả file HTML hoặc bấm để chọn".encode("utf-8"), body)
                self.assertIn("<legend>File HTML</legend>".encode("utf-8"), body)
                self.assertIn("Mở trang lịch học trên QLDT, nhấn Ctrl + S để lưu trang".encode("utf-8"), body)
                self.assertNotIn("Tải file lịch trực tiếp".encode("utf-8"), body)
                status, headers, _body = self._request(server, "GET", "/dashboard")
                self.assertEqual(status, 303)
                self.assertEqual(headers["Location"], "/auth/login")
                status, _headers, body = self._request(server, "GET", "/about")
                self.assertEqual(status, 200)
                self.assertIn(b"Quick export", body)
                app_cookie = self._app_cookie(signed_sessions)
                status, _headers, body = self._request(
                    server, "GET", "/dashboard", headers={"Cookie": f"phenikaa_server_session={app_cookie}"}
                )
                self.assertEqual(status, 200)
                self.assertIn(b"Calendar sessions", body)
                self.assertNotIn(b'name="bootstrap_file"', body)
            finally:
                self._stop_app(database, server, thread)

    def test_export_requires_authentication_and_csrf(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, signed_sessions, sync, server, thread = self._start_app(directory, auth_mode="oidc")
            body = urllib.parse.urlencode({"range_start": "2026-08-01", "range_end": "2026-10-31"})
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            try:
                status, _headers, _payload = self._request(server, "POST", "/export", body=body, headers=headers)
                self.assertEqual(status, 403)
                headers["Cookie"] = f"phenikaa_server_session={self._app_cookie(signed_sessions)}"
                status, _headers, _payload = self._request(server, "POST", "/export", body=body, headers=headers)
                self.assertEqual(status, 403)
                self.assertEqual(sync.requested, [])
                self.assertEqual(database.list_sessions(), [])
            finally:
                self._stop_app(database, server, thread)

    def test_public_export_accepts_signed_public_csrf(self):
        captured = []

        def calendar_exporter(session, start, end, output_dir, prefix, calendar_name):
            captured.append(session)
            root = Path(output_dir)
            paths = {}
            for extension in ("json", "xlsx", "ics"):
                path = root / f"{prefix}.{extension}"
                path.write_bytes(b"file")
                paths[extension] = str(path)
            return paths

        with tempfile.TemporaryDirectory() as directory:
            _config, database, signed_sessions, sync, server, thread = self._start_app(
                directory, auth_mode="oidc", calendar_exporter=calendar_exporter
            )
            try:
                csrf = signed_sessions.create({"purpose": "public_export"}, lifetime=600)
                form = {
                    "csrf": csrf, "range_start": "2026-08-01", "range_end": "2026-10-31",
                    "userId": "student-id", "tokenJWT": "secret-token",
                }
                status, _headers, _body = self._request(
                    server, "POST", "/export", body=urllib.parse.urlencode(form),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(captured, [{"userId": "student-id", "tokenJWT": "secret-token"}])
                self.assertEqual(sync.requested, [])
                self.assertEqual(database.list_sessions(), [])
            finally:
                self._stop_app(database, server, thread)

    def test_public_export_file_accepts_public_csrf_when_authenticated(self):
        captured = []

        def calendar_exporter(session, start, end, output_dir, prefix, calendar_name):
            captured.append(session)
            root = Path(output_dir)
            paths = {}
            for extension in ("json", "xlsx", "ics"):
                path = root / f"{prefix}.{extension}"
                path.write_bytes(b"file")
                paths[extension] = str(path)
            return paths

        with tempfile.TemporaryDirectory() as directory:
            _config, database, signed_sessions, sync, server, thread = self._start_app(
                directory, auth_mode="oidc", calendar_exporter=calendar_exporter
            )
            try:
                csrf = signed_sessions.create({"purpose": "public_export"}, lifetime=600)
                blob = pe.xor_b64_encode(
                    json.dumps({"userId": "student-id", "tokenJWT": "secret-token"}), pe.BOOTSTRAP_KEY
                )
                boundary = "----TestBoundary"
                fields = [
                    ("csrf", csrf, None),
                    ("range_start", "2026-08-01", None),
                    ("range_end", "2026-10-31", None),
                    ("bootstrap_file", f'<script>AXYZCLRVN = () => "{blob}"</script>', "index.html"),
                ]
                parts = []
                for name, value, filename in fields:
                    disposition = f'form-data; name="{name}"'
                    if filename:
                        disposition += f'; filename="{filename}"'
                    parts.append(
                        f"--{boundary}\r\nContent-Disposition: {disposition}\r\n\r\n{value}\r\n".encode()
                    )
                body = b"".join(parts) + f"--{boundary}--\r\n".encode()
                headers = {
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                    "Cookie": f"phenikaa_server_session={self._app_cookie(signed_sessions)}",
                }
                status, _response_headers, _body = self._request(
                    server, "POST", "/export", body=body, headers=headers
                )
                self.assertEqual(status, 200)
                self.assertEqual(captured, [{"userId": "student-id", "tokenJWT": "secret-token"}])
                self.assertEqual(sync.requested, [])
            finally:
                self._stop_app(database, server, thread)

    def test_export_supports_manual_credentials_without_sync(self):
        captured = []

        def calendar_exporter(session, start, end, output_dir, prefix, calendar_name):
            captured.append((session, start, end, calendar_name))
            root = Path(output_dir)
            paths = {}
            for extension, content in (("json", b"[]"), ("xlsx", b"xlsx"), ("ics", b"BEGIN:VCALENDAR")):
                path = root / f"{prefix}.{extension}"
                path.write_bytes(content)
                paths[extension] = str(path)
            return paths

        with tempfile.TemporaryDirectory() as directory:
            _config, database, signed_sessions, sync, server, thread = self._start_app(
                directory, auth_mode="oidc", calendar_exporter=calendar_exporter
            )
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": f"phenikaa_server_session={self._app_cookie(signed_sessions)}",
            }
            form = {"csrf": "csrf-token", "range_start": "2026-08-01", "range_end": "2026-10-31", "userId": "student-id", "tokenJWT": "secret-token"}
            try:
                status, response_headers, body = self._request(
                    server, "POST", "/export", body=urllib.parse.urlencode(form), headers=headers
                )
                self.assertEqual(status, 200)
                self.assertEqual(response_headers["Content-Type"], "application/zip")
                self.assertEqual(response_headers["Cache-Control"], "no-store")
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    self.assertEqual(sorted(archive.namelist()), ["calendar.ics", "calendar.json", "calendar.xlsx"])
                self.assertEqual(captured[0][0], {"userId": "student-id", "tokenJWT": "secret-token"})
                self.assertEqual(sync.requested, [])
                self.assertEqual(database.list_sessions(), [])
            finally:
                self._stop_app(database, server, thread)

    def test_settings_language_toggle_and_account_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                status, _headers, body = self._request(server, "GET", "/settings")
                self.assertEqual(status, 200)
                self.assertIn(b"Dashboard", body)
                self.assertIn(b"Delete account", body)
                status, headers, _body = self._request(server, "GET", "/language?lang=vi&return=%2Fsettings")
                self.assertEqual(status, 303)
                self.assertIn("phenikaa_ui_language=vi", headers["Set-Cookie"])
                status, _headers, body = self._request(
                    server,
                    "GET",
                    "/settings",
                    headers={"Cookie": "phenikaa_ui_language=vi"},
                )
                self.assertEqual(status, 200)
                self.assertIn("Cài đặt".encode("utf-8"), body)
                delete_body = urllib.parse.urlencode({"csrf": "development", "confirmation": "DELETE"})
                status, headers, _body = self._request(
                    server,
                    "POST",
                    "/account/delete",
                    body=delete_body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(status, 303)
                self.assertEqual(headers["Location"], "/")
                self.assertIsNone(database.get_user(user["id"]))
                self.assertEqual(database.list_sessions(), [])
                self.assertFalse((database.path if hasattr(database, "path") else Path(directory) / "profiles" / session_id).exists())
            finally:
                self._stop_app(database, server, thread)

    def test_google_connect_redirect_sets_signed_transaction_for_owned_session(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, signed_sessions, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                status, headers, _body = self._request(server, "GET", f"/sessions/{session_id}/google/connect")
                self.assertEqual(status, 303)
                self.assertTrue(headers["Location"].startswith("https://accounts.example/auth?"))
                self.assertIn("phenikaa_google_oauth_transaction=", headers["Set-Cookie"])
                self.assertIn("HttpOnly; Secure; SameSite=Lax", headers["Set-Cookie"])
                transaction = signed_sessions.verify(self._cookie_value(headers["Set-Cookie"], "phenikaa_google_oauth_transaction"))
                assert transaction is not None
                self.assertEqual(transaction["session_id"], session_id)
                self.assertEqual(transaction["state"], google.states[0])
                self.assertEqual(transaction["requested_scope"], SCOPE)
                self.assertEqual(google.scopes, [SCOPE])
            finally:
                self._stop_app(database, server, thread)


    def test_google_connect_requests_temporary_events_scope_only_for_pending_primary_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, signed_sessions, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                database.set_google_migration_state(session_id, "primary_cleanup_pending")
                status, headers, _body = self._request(server, "GET", f"/sessions/{session_id}/google/connect")
                self.assertEqual(status, 303)
                transaction = signed_sessions.verify(self._cookie_value(headers["Set-Cookie"], "phenikaa_google_oauth_transaction"))
                assert transaction is not None
                self.assertEqual(transaction["requested_scope"], LEGACY_CLEANUP_SCOPE)
                self.assertEqual(google.scopes, [LEGACY_CLEANUP_SCOPE])
            finally:
                self._stop_app(database, server, thread)

    def test_google_callback_success_exchanges_code_requests_sync_and_clears_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, signed_sessions, sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                transaction = signed_sessions.create({"state": "state-ok", "session_id": session_id, "requested_scope": SCOPE}, lifetime=600)
                status, headers, _body = self._request(
                    server,
                    "GET",
                    "/auth/google/callback?state=state-ok&code=code-ok",
                    headers={"Cookie": f"phenikaa_google_oauth_transaction={transaction}"},
                )
                self.assertEqual(status, 303)
                self.assertEqual(headers["Location"], "/dashboard")
                self.assertIn("phenikaa_google_oauth_transaction=;", headers["Set-Cookie"])
                self.assertEqual(google.exchanges, [(session_id, "code-ok", SCOPE)])
                self.assertEqual(sync.requested, [session_id])
            finally:
                self._stop_app(database, server, thread)

    def test_google_callback_waits_for_profile_lock_before_exchanging_code(self):
        with tempfile.TemporaryDirectory() as directory:
            locks = ProfileLocks()
            google = FakeGoogleService()
            _config, database, signed_sessions, sync, server, thread = self._start_app(
                directory, google=google, locks=locks
            )
            profile_lock = None
            lock_held = False
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                transaction = signed_sessions.create({"state": "state-ok", "session_id": session_id, "requested_scope": LEGACY_CLEANUP_SCOPE}, lifetime=600)
                profile_lock = locks.for_profile(session_id)
                profile_lock.acquire()
                lock_held = True
                result = []

                def request_callback():
                    result.append(self._request(
                        server,
                        "GET",
                        "/auth/google/callback?state=state-ok&code=code-ok",
                        headers={"Cookie": f"phenikaa_google_oauth_transaction={transaction}"},
                    ))

                request_thread = threading.Thread(target=request_callback)
                request_thread.start()
                time.sleep(0.1)
                self.assertEqual(result, [])
                self.assertEqual(google.exchanges, [])
                self.assertEqual(sync.requested, [])
                profile_lock.release()
                lock_held = False
                request_thread.join(2)
                self.assertFalse(request_thread.is_alive())
                self.assertEqual(result[0][0], 303)
                self.assertEqual(google.exchanges, [(session_id, "code-ok", LEGACY_CLEANUP_SCOPE)])
                self.assertEqual(sync.requested, [session_id])
            finally:
                if lock_held and profile_lock is not None:
                    profile_lock.release()
                self._stop_app(database, server, thread)

    def test_google_callback_rejects_bad_state_and_google_error_clears_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, signed_sessions, sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                transaction = signed_sessions.create({"state": "state-ok", "session_id": session_id}, lifetime=600)
                status, headers, _body = self._request(
                    server,
                    "GET",
                    "/auth/google/callback?state=wrong&code=code-ok",
                    headers={"Cookie": f"phenikaa_google_oauth_transaction={transaction}"},
                )
                self.assertEqual(status, 400)
                self.assertIn("phenikaa_google_oauth_transaction=;", headers["Set-Cookie"])
                status, headers, body = self._request(
                    server,
                    "GET",
                    "/auth/google/callback?error=access_denied",
                    headers={"Cookie": f"phenikaa_google_oauth_transaction={transaction}"},
                )
                self.assertEqual(status, 400)
                self.assertIn(b"access_denied", body)
                self.assertIn("phenikaa_google_oauth_transaction=;", headers["Set-Cookie"])
                self.assertEqual(google.exchanges, [])
                self.assertEqual(sync.requested, [])
            finally:
                self._stop_app(database, server, thread)

    def test_google_callback_rechecks_current_owner_from_signed_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, signed_sessions, sync, server, thread = self._start_app(directory, auth_mode="oidc", google=google)
            try:
                owner = database.get_or_create_user("owner", "Owner")
                database.get_or_create_user("intruder", "Intruder")
                session_id = database.create_session(owner["id"])
                transaction = signed_sessions.create({"state": "state-ok", "session_id": session_id}, lifetime=600)
                app_cookie = self._app_cookie(signed_sessions, subject="intruder")
                status, headers, body = self._request(
                    server,
                    "GET",
                    "/auth/google/callback?state=state-ok&code=code-ok",
                    headers={"Cookie": f"phenikaa_server_session={app_cookie}; phenikaa_google_oauth_transaction={transaction}"},
                )
                self.assertEqual(status, 404)
                self.assertIn(b"session not found", body)
                self.assertIn("phenikaa_google_oauth_transaction=;", headers["Set-Cookie"])
                self.assertEqual(google.exchanges, [])
                self.assertEqual(sync.requested, [])
            finally:
                self._stop_app(database, server, thread)

    def test_google_disconnect_requires_csrf_and_owned_session(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, signed_sessions, _sync, server, thread = self._start_app(directory, auth_mode="oidc", google=google)
            try:
                user = database.get_or_create_user("subject", "User")
                other = database.get_or_create_user("other", "Other")
                session_id = database.create_session(user["id"])
                other_session = database.create_session(other["id"])
                app_cookie = self._app_cookie(signed_sessions)
                body = urllib.parse.urlencode({"csrf": "wrong"})
                status, _headers, _payload = self._request(
                    server,
                    "POST",
                    f"/sessions/{session_id}/google/disconnect",
                    body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"phenikaa_server_session={app_cookie}"},
                )
                self.assertEqual(status, 403)
                body = urllib.parse.urlencode({"csrf": "csrf-token"})
                status, _headers, _payload = self._request(
                    server,
                    "POST",
                    f"/sessions/{other_session}/google/disconnect",
                    body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"phenikaa_server_session={app_cookie}"},
                )
                self.assertEqual(status, 404)
                status, headers, _payload = self._request(
                    server,
                    "POST",
                    f"/sessions/{session_id}/google/disconnect",
                    body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"phenikaa_server_session={app_cookie}"},
                )
                self.assertEqual(status, 303)
                self.assertEqual(headers["Location"], "/")
                self.assertEqual(google.disconnects, [session_id])
            finally:
                self._stop_app(database, server, thread)

    def test_google_disconnect_returns_conflict_while_profile_lock_is_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            locks = ProfileLocks()
            google = FakeGoogleService()
            _config, database, signed_sessions, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc", google=google, locks=locks
            )
            profile_lock = None
            lock_held = False
            try:
                user = database.get_or_create_user("subject", "User")
                session_id = database.create_session(user["id"])
                app_cookie = self._app_cookie(signed_sessions)
                body = urllib.parse.urlencode({"csrf": "csrf-token"})
                profile_lock = locks.for_profile(session_id)
                profile_lock.acquire()
                lock_held = True
                status, _headers, payload = self._request(
                    server,
                    "POST",
                    f"/sessions/{session_id}/google/disconnect",
                    body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"phenikaa_server_session={app_cookie}"},
                )
                self.assertEqual(status, 409)
                self.assertIn(b"session is busy", payload)
                self.assertEqual(google.disconnects, [])
            finally:
                if lock_held and profile_lock is not None:
                    profile_lock.release()
                self._stop_app(database, server, thread)

    def test_google_dashboard_states_absent_connected_error_and_no_token_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                database.create_session(user["id"], label="No Google")
                status, _headers, body = self._request(server, "GET", "/dashboard")
                self.assertEqual(status, 200)
                self.assertIn(b"Google Calendar: <strong>Unavailable</strong>", body)
            finally:
                self._stop_app(database, server, thread)

        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                connected = database.create_session(user["id"], label="Connected")
                database.upsert_google_connection(
                    connected,
                    access_token_encrypted="access-token-secret",
                    refresh_token_encrypted="refresh-token-secret",
                    expires_at="2026-08-30T12:00:00+00:00",
                )
                database.set_google_connection_error(connected, "bad <token>")
                status, _headers, body = self._request(server, "GET", "/dashboard")
                self.assertEqual(status, 200)
                self.assertIn(b"Google Calendar: <strong>Connected</strong>", body)
                self.assertIn(b"bad &lt;token&gt;", body)
                self.assertNotIn(b"access-token-secret", body)
                self.assertNotIn(b"refresh-token-secret", body)
            finally:
                self._stop_app(database, server, thread)

        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                unconnected = database.create_session(user["id"], label="Unconnected")
                status, _headers, body = self._request(server, "GET", "/dashboard")
                self.assertEqual(status, 200)
                self.assertIn(f"/sessions/{unconnected}/google/connect".encode("utf-8"), body)
            finally:
                self._stop_app(database, server, thread)

    def test_google_absent_config_routes_return_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, signed_sessions, _sync, server, thread = self._start_app(directory)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                status, _headers, _body = self._request(server, "GET", f"/sessions/{session_id}/google/connect")
                self.assertEqual(status, 503)
                transaction = signed_sessions.create({"state": "state-ok", "session_id": session_id}, lifetime=600)
                status, headers, _body = self._request(
                    server,
                    "GET",
                    "/auth/google/callback?state=state-ok&code=code-ok",
                    headers={"Cookie": f"phenikaa_google_oauth_transaction={transaction}"},
                )
                self.assertEqual(status, 503)
                self.assertIn("phenikaa_google_oauth_transaction=;", headers["Set-Cookie"])
                body = urllib.parse.urlencode({"csrf": "development"})
                status, _headers, _payload = self._request(
                    server,
                    "POST",
                    f"/sessions/{session_id}/google/disconnect",
                    body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(status, 503)
            finally:
                self._stop_app(database, server, thread)


if __name__ == "__main__":
    unittest.main()
