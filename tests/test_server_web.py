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
from unittest.mock import patch

if find_spec("jwt") is None or find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from cryptography.fernet import Fernet

import phenikaa_exporter as pe
from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database, STATUS_ACTIVE, STATUS_PENDING_LOGIN
from server.google import LEGACY_CLEANUP_SCOPE, SCOPE, GoogleCalendarError
from server.login_broker import LoginBroker
from server.oidc import SignedSessions
from server.refresh import ProfileLocks
from server.sync import SyncEngine
from server.web import ServerApplication, make_server


class FakeGoogleService:
    def __init__(self, calendar_result="deleted"):
        self.states: list[str] = []
        self.scopes: list[str] = []
        self.exchanges: list[tuple[str, str, str]] = []
        self.disconnects: list[str] = []
        self.deleted_calendars: list[tuple[str, str]] = []
        self.hidden_calendars: list[tuple[str, str]] = []
        self.calendar_result = calendar_result

    def authorization_url(self, state: str, scope: str = SCOPE) -> str:
        self.states.append(state)
        self.scopes.append(scope)
        return "https://accounts.example/auth?" + urllib.parse.urlencode({"state": state, "scope": scope})

    def exchange_code(self, session_id: str, code: str, requested_scope: str = SCOPE) -> None:
        self.exchanges.append((session_id, code, requested_scope))

    def disconnect(self, session_id: str) -> None:
        self.disconnects.append(session_id)

    def delete_app_calendar(self, session_id: str, calendar_id: str) -> str:
        if self.calendar_result == "raise":
            raise GoogleCalendarError("Google exploded")
        self.deleted_calendars.append((session_id, calendar_id))
        return "already_gone" if self.calendar_result == "already_gone" else "deleted"

    def remove_from_list(self, session_id: str, calendar_id: str) -> str:
        if self.calendar_result == "raise":
            raise GoogleCalendarError("Google exploded")
        self.hidden_calendars.append((session_id, calendar_id))
        return "already_gone" if self.calendar_result == "already_gone" else "removed"


class RecordingSync:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def request_sync(self, session_id: str, *, run_id: int | None = None) -> None:
        self.requested.append(session_id)


