import json
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from pathlib import Path

if find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from cryptography.fernet import Fernet

from server.crypto import TokenVault
from server.db import Database
from server.google import (
    APP_PRIVATE_KEY,
    EVENTS_URL,
    REVOKE_URL,
    SCOPE,
    TOKEN_URL,
    GoogleCalendarService,
    GoogleHttpResponse,
    GoogleOAuthConfig,
    authorization_url,
    google_event_body,
    source_key,
)

SAMPLE_EVENT = {
    "ID": "class-1",
    "TENHOCPHAN": "Distributed Systems",
    "TENLOPHOCPHAN": "Distributed Systems(N01)<br><br>",
    "NGAYHOC": "24/08/2026",
    "GIOBATDAU": 8,
    "PHUTBATDAU": 0,
    "GIOKETTHUC": 10,
    "PHUTKETTHUC": 0,
    "TIETBATDAU": 1,
    "TIETKETTHUC": 3,
    "TENPHONGHOC": "A1-601",
    "GIANGVIEN": "Teacher",
    "PHANLOAI": "LICHHOC",
}


class FakeGoogleHttp:
    def __init__(self):
        self.calls = []
        self.queue = []

    def push(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.queue.append(GoogleHttpResponse(status, body))

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout})
        if not self.queue:
            raise AssertionError("unexpected Google HTTP call")
        return self.queue.pop(0)


