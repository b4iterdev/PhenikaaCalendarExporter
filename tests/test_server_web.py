import http.client
from http import cookies
import tempfile
import threading
import unittest
import urllib.parse
from importlib.util import find_spec
from pathlib import Path

if find_spec("jwt") is None or find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from cryptography.fernet import Fernet

from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database
from server.login_broker import LoginBroker
from server.oidc import SignedSessions
from server.refresh import ProfileLocks
from server.sync import SyncEngine
from server.web import ServerApplication, make_server


class FakeGoogleService:
    def __init__(self):
        self.states: list[str] = []
        self.exchanges: list[tuple[str, str]] = []
        self.disconnects: list[str] = []

    def authorization_url(self, state: str) -> str:
        self.states.append(state)
        return "https://accounts.example/auth?" + urllib.parse.urlencode({"state": state})

    def exchange_code(self, session_id: str, code: str) -> None:
        self.exchanges.append((session_id, code))

    def disconnect(self, session_id: str) -> None:
        self.disconnects.append(session_id)


class RecordingSync:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def request_sync(self, session_id: str) -> None:
        self.requested.append(session_id)


class WebSmokeTests(unittest.TestCase):
    def _start_app(self, directory, *, auth_mode="disabled", google=None):
        config = ServerConfig(state_dir=Path(directory), host="127.0.0.1", port=0, auth_mode=auth_mode)
        config.ensure_dirs()
        database = Database(config.db_path)
        vault = TokenVault(Fernet.generate_key())
        signed_sessions = SignedSessions(b"x" * 32)
        broker = LoginBroker(config, locks=ProfileLocks())
        sync = RecordingSync()
        app = ServerApplication(config, database, vault, signed_sessions, broker, sync, None, google)
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
                connection.request("GET", "/")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                response.read()
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
            finally:
                self._stop_app(database, server, thread)

    def test_google_callback_success_exchanges_code_requests_sync_and_clears_transaction(self):
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
                    "/auth/google/callback?state=state-ok&code=code-ok",
                    headers={"Cookie": f"phenikaa_google_oauth_transaction={transaction}"},
                )
                self.assertEqual(status, 303)
                self.assertEqual(headers["Location"], "/")
                self.assertIn("phenikaa_google_oauth_transaction=;", headers["Set-Cookie"])
                self.assertEqual(google.exchanges, [(session_id, "code-ok")])
                self.assertEqual(sync.requested, [session_id])
            finally:
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

    def test_google_dashboard_states_absent_connected_error_and_no_token_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            _config, database, _signed_sessions, _sync, server, thread = self._start_app(directory)
            try:
                user = database.get_or_create_user("local-development-user", "Local user")
                database.create_session(user["id"], label="No Google")
                status, _headers, body = self._request(server, "GET", "/")
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
                unconnected = database.create_session(user["id"], label="Unconnected")
                database.upsert_google_connection(
                    connected,
                    access_token_encrypted="access-token-secret",
                    refresh_token_encrypted="refresh-token-secret",
                    expires_at="2026-08-30T12:00:00+00:00",
                )
                database.set_google_connection_error(connected, "bad <token>")
                status, _headers, body = self._request(server, "GET", "/")
                self.assertEqual(status, 200)
                self.assertIn(b"Google Calendar: <strong>Connected</strong>", body)
                self.assertIn(f"/sessions/{unconnected}/google/connect".encode("utf-8"), body)
                self.assertIn(b"bad &lt;token&gt;", body)
                self.assertNotIn(b"access-token-secret", body)
                self.assertNotIn(b"refresh-token-secret", body)
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
