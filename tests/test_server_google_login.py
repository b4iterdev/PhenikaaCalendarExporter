import http.client
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database
from server.google import GoogleHttpResponse, GoogleOAuthConfig
from server.google_login import GoogleLoginService, LOGIN_SCOPE
from server.login_broker import LoginBroker
from server.oidc import SignedSessions
from server.web import APP_COOKIE, GOOGLE_OAUTH_COOKIE, ServerApplication, make_server

SAMPLE_EVENT = {
    "ID": "class-1", "TENHOCPHAN": "Distributed Systems", "PHANLOAI": "LICHHOC",
    "NGAYHOC": "24/08/2026", "GIOBATDAU": 8, "PHUTBATDAU": 0,
    "GIOKETTHUC": 10, "PHUTKETTHUC": 0,
}


class RecordingSync:
    def __init__(self):
        self.requested: list[str] = []

    def request_sync(self, session_id: str) -> None:
        self.requested.append(session_id)


class GoogleLoginTests(unittest.TestCase):
    directory: tempfile.TemporaryDirectory[str]
    config: ServerConfig
    db: Database
    vault: TokenVault
    responses: list[tuple[int, dict[str, Any]]]
    calls: list[tuple[str, str, dict[str, str], bytes]]
    service: GoogleLoginService
    cookies: dict[str, str]
    signed: SignedSessions
    app: ServerApplication
    server: Any
    thread: threading.Thread
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = ServerConfig(state_dir=Path(self.directory.name), auth_mode="google", port=0)
        self.config.ensure_dirs()
        self.db = Database(self.config.db_path)
        self.addCleanup(self.db.close)
        self.vault = TokenVault(Fernet.generate_key())
        self.responses = []
        self.calls = []
        self.service = GoogleLoginService(GoogleOAuthConfig("client", "secret", "https://app/auth/google/callback"),
                                          self.db, self.vault, http_request=self.http)
        self.cookies = {}
        self.signed = SignedSessions(b"x" * 32)
        self.app = ServerApplication(self.config, self.db, self.vault, self.signed, LoginBroker(self.config), RecordingSync(), None, self.service)
        self.server = make_server(self.app)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def setUp(self):
        jwks = patch("server.google_login.PyJWKClient")
        mock = jwks.start()
        self.addCleanup(jwks.stop)
        mock.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(key=self.key.public_key())

    def http(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        status, payload = self.responses.pop(0)
        return GoogleHttpResponse(status, json.dumps(payload).encode())

    def token(self, subject="alice", nonce="nonce", *, refresh=True, scope=LOGIN_SCOPE, **claims) -> dict[str, Any]:
        now = int(time.time())
        identity = {"sub": subject, "iss": "https://accounts.google.com", "aud": "client", "iat": now,
                    "exp": now + 3600, "nonce": nonce, "email": subject + "@example.com", "name": "Alice", **claims}
        token = {"id_token": jwt.encode(identity, self.key, algorithm="RS256"),
                 "access_token": "access-" + subject, "scope": scope, "expires_in": 3600}
        if refresh:
            token["refresh_token"] = "refresh-" + subject
        return token

    def login(self, **kwargs):
        self.responses.append((200, self.token(**kwargs)))
        return self.service.login("code", "verifier", "nonce")

    def test_url_combines_identity_calendar_offline_and_pkce_without_forcing_consent(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.service.login_url("state", "nonce", "challenge")).query)
        self.assertEqual(query["scope"], [LOGIN_SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("prompt", query)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.service.login_url("s", "n", "c", consent=True, subject="alice")).query)
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["login_hint"], ["alice"])

    def test_login_persists_encrypted_grant_before_phenikaa_and_reuses_refresh(self):
        identity = self.login()
        user = self.db.find_user(identity["sub"])
        assert user is not None
        self.assertEqual(self.db.list_sessions(), [])
        grant = self.db.get_google_user_grant(user["id"])
        assert grant is not None
        self.assertNotIn("refresh-alice", grant["credentials_encrypted"])
        self.assertTrue(self.status(user["id"])["ready"])
        self.login(refresh=False)
        stored = self.db.get_google_user_grant(user["id"])
        assert stored is not None
        credentials = self.service._credentials(stored)
        self.assertEqual(self.vault.decrypt(credentials["refresh_token_encrypted"]), "refresh-alice")
        self.assertEqual(urllib.parse.parse_qs(self.calls[0][3].decode())["code_verifier"], ["verifier"])

    def test_partial_consent_and_missing_refresh_do_not_enable_sync(self):
        for subject, kwargs in (("partial", {"scope": "openid email"}), ("missing", {"refresh": False}), ("scope", {"scope": ""})):
            identity = self.login(subject=subject, **kwargs)
            user = self.db.find_user(identity["sub"])
            assert user is not None
            self.assertFalse(self.status(user["id"])["ready"])
            sid = self.db.create_session(user["id"])
            self.assertIsNone(self.service.connection(sid))

    def test_invalid_identity_is_rejected_before_creating_user(self):
        overrides: list[dict[str, Any]] = [{"nonce": "wrong"}, {"aud": "attacker"}, {"azp": "attacker"}, {"iss": "https://attacker"}, {"exp": 1}]
        for override in overrides:
            with self.subTest(override=override):
                self.responses.append((200, self.token(**override)))
                with self.assertRaises(Exception):
                    self.service.login("code", "verifier", "nonce")
                self.assertIsNone(self.db.find_user("google:alice"))

    def test_bad_signature_is_rejected(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = self.token()
        claims = jwt.decode(token["id_token"], options={"verify_signature": False})
        token["id_token"] = jwt.encode(claims, other_key, algorithm="RS256")
        self.responses.append((200, token))
        with self.assertRaises(jwt.InvalidSignatureError):
            self.service.login("code", "verifier", "nonce")

    def test_reauthorization_cannot_change_account_or_tokens(self):
        identity = self.login()
        user = self.db.find_user(identity["sub"])
        assert user is not None
        before = self.db.get_google_user_grant(user["id"])
        self.responses.append((200, self.token(subject="bob")))
        with self.assertRaisesRegex(RuntimeError, "same Google account"):
            self.service.login("code", "verifier", "nonce", expected_sub="alice")
        self.assertEqual(before, self.db.get_google_user_grant(user["id"]))
        self.assertIsNone(self.db.find_user("google:bob"))

    def test_existing_oidc_subject_collision_never_links(self):
        self.db.get_or_create_user("google:alice", "OIDC user")
        self.responses.append((200, self.token()))
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            self.service.login("code", "verifier", "nonce")

    def test_sync_uses_owner_grant_creates_dedicated_calendar_and_refreshes(self):
        identity = self.login()
        user = self.db.find_user(identity["sub"])
        assert user is not None
        sid = self.db.create_session(user["id"])
        self.responses.extend([(200, {"id": "app-calendar"}), (200, {"id": "event-1"})])
        result = self.service.sync_session(sid, [SAMPLE_EVENT])
        self.assertTrue(result.ok)
        self.assertEqual(result.created, 1)
        self.assertTrue(self.calls[-1][1].endswith("/app-calendar/events"))
        self.assertEqual(self.db.list_google_event_links(sid)[0]["google_event_id"], "event-1")
        self.assertEqual(self.calls[-1][2]["Authorization"], "Bearer access-alice")
        self.assertIsNone(self.db.get_google_connection(sid))
        state = self.db.get_google_calendar_state(sid)
        assert state is not None
        self.assertEqual(state["calendar_id"], "app-calendar")
        grant = self.db.get_google_user_grant(user["id"])
        assert grant is not None
        credentials = self.service._credentials(grant)
        credentials["expires_at"] = "2000-01-01T00:00:00+00:00"
        self.db.save_google_user_grant(user["id"], "alice", grant["email"], self.vault.encrypt(json.dumps(credentials)))
        self.responses.extend([(200, {"access_token": "refreshed", "expires_in": 3600}), (200, {"id": "app-calendar"}), (200, {"id": "event-1"})])
        self.assertTrue(self.service.sync_session(sid, [SAMPLE_EVENT]).ok)
        self.assertEqual(self.calls[-1][2]["Authorization"], "Bearer refreshed")
        self.assertTrue(self.status(user["id"])["ready"])

    def test_pause_survives_login_and_session_deletion_preserves_grant(self):
        identity = self.login()
        user = self.db.find_user(identity["sub"])
        assert user is not None
        sid = self.db.create_session(user["id"])
        self.service.disconnect(sid)
        self.login(refresh=False)
        self.assertFalse(self.service.sync_session(sid, []).attempted)
        self.db.set_google_user_sync(user["id"], True)
        self.assertIsNotNone(self.service.connection(sid))
        self.db.delete_session(sid)
        self.assertTrue(self.status(user["id"])["ready"])
        self.db.delete_user(user["id"])
        self.assertIsNone(self.db.get_google_user_grant(user["id"]))

    def start_web(self):
        self.thread.start()
        self.addCleanup(self.stop_web)

    def status(self, user_id):
        status = self.service.grant_status(user_id)
        assert status is not None
        return status

    def stop_web(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def request(self, path, *, form=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Cookie": "; ".join(f"{key}={value}" for key, value in self.cookies.items())}
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request("GET" if form is None else "POST", path, body=urllib.parse.urlencode(form) if form is not None else None, headers=headers)
        response = connection.getresponse()
        body = response.read().decode()
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                for name, cookie in SimpleCookie(value).items():
                    self.cookies[name] = cookie.value
        result = response.status, response.getheader("Location"), body
        connection.close()
        return result

    def web_login(self, *, subject="alice", scope=LOGIN_SCOPE, path="/auth/login"):
        status, location, _ = self.request(path)
        self.assertEqual(status, 303)
        assert isinstance(location, str)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        self.responses.append((200, self.token(subject=subject, nonce=query["nonce"][0], scope=scope)))
        return self.request("/auth/google/callback?" + urllib.parse.urlencode({"state": query["state"][0], "code": "code"}))

    def csrf(self):
        claims = self.signed.verify(self.cookies[APP_COOKIE])
        assert claims is not None
        return claims["csrf"]

    def test_http_login_onboarding_pause_logout_and_reauthorize_wrong_account(self):
        self.start_web()
        self.assertIn("Sign in with Google", self.request("/")[2])
        self.assertEqual(self.web_login()[:2], (303, "/dashboard"))
        self.assertEqual(self.cookies[GOOGLE_OAUTH_COOKIE], "")
        body = self.request("/dashboard")[2]
        self.assertIn("alice@example.com", body)
        self.assertIn("Connected", body)
        self.assertIn("Create and sign in", body)
        self.assertNotIn("/google/connect", body)
        status, location, _ = self.request("/sessions", form={"csrf": self.csrf()})
        self.assertEqual(status, 303)
        assert location is not None
        self.assertTrue(location.endswith("/login"))
        self.assertEqual(self.request("/account/google/pause", form={"csrf": "bad"})[0], 403)
        self.request("/account/google/pause", form={"csrf": self.csrf()})
        self.assertIn("Paused", self.request("/dashboard")[2])
        self.request("/account/google/resume", form={"csrf": self.csrf()})
        self.assertIn("Connected", self.request("/dashboard")[2])
        self.assertEqual(self.web_login(subject="bob", path="/auth/google/authorize")[0], 502)
        self.assertIn("alice@example.com", self.request("/dashboard")[2])
        self.request("/auth/logout", form={"csrf": self.csrf()})
        self.assertEqual(self.request("/dashboard")[:2], (303, "/auth/login"))
        user = self.db.find_user("google:alice")
        assert user is not None
        self.assertIsNotNone(self.db.get_google_user_grant(user["id"]))

    def test_http_partial_consent_and_invalid_callback(self):
        self.start_web()
        self.assertEqual(self.request("/auth/google/callback?state=bad&code=bad")[0], 400)
        self.assertEqual(self.web_login(scope="openid email")[0], 303)
        body = self.request("/dashboard")[2]
        self.assertIn("Authorization needed", body)
        self.assertIn("/auth/google/authorize", body)
        self.assertNotIn("Pause calendar sync", body)

    def test_http_delete_revokes_grant_without_phenikaa_session(self):
        self.start_web()
        self.web_login()
        user = self.db.find_user("google:alice")
        assert user is not None
        self.responses.append((200, {}))
        self.assertEqual(self.request("/account/delete", form={"csrf": self.csrf(), "confirmation": "DELETE"})[0], 303)
        self.assertTrue(self.calls[-1][1].endswith("/revoke"))
        self.assertIsNone(self.db.get_google_user_grant(user["id"]))
        self.assertIsNone(self.db.get_user(user["id"]))

    def test_oidc_cookie_cannot_access_google_user_after_mode_switch(self):
        self.start_web()
        self.login()
        self.cookies[APP_COOKIE] = self.signed.create({"sub": "google:alice", "csrf": "token"})
        self.assertEqual(self.request("/dashboard")[:2], (303, "/auth/login"))

    def test_deletion_while_session_busy_does_not_revoke_grant(self):
        self.start_web()
        self.web_login()
        user = self.db.find_user("google:alice")
        assert user is not None
        sid = self.db.create_session(user["id"])
        lock = self.app.broker.try_profile_lock(sid)
        assert lock is not None
        before = len(self.calls)
        try:
            result = self.request("/account/delete", form={"csrf": self.csrf(), "confirmation": "DELETE"})
            self.assertEqual(result[0], 409)
            self.assertEqual(len(self.calls), before)
            self.assertIsNotNone(self.db.get_user(user["id"]))
        finally:
            lock.release()

    def test_startup_rejects_unknown_mode_and_missing_google_configuration(self):
        from server.__main__ import main
        with patch.dict("os.environ", {"PHENIKAA_SERVER_AUTH": "invalid"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must be oidc, google, or disabled"):
                main([])
        with patch.dict("os.environ", {"PHENIKAA_SERVER_AUTH": "google"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Google login requires"):
                main([])


if __name__ == "__main__":
    unittest.main()