class GoogleCalendarTests(unittest.TestCase):
    def make_service(self, root, http, now=None):
        database = Database(Path(root) / "server.db")
        user = database.get_or_create_user("subject")
        session_id = database.create_session(user["id"])
        vault = TokenVault(Fernet.generate_key())
        config = GoogleOAuthConfig("client-id", "client-secret", "https://app.example/google/callback")
        clock = lambda: now or datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        service = GoogleCalendarService(config, database, vault, http_request=http, clock=clock)
        return service, database, vault, session_id

    def test_authorization_url_uses_web_server_offline_consent_flow(self):
        url = authorization_url(GoogleOAuthConfig("cid", "secret", "https://app/cb"), "state-value")
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], [SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["redirect_uri"], ["https://app/cb"])
        self.assertEqual(query["state"], ["state-value"])

    def test_exchange_code_persists_encrypted_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            http = FakeGoogleHttp()
            http.push(200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1800})
            service, database, vault, session_id = self.make_service(directory, http)
            service.exchange_code(session_id, "code-1")
            form = urllib.parse.parse_qs(http.calls[0]["body"].decode("ascii"))
            self.assertEqual(http.calls[0]["url"], TOKEN_URL)
            self.assertEqual(form["grant_type"], ["authorization_code"])
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertNotIn("access-1", stored["access_token_encrypted"])
            self.assertEqual(vault.decrypt(stored["access_token_encrypted"]), "access-1")
            self.assertEqual(vault.decrypt(stored["refresh_token_encrypted"]), "refresh-1")
            database.close()

    def test_exchange_code_retains_existing_refresh_token_when_reconnect_omits_it(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"access_token": "access-2", "expires_in": 1800})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-1"),
                refresh_token_encrypted=vault.encrypt("refresh-keep"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            )
            service.exchange_code(session_id, "code-2")
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertEqual(vault.decrypt(stored["access_token_encrypted"]), "access-2")
            self.assertEqual(vault.decrypt(stored["refresh_token_encrypted"]), "refresh-keep")
            database.close()

    def test_refresh_retains_existing_refresh_token_when_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"access_token": "new-access", "expires_in": 3600})
            http.push(200, {"id": "google-1"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("expired-access"),
                refresh_token_encrypted=vault.encrypt("refresh-keep"),
                expires_at=(now - timedelta(minutes=1)).isoformat(),
            )
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            refreshed = database.get_google_connection(session_id)
            assert refreshed is not None
            self.assertEqual(vault.decrypt(refreshed["access_token_encrypted"]), "new-access")
            self.assertEqual(vault.decrypt(refreshed["refresh_token_encrypted"]), "refresh-keep")
            refresh_form = urllib.parse.parse_qs(http.calls[0]["body"].decode("ascii"))
            self.assertEqual(refresh_form["grant_type"], ["refresh_token"])
            database.close()

    def test_reconcile_creates_updates_recreates_404_and_deletes_only_links(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(404, {"error": {"message": "missing"}})
            http.push(200, {"id": "google-recreated"})
            http.push(204)
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            key = source_key(SAMPLE_EVENT)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            )
            database.upsert_google_event_link(session_id, key, "google-old")
            database.upsert_google_event_link(session_id, "phenikaa:id:stale", "google-stale")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual((result.created, result.updated, result.deleted), (1, 0, 1))
            methods = [call["method"] for call in http.calls]
            self.assertEqual(methods, ["PUT", "POST", "DELETE"])
            self.assertTrue(http.calls[0]["url"].startswith(EVENTS_URL + "/google-old"))
            self.assertTrue(http.calls[2]["url"].startswith(EVENTS_URL + "/google-stale"))
            sent = json.loads(http.calls[1]["body"].decode("utf-8"))
            self.assertEqual(sent["extendedProperties"]["private"][APP_PRIVATE_KEY], key)
            links = database.list_google_event_links(session_id)
            self.assertEqual(links, [{
                "session_id": session_id,
                "source_key": key,
                "google_event_id": "google-recreated",
                "updated_at": links[0]["updated_at"],
            }])
            database.close()

    def test_disconnect_revokes_refresh_token_removes_connection_and_retains_links(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(400, {"error": "invalid_token"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            key = source_key(SAMPLE_EVENT)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            )
            database.upsert_google_event_link(session_id, key, "google-1")
            service.disconnect(session_id)
            self.assertEqual(http.calls[0]["url"], REVOKE_URL)
            self.assertEqual(http.calls[0]["method"], "POST")
            form = urllib.parse.parse_qs(http.calls[0]["body"].decode("ascii"))
            self.assertEqual(form["token"], ["refresh-live"])
            self.assertIsNone(database.get_google_connection(session_id))
            self.assertEqual(database.list_google_event_links(session_id)[0]["google_event_id"], "google-1")
            database.close()

    def test_disconnect_surfaces_unexpected_revoke_error_and_keeps_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(503, {"error": {"message": "try later"}})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            )
            with self.assertRaisesRegex(Exception, "try later"):
                service.disconnect(session_id)
            self.assertIsNotNone(database.get_google_connection(session_id))
            database.close()

    def test_source_key_distinguishes_same_id_on_different_occurrences(self):
        later = dict(SAMPLE_EVENT)
        later["NGAYHOC"] = "31/08/2026"
        later["GIOBATDAU"] = 10
        same_time_other_section = dict(SAMPLE_EVENT)
        same_time_other_section["TENLOPHOCPHAN"] = "Distributed Systems(N02)<br><br>"
        self.assertNotEqual(source_key(SAMPLE_EVENT), source_key(later))
        self.assertNotEqual(source_key(SAMPLE_EVENT), source_key(same_time_other_section))

    def test_source_key_fallback_is_deterministic_and_distinguishes_end_time(self):
        first = dict(SAMPLE_EVENT)
        first["ID"] = ""
        second = dict(first)
        second["GIOKETTHUC"] = 11
        self.assertEqual(source_key(first), source_key(dict(first)))
        self.assertNotEqual(source_key(first), source_key(second))

    def test_google_body_preserves_local_times_and_fields(self):
        body = google_event_body(SAMPLE_EVENT)
        self.assertEqual(body["summary"], "Distributed Systems")
        self.assertEqual(body["location"], "A1-601")
        self.assertEqual(body["start"], {"dateTime": "2026-08-24T08:00:00", "timeZone": "Asia/Ho_Chi_Minh"})
        self.assertEqual(body["end"], {"dateTime": "2026-08-24T10:00:00", "timeZone": "Asia/Ho_Chi_Minh"})
        self.assertIn("Class: Distributed Systems(N01)", body["description"])


if __name__ == "__main__":
    unittest.main()