class WebSmokeTests(unittest.TestCase):
    def _start_app(self, directory, *, auth_mode="disabled", google=None, locks=None, calendar_exporter=None, profile_lock_timeout=10.0):
        config = ServerConfig(state_dir=Path(directory), host="127.0.0.1", port=0, auth_mode=auth_mode)
        config.ensure_dirs()
        database = Database(config.db_path)
        vault = TokenVault(Fernet.generate_key())
        signed_sessions = SignedSessions(b"x" * 32)
        broker = LoginBroker(config, locks=locks or ProfileLocks())
        sync = RecordingSync()
        options = {"calendar_exporter": calendar_exporter} if calendar_exporter is not None else {}
        app = ServerApplication(config, database, vault, signed_sessions, broker, sync, None, google, profile_lock_timeout=profile_lock_timeout, **options)
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

    def test_api_v1_openapi_document_is_public(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc"
            )
            try:
                status, headers, body = self._request(
                    server, "GET", "/api/v1/openapi.json"
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    headers["Content-Type"],
                    "application/json; charset=utf-8",
                )
                self.assertEqual(headers["Cache-Control"], "no-store")

                spec = json.loads(body.decode("utf-8"))
                self.assertEqual(spec["openapi"], "3.1.0")
                self.assertIn("/api/v1/health", spec["paths"])
                self.assertIn("/api/v1/export/one-shot", spec["paths"])
                self.assertIn("/api/v1/tokens", spec["paths"])
                self.assertIn("/api/v1/sessions", spec["paths"])
                self.assertIn(
                    "BearerAuth",
                    spec["components"]["securitySchemes"],
                )
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_health(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            try:
                status, headers, body = self._request(
                    server, "GET", "/api/v1/health"
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    headers["Content-Type"],
                    "application/json; charset=utf-8",
                )
                self.assertEqual(headers["Cache-Control"], "no-store")
                data = json.loads(body.decode("utf-8"))
                self.assertEqual(
                    data,
                    {"ok": True, "data": {"status": "healthy"}},
                )
            finally:
                self._stop_app(database, server, thread)

    def test_server_status_page_and_json_api(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            try:
                status, headers, body = self._request(server, "GET", "/status")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
                self.assertIn(b"Phenikaa", body)
                self.assertIn(b"Google", body)
                self.assertIn(b"/status?refresh=1", body)
                self.assertNotIn(b"Server Egress IP", body)
                self.assertNotIn(b"IP Egress", body)

                status_api, headers_api, body_api = self._request(server, "GET", "/api/status")
                self.assertEqual(status_api, 200)
                self.assertEqual(headers_api["Content-Type"], "application/json")
                data = json.loads(body_api.decode("utf-8"))
                self.assertIn("overall_status", data)
                self.assertIn("services", data)
                self.assertIn("phenikaa", data["services"])
                self.assertIn("google", data["services"])
                self.assertNotIn("public_ip", data)

                status_v1, headers_v1, body_v1 = self._request(
                    server, "GET", "/api/v1/status"
                )
                self.assertEqual(status_v1, 200)
                self.assertEqual(
                    headers_v1["Content-Type"],
                    "application/json; charset=utf-8",
                )
                self.assertEqual(headers_v1["Cache-Control"], "no-store")
                data_v1 = json.loads(body_v1.decode("utf-8"))
                self.assertTrue(data_v1["ok"])
                self.assertIn("overall_status", data_v1["data"])
                self.assertIn("services", data_v1["data"])
                self.assertIn("system", data_v1["data"])
                self.assertNotIn("public_ip", data_v1["data"])

                status_home, _headers_home, body_home = self._request(server, "GET", "/")
                self.assertEqual(status_home, 200)
                self.assertIn(b'href="/status"', body_home)
            finally:
                self._stop_app(database, server, thread)

    def test_login_page_has_plain_stream_frame_without_corner_decoration(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            user = database.get_or_create_user("local-development-user", "Local user")
            session_id = database.create_session(int(user["id"]))
            try:
                with patch.object(LoginBroker, "start_login", return_value=None) as start_login:
                    status, _headers, body = self._request(server, "GET", f"/sessions/{session_id}/login")
                self.assertEqual(status, 200)
                self.assertIn(b'class="signin-frame"', body)
                self.assertIn(b'id="frame"', body)
                self.assertNotIn(b"signin-frame__corner", body)
                start_login.assert_called_once()

                status, _headers, stylesheet = self._request(server, "GET", "/static/styles.css")
                self.assertEqual(status, 200)
                self.assertNotIn(b"signin-frame__corner", stylesheet)
            finally:
                self._stop_app(database, server, thread)

    def test_login_page_resets_active_status_to_pending_login(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            user = database.get_or_create_user("local-development-user", "Local user")
            session_id = database.create_session(int(user["id"]))
            try:
                # Mark session as active
                database.update_session_status(session_id, STATUS_ACTIVE)
                # Verify it's active
                self.assertEqual(database.get_session(session_id)["status"], STATUS_ACTIVE)
                
                with patch.object(LoginBroker, "start_login", return_value=None) as start_login:
                    status, _headers, body = self._request(server, "GET", f"/sessions/{session_id}/login")
                self.assertEqual(status, 200)
                start_login.assert_called_once()
                
                # Verify session status was reset to pending_login
                self.assertEqual(database.get_session(session_id)["status"], STATUS_PENDING_LOGIN)
            finally:
                self._stop_app(database, server, thread)

    def test_login_page_has_stream_guide_dialog_and_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            user = database.get_or_create_user("local-development-user", "Local user")
            session_id = database.create_session(int(user["id"]))
            try:
                with patch.object(LoginBroker, "start_login", return_value=None):
                    status, _headers, body = self._request(server, "GET", f"/sessions/{session_id}/login")
                self.assertEqual(status, 200)
                self.assertIn(b'id="guide-trigger"', body)
                self.assertNotIn(b'id="guide-trigger-hint"', body)
                self.assertIn(b'class="signin-guide-btn"', body)
                self.assertIn(b'id="guide-modal"', body)
                self.assertIn(b"Enter", body)
                self.assertIn(b"Unikey", body)
            finally:
                self._stop_app(database, server, thread)

    def test_login_page_has_mobile_stream_input_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            user = database.get_or_create_user("local-development-user", "Local user")
            session_id = database.create_session(int(user["id"]))
            try:
                with patch.object(LoginBroker, "start_login", return_value=None):
                    status, _headers, body = self._request(server, "GET", f"/sessions/{session_id}/login")
                self.assertEqual(status, 200)
                self.assertIn(b'id="mobile-input"', body)
                self.assertIn(b'id="mobile-send"', body)
                self.assertIn(b'id="mobile-tab"', body)
                self.assertIn(b'id="mobile-enter"', body)
                self.assertIn(b'class="signin-mobile-bar"', body)
                self.assertIn(b"touchend", body)
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
            app = ServerApplication(config, database, vault, SignedSessions(b"x" * 32), broker, sync, None, profile_lock_timeout=0)
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
                for path in ("/", "/about"):
                    for cookie in ("", "invalid", app_cookie):
                        with self.subTest(path=path, authenticated=cookie == app_cookie):
                            status, _headers, body = self._request(
                                server, "GET", path, headers={"Cookie": f"phenikaa_server_session={cookie}"}
                            )
                            self.assertEqual(status, 200)
                            if cookie == app_cookie:
                                self.assertNotIn(b'href="/auth/login"', body)
                                self.assertIn(b'href="/settings"', body)
                                self.assertIn(b'action="/auth/logout"', body)
                                self.assertIn(b'value="csrf-token"', body)
                            else:
                                self.assertIn(b'href="/auth/login"', body)
                                self.assertNotIn(b'action="/auth/logout"', body)
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

    def test_api_v1_one_shot_json_export_is_ephemeral(self):
        captured = []

        def calendar_exporter(session, start, end, output_dir, prefix, calendar_name):
            captured.append((session, start, end, calendar_name))
            root = Path(output_dir)
            paths = {}
            for extension, content in (
                ("json", b"[]"),
                ("xlsx", b"xlsx"),
                ("ics", b"BEGIN:VCALENDAR"),
            ):
                output_path = root / f"{prefix}.{extension}"
                output_path.write_bytes(content)
                paths[extension] = str(output_path)
            return paths

        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, sync, server, thread = self._start_app(
                directory, auth_mode="oidc", calendar_exporter=calendar_exporter
            )
            request_body = json.dumps({
                "userId": "student-id",
                "tokenJWT": "test-token",
                "start": "2026-08-01",
                "end": "2026-10-31",
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            try:
                status, response_headers, response_body = self._request(
                    server,
                    "POST",
                    "/api/v1/export/one-shot?format=json",
                    body=request_body,
                    headers=headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    response_headers["Content-Type"],
                    "application/json; charset=utf-8",
                )
                self.assertEqual(response_headers["Cache-Control"], "no-store")

                result = json.loads(response_body.decode("utf-8"))
                self.assertTrue(result["ok"])
                self.assertEqual(result["data"]["events"], [])
                self.assertEqual(
                    captured[0][0],
                    {"userId": "student-id", "tokenJWT": "test-token"},
                )
                self.assertEqual(captured[0][1].isoformat(), "2026-08-01")
                self.assertEqual(captured[0][2].isoformat(), "2026-10-31")
                self.assertEqual(sync.requested, [])
                self.assertEqual(database.list_sessions(), [])
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_one_shot_rejects_body_over_one_mib(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc"
            )
            try:
                status, headers, body = self._request(
                    server,
                    "POST",
                    "/api/v1/export/one-shot",
                    body=b"",
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(1024 * 1024 + 1),
                    },
                )
                self.assertEqual(status, 413)
                self.assertEqual(headers["Cache-Control"], "no-store")
                result = json.loads(body.decode("utf-8"))
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["error"]["code"],
                    "request_too_large",
                )
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_one_shot_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc"
            )
            body = json.dumps({
                "start": "2026-08-01",
                "end": "2026-10-31",
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            try:
                for _ in range(10):
                    status, _headers, _response = self._request(
                        server,
                        "POST",
                        "/api/v1/export/one-shot",
                        body=body,
                        headers=headers,
                    )
                    self.assertEqual(status, 400)

                status, response_headers, response_body = self._request(
                    server,
                    "POST",
                    "/api/v1/export/one-shot",
                    body=body,
                    headers=headers,
                )
                self.assertEqual(status, 429)
                self.assertEqual(
                    response_headers["Cache-Control"],
                    "no-store",
                )
                result = json.loads(response_body.decode("utf-8"))
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["error"]["code"],
                    "rate_limited",
                )
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_one_shot_file_formats(self):
        def calendar_exporter(session, start, end, output_dir, prefix, calendar_name):
            root = Path(output_dir)
            paths = {}
            for extension, content in (
                ("json", b"[]"),
                ("xlsx", b"test-xlsx-content"),
                ("ics", b"BEGIN:VCALENDAR\\r\\nEND:VCALENDAR\\r\\n"),
            ):
                output_path = root / f"{prefix}.{extension}"
                output_path.write_bytes(content)
                paths[extension] = str(output_path)
            return paths

        expected_types = {
            "ics": "text/calendar; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "zip": "application/zip",
        }

        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc", calendar_exporter=calendar_exporter
            )
            payload = json.dumps({
                "userId": "student-id",
                "tokenJWT": "test-token",
                "start": "2026-08-01",
                "end": "2026-10-31",
            }).encode("utf-8")
            try:
                for output_format, expected_type in expected_types.items():
                    with self.subTest(format=output_format):
                        status, headers, body = self._request(
                            server,
                            "POST",
                            f"/api/v1/export/one-shot?format={output_format}",
                            body=payload,
                            headers={"Content-Type": "application/json"},
                        )
                        self.assertEqual(status, 200)
                        self.assertEqual(headers["Content-Type"], expected_type)
                        self.assertEqual(headers["Cache-Control"], "no-store")
                        self.assertIn("attachment;", headers["Content-Disposition"])

                        if output_format == "ics":
                            self.assertIn(b"BEGIN:VCALENDAR", body)
                        elif output_format == "xlsx":
                            self.assertEqual(body, b"test-xlsx-content")
                        else:
                            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                                self.assertEqual(
                                    sorted(archive.namelist()),
                                    ["calendar.ics", "calendar.json", "calendar.xlsx"],
                                )
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_sessions_crud_and_owner_isolation(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc"
            )
            try:
                owner = database.get_or_create_user("api-session-owner", "Owner")
                other = database.get_or_create_user("api-session-other", "Other")
                other_session = database.create_session(
                    int(other["id"]), label="Private session"
                )

                secret = "phk_test_sessions_secret_123456"
                database.create_api_token(
                    token_id="api-sessions-test-token",
                    owner_user_id=int(owner["id"]),
                    token_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
                    token_prefix=secret[:12],
                    scopes=["sessions:read", "sessions:write"],
                    name="session integration test",
                )
                headers = {"Authorization": f"Bearer {secret}"}

                # The owner initially has no sessions.
                status, _headers, body = self._request(
                    server, "GET", "/api/v1/sessions", headers=headers
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    json.loads(body.decode("utf-8"))["data"]["sessions"], []
                )

                # Create a session using the Bearer token.
                payload = {
                    "label": "API-created session",
                    "rangeStart": "2026-09-01",
                    "rangeEnd": "2027-01-31",
                    "syncIntervalHours": 24,
                }
                status, _headers, body = self._request(
                    server,
                    "POST",
                    "/api/v1/sessions",
                    body=json.dumps(payload).encode("utf-8"),
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                    },
                )
                self.assertEqual(status, 201)
                created = json.loads(body.decode("utf-8"))["data"]["session"]
                session_id = created["id"]
                self.assertEqual(created["label"], "API-created session")

                # Listing and reading return only sessions owned by the token owner.
                status, _headers, body = self._request(
                    server, "GET", "/api/v1/sessions", headers=headers
                )
                self.assertEqual(status, 200)
                sessions = json.loads(body.decode("utf-8"))["data"]["sessions"]
                self.assertEqual([item["id"] for item in sessions], [session_id])
                self.assertNotIn(other_session, [item["id"] for item in sessions])

                status, _headers, body = self._request(
                    server, "GET", f"/api/v1/sessions/{session_id}", headers=headers
                )
                self.assertEqual(status, 200)
                detail = json.loads(body.decode("utf-8"))["data"]["session"]
                self.assertEqual(detail["id"], session_id)

                status, _headers, body = self._request(
                    server, "GET", f"/api/v1/sessions/{other_session}", headers=headers
                )
                self.assertEqual(status, 404)

                # Update only the owner's session.
                updated_payload = {"label": "Renamed API session"}
                status, _headers, body = self._request(
                    server,
                    "PATCH",
                    f"/api/v1/sessions/{session_id}",
                    body=json.dumps(updated_payload).encode("utf-8"),
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                    },
                )
                self.assertEqual(status, 200)
                updated = json.loads(body.decode("utf-8"))["data"]["session"]
                self.assertEqual(updated["label"], "Renamed API session")

                # Seed an export file for the session
                export_dir = _config.exports_dir / session_id
                export_dir.mkdir(parents=True, exist_ok=True)
                (export_dir / "calendar.json").write_text("[]", encoding="utf-8")

                # Listing exports only requires sessions:read
                status, _headers, body = self._request(
                    server, "GET", f"/api/v1/sessions/{session_id}/exports", headers=headers
                )
                self.assertEqual(status, 200)

                # Downloading export requires events:read; headers only has sessions:read & sessions:write
                status, _headers, body = self._request(
                    server, "GET", f"/api/v1/sessions/{session_id}/exports/calendar.json", headers=headers
                )
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body.decode("utf-8"))["error"]["code"], "insufficient_scope")

                # Deleting another user's session must return 404.
                status, _headers, _body = self._request(
                    server, "DELETE", f"/api/v1/sessions/{other_session}", headers=headers
                )
                self.assertEqual(status, 404)

                # Delete the owner's session without Google OAuth configured.
                status, _headers, body = self._request(
                    server, "DELETE", f"/api/v1/sessions/{session_id}", headers=headers
                )
                self.assertEqual(status, 200)
                del_resp = json.loads(body.decode("utf-8"))["data"]
                self.assertEqual(del_resp["id"], session_id)
                self.assertTrue(del_resp["deleted"])
                self.assertIsNone(database.get_session(session_id))

                # A request without a Bearer token must be rejected.
                status, _headers, _body = self._request(
                    server, "GET", "/api/v1/sessions"
                )
                self.assertEqual(status, 401)
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_token_create_bearer_me_list_and_revoke(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                _config,
                database,
                signed_sessions,
                _sync,
                server,
                thread,
            ) = self._start_app(directory, auth_mode="oidc")

            cookie = self._app_cookie(
                signed_sessions,
                subject="api-token-owner",
                name="API Token Owner",
                csrf="test-csrf",
            )
            browser_headers = {
                "Content-Type": "application/json",
                "Cookie": f"phenikaa_server_session={cookie}",
                "X-CSRF-Token": "test-csrf",
            }

            try:
                # Create a token using the logged-in browser session and CSRF.
                status, headers, body = self._request(
                    server,
                    "POST",
                    "/api/v1/tokens",
                    body=json.dumps({
                        "name": "test integration token",
                        "scopes": ["me:read", "tokens:read", "tokens:write"],
                    }).encode("utf-8"),
                    headers=browser_headers,
                )
                self.assertEqual(status, 201)
                self.assertEqual(
                    headers["Content-Type"],
                    "application/json; charset=utf-8",
                )
                self.assertEqual(headers["Cache-Control"], "no-store")

                created = json.loads(body.decode("utf-8"))["data"]
                secret = created["token"]
                token_id = created["id"]
                self.assertTrue(secret.startswith("phk_"))

                # Ensure the listed database record does not expose the secret.
                user = database.find_user("api-token-owner")
                self.assertIsNotNone(user)
                records = database.list_api_tokens(int(user["id"]))
                self.assertEqual(len(records), 1)
                self.assertNotIn(secret, repr(records))

                bearer_headers = {"Authorization": f"Bearer {secret}"}

                # The new token identifies its owner.
                status, _headers, body = self._request(
                    server, "GET", "/api/v1/me", headers=bearer_headers
                )
                self.assertEqual(status, 200)
                me_data = json.loads(body.decode("utf-8"))["data"]
                self.assertEqual(me_data["token"]["id"], token_id)
                self.assertIn("me:read", me_data["scopes"])

                # The owner can list their tokens using the appropriate scope.
                status, _headers, body = self._request(
                    server, "GET", "/api/v1/tokens", headers=bearer_headers
                )
                self.assertEqual(status, 200)
                listed = json.loads(body.decode("utf-8"))["data"]["tokens"]
                self.assertEqual(len(listed), 1)
                self.assertEqual(listed[0]["id"], token_id)

                # Revoke the token, then confirm it can no longer authenticate.
                status, _headers, body = self._request(
                    server,
                    "POST",
                    f"/api/v1/tokens/{token_id}/revoke",
                    headers=bearer_headers,
                )
                self.assertEqual(status, 200)
                self.assertTrue(
                    json.loads(body.decode("utf-8"))["data"]["revoked"]
                )

                status, _headers, body = self._request(
                    server, "GET", "/api/v1/me", headers=bearer_headers
                )
                self.assertEqual(status, 401)
                error = json.loads(body.decode("utf-8"))["error"]
                self.assertEqual(error["code"], "invalid_auth")
            finally:
                self._stop_app(database, server, thread)

    def test_api_v1_one_shot_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc"
            )
            cases = [
                (
                    "invalid_range",
                    {
                        "userId": "student-id",
                        "tokenJWT": "test-token",
                        "start": "2026-10-31",
                        "end": "2026-08-01",
                    },
                    "/api/v1/export/one-shot?format=json",
                ),
                (
                    "invalid_auth",
                    {
                        "start": "2026-08-01",
                        "end": "2026-10-31",
                    },
                    "/api/v1/export/one-shot?format=json",
                ),
                (
                    "invalid_format",
                    {
                        "userId": "student-id",
                        "tokenJWT": "test-token",
                        "start": "2026-08-01",
                        "end": "2026-10-31",
                    },
                    "/api/v1/export/one-shot?format=pdf",
                ),
            ]
            try:
                for expected_code, payload, url in cases:
                    with self.subTest(error=expected_code):
                        status, headers, body = self._request(
                            server,
                            "POST",
                            url,
                            body=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        self.assertEqual(status, 400)
                        self.assertEqual(
                            headers["Content-Type"],
                            "application/json; charset=utf-8",
                        )
                        self.assertEqual(headers["Cache-Control"], "no-store")
                        result = json.loads(body.decode("utf-8"))
                        self.assertFalse(result["ok"])
                        self.assertEqual(
                            result["error"]["code"],
                            expected_code,
                        )
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

    def _seed_google_calendar(self, database, session_id, calendar_id="cal-123"):
        database.upsert_google_connection(
            session_id,
            access_token_encrypted="enc-access",
            refresh_token_encrypted="enc-refresh",
            expires_at="2099-01-01T00:00:00+00:00",
            scope=SCOPE,
        )
        database.set_google_calendar_id(session_id, calendar_id)

    def _delete_account(self, server, calendar_action):
        return self._request(
            server,
            "POST",
            "/account/delete",
            body=urllib.parse.urlencode(
                {"csrf": "development", "confirmation": "DELETE", "calendar_action": calendar_action}
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_account_delete_calendar_action_keep_hide_delete_matrix(self):
        for action, expect_deleted, expect_hidden in (
            ("keep", [], []),
            ("hide", [], ["cal-123"]),
            ("delete", ["cal-123"], []),
        ):
            with self.subTest(calendar_action=action):
                with tempfile.TemporaryDirectory() as directory:
                    google = FakeGoogleService()
                    _config, database, _signed, _sync, server, thread = self._start_app(
                        directory, google=google
                    )
                    try:
                        user = database.get_or_create_user("local-development-user", "Local user")
                        session_id = database.create_session(user["id"])
                        self._seed_google_calendar(database, session_id)
                        status, headers, _body = self._delete_account(server, action)
                        self.assertEqual(status, 303)
                        self.assertEqual(headers["Location"], "/")
                        self.assertIsNone(database.get_user(user["id"]))
                        self.assertEqual([cal for _, cal in google.deleted_calendars], expect_deleted)
                        self.assertEqual([cal for _, cal in google.hidden_calendars], expect_hidden)
                    finally:
                        self._stop_app(database, server, thread)

    def test_account_delete_unknown_calendar_action_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, _signed, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                self._seed_google_calendar(database, session_id)
                status, _headers, _body = self._delete_account(server, "wipe")
                self.assertEqual(status, 400)
                self.assertIsNotNone(database.get_user(user["id"]))
                self.assertEqual(google.deleted_calendars, [])
                self.assertEqual(google.hidden_calendars, [])
            finally:
                self._stop_app(database, server, thread)

    def test_account_delete_calendar_failure_warns_but_wipes(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService(calendar_result="raise")
            _config, database, _signed, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                self._seed_google_calendar(database, session_id)
                status, headers, _body = self._delete_account(server, "delete")
                self.assertEqual(status, 303)
                self.assertTrue(headers["Location"].startswith("/?calendar_warning="))
                self.assertIsNone(database.get_user(user["id"]))
                self.assertEqual(database.list_sessions(), [])
            finally:
                self._stop_app(database, server, thread)

    def test_account_delete_calendar_already_gone_redirects_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService(calendar_result="already_gone")
            _config, database, _signed, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                self._seed_google_calendar(database, session_id)
                status, headers, _body = self._delete_account(server, "delete")
                self.assertEqual(status, 303)
                self.assertEqual(headers["Location"], "/")
                self.assertIsNone(database.get_user(user["id"]))
                self.assertEqual([cal for _, cal in google.deleted_calendars], ["cal-123"])
            finally:
                self._stop_app(database, server, thread)

    def test_landing_escapes_calendar_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed, _sync, server, thread = self._start_app(directory)
            try:
                probe = "<script>alert(1)</script>"
                status, _headers, body = self._request(
                    server, "GET", "/?calendar_warning=" + urllib.parse.quote(probe, safe="")
                )
                self.assertEqual(status, 200)
                self.assertNotIn(b"<script>alert(1)</script>", body)
                self.assertIn(b"&lt;script&gt;", body)
            finally:
                self._stop_app(database, server, thread)

    def test_settings_calendar_choice_shown_only_when_connected(self):
        with tempfile.TemporaryDirectory() as directory:
            google = FakeGoogleService()
            _config, database, _signed, _sync, server, thread = self._start_app(directory, google=google)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                status, _headers, body = self._request(server, "GET", "/settings")
                self.assertEqual(status, 200)
                self.assertNotIn(b'name="calendar_action"', body)
                self._seed_google_calendar(database, session_id)
                status, _headers, body = self._request(server, "GET", "/settings")
                self.assertEqual(status, 200)
                self.assertIn(b'name="calendar_action"', body)
                self.assertIn(b'value="keep" checked', body)
                status, _headers, body = self._request(
                    server, "GET", "/settings", headers={"Cookie": "phenikaa_ui_language=vi"}
                )
                self.assertEqual(status, 200)
                self.assertIn("Giữ lịch".encode("utf-8"), body)
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
                directory, auth_mode="oidc", google=google, locks=locks, profile_lock_timeout=0
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

    def test_session_delete_waits_for_transient_profile_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            locks = ProfileLocks()
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(
                directory, locks=locks, profile_lock_timeout=5.0
            )
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                session_id = database.create_session(user["id"])
                profile_lock = locks.for_profile(session_id)
                acquired = threading.Event()

                def hold_lock() -> None:
                    profile_lock.acquire()
                    acquired.set()
                    try:
                        time.sleep(0.5)
                    finally:
                        profile_lock.release()

                holder = threading.Thread(target=hold_lock, daemon=True)
                holder.start()
                self.assertTrue(acquired.wait(5))
                result: list = []
                delete_body = urllib.parse.urlencode({"csrf": "development"})
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                try:
                    connection.request(
                        "POST", f"/sessions/{session_id}/delete", body=delete_body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response = connection.getresponse()
                    result.append(response.status)
                    response.read()
                finally:
                    connection.close()
                holder.join(5)
                self.assertEqual(result, [303])
                self.assertIsNone(database.get_session(session_id))
            finally:
                self._stop_app(database, server, thread)

    def test_google_disconnect_waits_for_transient_profile_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            locks = ProfileLocks()
            google = FakeGoogleService()
            _config, database, signed_sessions, _sync, server, thread = self._start_app(
                directory, auth_mode="oidc", google=google, locks=locks, profile_lock_timeout=5.0
            )
            try:
                user = database.get_or_create_user("subject", "User")
                session_id = database.create_session(user["id"])
                app_cookie = self._app_cookie(signed_sessions)
                body = urllib.parse.urlencode({"csrf": "csrf-token"})
                profile_lock = locks.for_profile(session_id)
                acquired = threading.Event()

                def hold_lock() -> None:
                    profile_lock.acquire()
                    acquired.set()
                    try:
                        time.sleep(0.5)
                    finally:
                        profile_lock.release()

                holder = threading.Thread(target=hold_lock, daemon=True)
                holder.start()
                self.assertTrue(acquired.wait(5))
                status, _headers, _payload = self._request(
                    server,
                    "POST",
                    f"/sessions/{session_id}/google/disconnect",
                    body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"phenikaa_server_session={app_cookie}"},
                )
                holder.join(5)
                self.assertEqual(status, 303)
                self.assertEqual(google.disconnects, [session_id])
            finally:
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
