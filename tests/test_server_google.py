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
    CALENDARS_URL,
    APP_CREATED_SCOPE,
    EVENTS_BASE_URL,
    EVENTS_SCOPE,
    LEGACY_CLEANUP_SCOPE,
    PRIMARY_CALENDAR_ID,
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


def events_url(calendar_id: str) -> str:
    return EVENTS_BASE_URL + "/" + urllib.parse.quote(calendar_id, safe="") + "/events"


def calendar_url(calendar_id: str) -> str:
    return CALENDARS_URL + "/" + urllib.parse.quote(calendar_id, safe="")

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

    def test_authorization_url_defaults_to_app_created_scope_only(self):
        url = authorization_url(GoogleOAuthConfig("cid", "secret", "https://app/cb"), "state-value")
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], [APP_CREATED_SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["redirect_uri"], ["https://app/cb"])
        self.assertEqual(query["state"], ["state-value"])


    def test_authorization_url_can_request_temporary_legacy_cleanup_scope(self):
        url = authorization_url(
            GoogleOAuthConfig("cid", "secret", "https://app/cb"), "state-value", LEGACY_CLEANUP_SCOPE
        )
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query["scope"], [LEGACY_CLEANUP_SCOPE])

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
            self.assertEqual(stored["scope"], SCOPE)
            database.close()

    def test_exchange_code_without_scope_stores_exact_requested_scope_fallback(self):
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
                scope=EVENTS_SCOPE,
            )
            service.exchange_code(session_id, "code-2", LEGACY_CLEANUP_SCOPE)
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertEqual(vault.decrypt(stored["access_token_encrypted"]), "access-2")
            self.assertEqual(vault.decrypt(stored["refresh_token_encrypted"]), "refresh-keep")
            self.assertEqual(stored["scope"], LEGACY_CLEANUP_SCOPE)
            database.close()

    def test_exchange_code_retains_existing_refresh_token_when_reconnect_omits_it(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"access_token": "access-2", "expires_in": 1800, "scope": SCOPE})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-1"),
                refresh_token_encrypted=vault.encrypt("refresh-keep"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
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
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"id": "google-1"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("expired-access"),
                refresh_token_encrypted=vault.encrypt("refresh-keep"),
                expires_at=(now - timedelta(minutes=1)).isoformat(),
                scope=SCOPE,
            )
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            refreshed = database.get_google_connection(session_id)
            assert refreshed is not None
            self.assertEqual(vault.decrypt(refreshed["access_token_encrypted"]), "new-access")
            self.assertEqual(vault.decrypt(refreshed["refresh_token_encrypted"]), "refresh-keep")
            self.assertEqual(refreshed["scope"], SCOPE)
            refresh_form = urllib.parse.parse_qs(http.calls[0]["body"].decode("ascii"))
            self.assertEqual(refresh_form["grant_type"], ["refresh_token"])
            self.assertEqual(http.calls[1]["url"], CALENDARS_URL)
            self.assertEqual(http.calls[2]["url"], events_url("app-calendar"))
            database.close()

    def test_fresh_sync_creates_app_calendar_and_never_calls_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"id": "google-1"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual((result.created, result.updated, result.deleted), (1, 0, 0))
            self.assertEqual(http.calls[0]["url"], CALENDARS_URL)
            calendar_body = json.loads(http.calls[0]["body"].decode("utf-8"))
            self.assertEqual(calendar_body["summary"], "Phenikaa Learning Calendar")
            self.assertEqual(http.calls[1]["url"], events_url("app-calendar"))
            self.assertNotIn("/primary/", " ".join(call["url"] for call in http.calls))
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertEqual(stored["calendar_id"], "app-calendar")
            self.assertEqual(stored["migration_state"], "app_calendar_ready")
            link = database.list_google_event_links(session_id, "app-calendar")[0]
            self.assertEqual(link["google_event_id"], "google-1")
            database.close()

    def test_reconcile_existing_app_calendar_creates_updates_recreates_404_and_deletes_only_links(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(404, {"error": {"message": "missing"}})
            http.push(200, {"id": "google-recreated"})
            http.push(200, {"extendedProperties": {"private": {APP_PRIVATE_KEY: "phenikaa:id:stale"}}})
            http.push(204)
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            key = source_key(SAMPLE_EVENT)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            database.set_google_calendar_id(session_id, "app-calendar")
            database.upsert_google_event_link(session_id, key, "google-old", "app-calendar")
            database.upsert_google_event_link(session_id, "phenikaa:id:stale", "google-stale", "app-calendar")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual((result.created, result.updated, result.deleted), (1, 0, 1))
            methods = [call["method"] for call in http.calls]
            self.assertEqual(methods, ["GET", "PUT", "POST", "GET", "DELETE"])
            self.assertEqual(http.calls[0]["url"], calendar_url("app-calendar"))
            self.assertTrue(http.calls[1]["url"].startswith(events_url("app-calendar") + "/google-old"))
            self.assertTrue(http.calls[3]["url"].startswith(events_url("app-calendar") + "/google-stale"))
            self.assertTrue(http.calls[4]["url"].startswith(events_url("app-calendar") + "/google-stale"))
            sent = json.loads(http.calls[2]["body"].decode("utf-8"))
            self.assertEqual(sent["extendedProperties"]["private"][APP_PRIVATE_KEY], key)
            links = database.list_google_event_links(session_id, "app-calendar")
            self.assertEqual(links, [{
                "session_id": session_id,
                "calendar_id": "app-calendar",
                "source_key": key,
                "google_event_id": "google-recreated",
                "updated_at": links[0]["updated_at"],
            }])
            database.close()

    def test_existing_calendar_and_event_ids_are_url_encoded(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "calendar/with @sign"})
            http.push(200, {"id": "event/with @sign"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            key = source_key(SAMPLE_EVENT)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            database.set_google_calendar_id(session_id, "calendar/with @sign")
            database.upsert_google_event_link(session_id, key, "event/with @sign", "calendar/with @sign")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual(http.calls[0]["url"], CALENDARS_URL + "/calendar%2Fwith%20%40sign")
            self.assertEqual(
                http.calls[1]["url"],
                EVENTS_BASE_URL + "/calendar%2Fwith%20%40sign/events/event%2Fwith%20%40sign",
            )
            database.close()

    def test_legacy_primary_cleanup_finishes_before_app_reconcile_and_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(404, {"error": {"message": "already gone"}})
            http.push(410, {"error": {"message": "deleted"}})
            http.push(200, {"id": "app-event"})
            http.push(200)
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            key = source_key(SAMPLE_EVENT)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=LEGACY_CLEANUP_SCOPE,
            )
            database.set_google_migration_state(session_id, "primary_cleanup_pending")
            database.upsert_google_event_link(session_id, key, "primary-old")
            database.upsert_google_event_link(session_id, "phenikaa:id:stale", "primary-stale")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual([call["method"] for call in http.calls], ["POST", "GET", "GET", "POST", "POST"])
            self.assertTrue(http.calls[1]["url"].startswith(events_url(PRIMARY_CALENDAR_ID) + "/primary-old"))
            self.assertTrue(http.calls[2]["url"].startswith(events_url(PRIMARY_CALENDAR_ID) + "/primary-stale"))
            self.assertEqual(http.calls[4]["url"], REVOKE_URL)
            self.assertEqual(database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID), [])
            self.assertIsNone(database.get_google_connection(session_id))
            state = database.get_google_calendar_state(session_id)
            assert state is not None
            self.assertEqual(state["calendar_id"], "app-calendar")
            self.assertEqual(state["migration_state"], "app_calendar_ready")
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("app-access"),
                refresh_token_encrypted=vault.encrypt("app-refresh"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"id": "app-event"})
            second = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(second.ok)
            self.assertEqual(http.calls[-2]["method"], "GET")
            self.assertEqual(http.calls[-1]["method"], "PUT")
            self.assertTrue(http.calls[-1]["url"].startswith(events_url("app-calendar") + "/app-event"))
            database.close()


    def test_primary_cleanup_verifies_matching_private_marker_before_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"extendedProperties": {"private": {APP_PRIVATE_KEY: "different-source"}}})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=LEGACY_CLEANUP_SCOPE,
            )
            database.set_google_migration_state(session_id, "primary_cleanup_pending")
            database.upsert_google_event_link(session_id, "phenikaa:id:legacy", "primary-event")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertFalse(result.ok)
            self.assertIn("private marker did not match", result.detail)
            self.assertEqual([call["method"] for call in http.calls], ["POST", "GET"])
            self.assertEqual(database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID)[0]["google_event_id"], "primary-event")
            database.close()

    def test_primary_cleanup_rejects_missing_private_marker_without_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(200, {})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=LEGACY_CLEANUP_SCOPE,
            )
            database.set_google_migration_state(session_id, "primary_cleanup_pending")
            database.upsert_google_event_link(session_id, "phenikaa:id:legacy", "primary-event")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertFalse(result.ok)
            self.assertIn("did not include the app private marker", result.detail)
            self.assertEqual([call["method"] for call in http.calls], ["POST", "GET"])
            self.assertEqual(database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID)[0]["google_event_id"], "primary-event")
            database.close()

    def test_primary_calendar_id_is_never_used_as_dedicated_calendar(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"id": "google-1"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            with self.assertRaisesRegex(ValueError, "cannot be primary"):
                database.set_google_calendar_id(session_id, PRIMARY_CALENDAR_ID)
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual([call["method"] for call in http.calls], ["POST", "POST"])
            self.assertEqual(http.calls[0]["url"], CALENDARS_URL)
            self.assertNotIn("/primary", " ".join(call["url"] for call in http.calls))
            database.close()

    def test_deleted_dedicated_calendar_is_recreated_and_old_app_links_are_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(404, {"error": {"message": "not found"}})
            http.push(200, {"id": "replacement-calendar"})
            http.push(200, {"id": "replacement-event"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            key = source_key(SAMPLE_EVENT)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            database.set_google_calendar_id(session_id, "deleted-calendar")
            database.upsert_google_event_link(session_id, key, "deleted-calendar-event", "deleted-calendar")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual([call["method"] for call in http.calls], ["GET", "POST", "POST"])
            self.assertEqual(http.calls[0]["url"], calendar_url("deleted-calendar"))
            self.assertEqual(http.calls[1]["url"], CALENDARS_URL)
            self.assertEqual(http.calls[2]["url"], events_url("replacement-calendar"))
            self.assertNotIn("/primary/", " ".join(call["url"] for call in http.calls))
            self.assertEqual(database.list_google_event_links(session_id, "deleted-calendar"), [])
            replacement = database.list_google_event_links(session_id, "replacement-calendar")
            self.assertEqual(replacement[0]["google_event_id"], "replacement-event")
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertEqual(stored["calendar_id"], "replacement-calendar")
            database.close()

    def test_legacy_events_only_scope_requires_reconnect_before_calendar_insert(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=EVENTS_SCOPE,
            )
            database.set_google_migration_state(session_id, "primary_cleanup_pending")
            database.upsert_google_event_link(session_id, "phenikaa:id:legacy", "primary-event")
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertFalse(result.ok)
            self.assertIn("Reconnect Google Calendar to authorize dedicated calendar creation", result.detail)
            self.assertEqual(http.calls, [])
            self.assertEqual(database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID)[0]["google_event_id"], "primary-event")
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertEqual(stored["migration_state"], "primary_cleanup_pending")
            database.close()

    def test_reconnect_reuses_retained_app_calendar_id_without_creating_duplicate_calendar(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200)
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"id": "app-event"})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("old-access"),
                refresh_token_encrypted=vault.encrypt("old-refresh"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            database.set_google_calendar_id(session_id, "app-calendar")
            service.disconnect(session_id)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("new-access"),
                refresh_token_encrypted=vault.encrypt("new-refresh"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=SCOPE,
            )
            result = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(result.ok)
            self.assertEqual([call["method"] for call in http.calls], ["POST", "GET", "POST"])
            self.assertEqual(http.calls[0]["url"], REVOKE_URL)
            self.assertEqual(http.calls[1]["url"], calendar_url("app-calendar"))
            self.assertEqual(http.calls[2]["url"], events_url("app-calendar"))
            self.assertNotEqual(http.calls[2]["url"], CALENDARS_URL)
            database.close()

    def test_partial_primary_cleanup_is_retryable_without_losing_remaining_legacy_links(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
            http = FakeGoogleHttp()
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"extendedProperties": {"private": {APP_PRIVATE_KEY: "phenikaa:id:first"}}})
            http.push(204)
            http.push(503, {"error": {"message": "try later"}})
            service, database, vault, session_id = self.make_service(directory, http, now=now)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted=vault.encrypt("access-live"),
                refresh_token_encrypted=vault.encrypt("refresh-live"),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                scope=LEGACY_CLEANUP_SCOPE,
            )
            database.set_google_migration_state(session_id, "primary_cleanup_pending")
            database.upsert_google_event_link(session_id, "phenikaa:id:first", "primary-first")
            database.upsert_google_event_link(session_id, "phenikaa:id:second", "primary-second")
            first = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertFalse(first.ok)
            remaining = database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID)
            self.assertEqual([row["google_event_id"] for row in remaining], ["primary-second"])
            stored = database.get_google_connection(session_id)
            assert stored is not None
            self.assertEqual(stored["calendar_id"], "app-calendar")
            self.assertEqual(stored["migration_state"], "primary_cleanup_pending")
            http.push(200, {"id": "app-calendar"})
            http.push(200, {"extendedProperties": {"private": {APP_PRIVATE_KEY: "phenikaa:id:second"}}})
            http.push(204)
            http.push(200, {"id": "app-event"})
            http.push(503, {"error": {"message": "revoke later"}})
            second = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertFalse(second.ok)
            self.assertIn("revoke later", second.detail)
            self.assertEqual(database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID), [])
            http.push(200, {"id": "app-calendar"})
            http.push(200)
            http.push(200)
            third = service.sync_session(session_id, [SAMPLE_EVENT])
            self.assertTrue(third.ok)
            self.assertEqual([call["method"] for call in http.calls[-3:]], ["GET", "PUT", "POST"])
            self.assertEqual(http.calls[-1]["url"], REVOKE_URL)
            self.assertNotIn(events_url(PRIMARY_CALENDAR_ID), " ".join(call["url"] for call in http.calls[-3:]))
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
