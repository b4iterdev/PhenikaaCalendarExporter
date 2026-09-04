import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import date
from importlib.util import find_spec
from pathlib import Path

if find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from server.config import academic_year_range
from server.crypto import TokenVault, load_or_create_key, token_fingerprint
from server.db import Database, OwnerSessionExistsError, STATUS_ACTIVE


class ConfigAndCryptoTests(unittest.TestCase):
    def test_academic_year_surrounds_date(self):
        self.assertEqual(academic_year_range(date(2026, 8, 1)), (date(2026, 8, 1), date(2027, 7, 31)))
        self.assertEqual(academic_year_range(date(2026, 3, 1)), (date(2025, 8, 1), date(2026, 7, 31)))

    def test_key_file_permissions_and_token_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            key = load_or_create_key(path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            vault = TokenVault(key)
            encrypted = vault.encrypt("secret-token")
            self.assertNotIn("secret-token", encrypted)
            self.assertEqual(vault.decrypt(encrypted), "secret-token")
            fingerprint = token_fingerprint("secret-token")
            assert fingerprint is not None
            self.assertEqual(len(fingerprint), 12)


class DatabaseTests(unittest.TestCase):
    def test_user_session_credentials_and_sync_history(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "server.db")
            user = database.get_or_create_user("subject-1", "Student")
            self.assertEqual(database.get_or_create_user("subject-1")["id"], user["id"])
            session_id = database.create_session(
                user["id"], label="Main", range_start="2026-08-01", range_end="2027-07-31"
            )
            database.update_session_credentials(session_id, "student-id", "encrypted", "fingerprint")
            stored = database.get_session(session_id)
            assert stored is not None
            self.assertEqual(stored["status"], STATUS_ACTIVE)
            run_id = database.start_sync_run(session_id)
            database.finish_sync_run(run_id, ok=True, events=2, detail="saved")
            self.assertEqual(database.last_sync_runs(session_id)[0]["events"], 2)
            database.upsert_google_connection(
                session_id,
                access_token_encrypted="access",
                refresh_token_encrypted="refresh",
                expires_at="2026-08-30T00:00:00+00:00",
                scope="calendar",
            )
            connection = database.get_google_connection(session_id)
            assert connection is not None
            self.assertEqual(connection["access_token_encrypted"], "access")
            database.upsert_google_event_link(session_id, "source-1", "google-1")
            self.assertEqual(database.list_google_event_links(session_id)[0]["google_event_id"], "google-1")
            self.assertEqual(database.list_google_event_links(session_id)[0]["calendar_id"], "primary")
            database.set_google_calendar_id(session_id, "app-calendar")
            calendar_state = database.get_google_calendar_state(session_id)
            assert calendar_state is not None
            self.assertEqual(calendar_state["calendar_id"], "app-calendar")
            database.upsert_google_event_link(session_id, "source-1", "app-google-1", "app-calendar")
            self.assertEqual(
                database.list_google_event_links(session_id, "app-calendar")[0]["google_event_id"],
                "app-google-1",
            )
            database.delete_session(session_id)
            self.assertEqual(database.last_sync_runs(session_id), [])
            self.assertIsNone(database.get_google_connection(session_id))
            self.assertIsNone(database.get_google_calendar_state(session_id))
            self.assertEqual(database.list_google_event_links(session_id), [])
            database.close()

    def test_one_session_per_owner_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "server.db")
            first = database.get_or_create_user("subject-1", "Student 1")
            second = database.get_or_create_user("subject-2", "Student 2")

            first_session = database.create_session(first["id"], label="First")
            second_session = database.create_session(second["id"], label="Second")

            self.assertNotEqual(first_session, second_session)
            self.assertEqual(len(database.list_sessions(first["id"])), 1)
            self.assertEqual(len(database.list_sessions(second["id"])), 1)
            with self.assertRaises(OwnerSessionExistsError):
                database.create_session(first["id"], label="Duplicate")
            self.assertEqual([row["id"] for row in database.list_sessions(first["id"])], [first_session])

            second_writer = Database(Path(directory) / "server.db")
            try:
                second_writer.get_or_create_user("subject-3", "Student 3")
            finally:
                second_writer.close()

            database.delete_session(first_session)
            replacement_session = database.create_session(first["id"], label="Replacement")
            self.assertNotEqual(first_session, replacement_session)
            self.assertEqual([row["id"] for row in database.list_sessions(first["id"])], [replacement_session])
            database.close()

    def test_concurrent_session_creates_cannot_duplicate_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "server.db")
            user = database.get_or_create_user("subject", "Student")
            barrier = threading.Barrier(8)
            created: list[str] = []
            conflicts: list[OwnerSessionExistsError] = []
            unexpected: list[BaseException] = []
            results_lock = threading.Lock()

            def create() -> None:
                try:
                    barrier.wait()
                    session_id = database.create_session(user["id"])
                    with results_lock:
                        created.append(session_id)
                except OwnerSessionExistsError as error:
                    with results_lock:
                        conflicts.append(error)
                except BaseException as error:
                    with results_lock:
                        unexpected.append(error)

            threads = [threading.Thread(target=create) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(unexpected, [])
            self.assertEqual(len(created), 1)
            self.assertEqual(len(conflicts), 7)
            self.assertEqual([row["id"] for row in database.list_sessions(user["id"])], created)
            database.close()

    def test_session_owner_uniqueness_migration_keeps_oldest_and_cascades_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.db"
            connection = sqlite3.connect(path)
            connection.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oidc_sub TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending_login',
                phenikaa_user_id TEXT,
                token_encrypted TEXT,
                token_fingerprint TEXT,
                range_start TEXT,
                range_end TEXT,
                sync_interval_hours REAL,
                last_sync_at TEXT,
                last_sync_status TEXT,
                last_sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                ok INTEGER NOT NULL DEFAULT 0,
                refreshed_token INTEGER NOT NULL DEFAULT 0,
                events INTEGER,
                detail TEXT
            );
            CREATE TABLE google_connections (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                token_type TEXT NOT NULL DEFAULT 'Bearer',
                scope TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL,
                calendar_id TEXT,
                migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
                connected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT
            );
            CREATE TABLE google_calendar_state (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                calendar_id TEXT,
                migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE google_event_links (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                calendar_id TEXT NOT NULL DEFAULT 'primary',
                source_key TEXT NOT NULL,
                google_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, calendar_id, source_key)
            );
            INSERT INTO users (id, oidc_sub, display_name, created_at) VALUES (1, 'owner', '', 'now');
            INSERT INTO users (id, oidc_sub, display_name, created_at) VALUES (2, 'other', '', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('oldest', 1, '2026-01-01T00:00:00+00:00', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('newer', 1, '2026-01-02T00:00:00+00:00', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('tie-loser', 1, '2026-01-01T00:00:00+00:00', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('other-session', 2, '2026-01-03T00:00:00+00:00', 'now');
            INSERT INTO sync_runs (session_id, started_at, detail) VALUES ('oldest', 'now', 'keep');
            INSERT INTO sync_runs (session_id, started_at, detail) VALUES ('newer', 'now', 'delete');
            INSERT INTO google_connections (session_id, access_token_encrypted, refresh_token_encrypted, expires_at, connected_at, updated_at)
            VALUES ('oldest', 'access-old', 'refresh-old', 'later', 'now', 'now');
            INSERT INTO google_connections (session_id, access_token_encrypted, refresh_token_encrypted, expires_at, connected_at, updated_at)
            VALUES ('newer', 'access-new', 'refresh-new', 'later', 'now', 'now');
            INSERT INTO google_calendar_state (session_id, calendar_id, migration_state, updated_at)
            VALUES ('newer', 'app-new', 'app_calendar_ready', 'now');
            INSERT INTO google_event_links (session_id, calendar_id, source_key, google_event_id, updated_at)
            VALUES ('oldest', 'primary', 'keep', 'google-old', 'now');
            INSERT INTO google_event_links (session_id, calendar_id, source_key, google_event_id, updated_at)
            VALUES ('newer', 'primary', 'delete', 'google-new', 'now');
            """)
            connection.commit()
            connection.close()

            database = Database(path)
            self.assertEqual([row["id"] for row in database.list_sessions(1)], ["oldest"])
            self.assertEqual([row["id"] for row in database.list_sessions(2)], ["other-session"])
            self.assertEqual(database.last_sync_runs("oldest")[0]["detail"], "keep")
            self.assertEqual(database.last_sync_runs("newer"), [])
            self.assertIsNotNone(database.get_google_connection("oldest"))
            self.assertIsNone(database.get_google_connection("newer"))
            self.assertIsNone(database.get_google_calendar_state("newer"))
            self.assertEqual(database.list_google_event_links("oldest", "primary")[0]["source_key"], "keep")
            self.assertEqual(database.list_google_event_links("newer", "primary"), [])
            database.close()

            rerun = Database(path)
            with self.assertRaises(OwnerSessionExistsError):
                rerun.create_session(1)
            rerun.close()

    def test_google_calendar_migration_marks_legacy_links_pending_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.db"
            connection = sqlite3.connect(path)
            connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oidc_sub TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending_login',
                phenikaa_user_id TEXT,
                token_encrypted TEXT,
                token_fingerprint TEXT,
                range_start TEXT,
                range_end TEXT,
                sync_interval_hours REAL,
                last_sync_at TEXT,
                last_sync_status TEXT,
                last_sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                ok INTEGER NOT NULL DEFAULT 0,
                refreshed_token INTEGER NOT NULL DEFAULT 0,
                events INTEGER,
                detail TEXT
            );
            CREATE TABLE google_connections (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                token_type TEXT NOT NULL DEFAULT 'Bearer',
                scope TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL,
                connected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT
            );
            CREATE TABLE google_event_links (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source_key TEXT NOT NULL,
                google_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, source_key)
            );
            INSERT INTO users (id, oidc_sub, display_name, created_at) VALUES (1, 'subject', '', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('legacy', 1, 'now', 'now');
            INSERT INTO google_connections (
                session_id, access_token_encrypted, refresh_token_encrypted, expires_at, connected_at, updated_at
            ) VALUES ('legacy', 'access', 'refresh', 'later', 'now', 'now');
            INSERT INTO google_event_links (session_id, source_key, google_event_id, updated_at)
            VALUES ('legacy', 'source', 'primary-event', 'now');
            """)
            connection.commit()
            connection.close()
            database = Database(path)
            legacy = database.get_google_connection("legacy")
            assert legacy is not None
            self.assertIsNone(legacy["calendar_id"])
            self.assertEqual(legacy["migration_state"], "primary_cleanup_pending")
            state = database.get_google_calendar_state("legacy")
            assert state is not None
            self.assertEqual(state["migration_state"], "primary_cleanup_pending")
            links = database.list_google_event_links("legacy")
            self.assertEqual(links[0]["calendar_id"], "primary")
            database.close()
            again = Database(path)
            migrated = again.get_google_connection("legacy")
            assert migrated is not None
            self.assertEqual(migrated["migration_state"], "primary_cleanup_pending")
            again.close()

    def test_google_calendar_migration_preserves_disconnected_legacy_links_as_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.db"
            connection = sqlite3.connect(path)
            connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oidc_sub TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending_login',
                phenikaa_user_id TEXT,
                token_encrypted TEXT,
                token_fingerprint TEXT,
                range_start TEXT,
                range_end TEXT,
                sync_interval_hours REAL,
                last_sync_at TEXT,
                last_sync_status TEXT,
                last_sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                ok INTEGER NOT NULL DEFAULT 0,
                refreshed_token INTEGER NOT NULL DEFAULT 0,
                events INTEGER,
                detail TEXT
            );
            CREATE TABLE google_connections (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                token_type TEXT NOT NULL DEFAULT 'Bearer',
                scope TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL,
                connected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT
            );
            CREATE TABLE google_event_links (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source_key TEXT NOT NULL,
                google_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, source_key)
            );
            INSERT INTO users (id, oidc_sub, display_name, created_at) VALUES (1, 'subject', '', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('disconnected', 1, 'now', 'now');
            INSERT INTO google_event_links (session_id, source_key, google_event_id, updated_at)
            VALUES ('disconnected', 'source', 'primary-event', 'now');
            """)
            connection.commit()
            connection.close()
            database = Database(path)
            state = database.get_google_calendar_state("disconnected")
            assert state is not None
            self.assertEqual(state["migration_state"], "primary_cleanup_pending")
            self.assertIsNone(database.get_google_connection("disconnected"))
            self.assertEqual(database.list_google_event_links("disconnected", "primary")[0]["google_event_id"], "primary-event")
            database.upsert_google_connection(
                "disconnected",
                access_token_encrypted="access",
                refresh_token_encrypted="refresh",
                expires_at="2026-08-30T00:00:00+00:00",
            )
            reconnected = database.get_google_connection("disconnected")
            assert reconnected is not None
            self.assertEqual(reconnected["migration_state"], "primary_cleanup_pending")
            database.close()

    def test_google_calendar_migration_recovers_legacy_table_after_interrupted_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.db"
            connection = sqlite3.connect(path)
            connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oidc_sub TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending_login',
                phenikaa_user_id TEXT,
                token_encrypted TEXT,
                token_fingerprint TEXT,
                range_start TEXT,
                range_end TEXT,
                sync_interval_hours REAL,
                last_sync_at TEXT,
                last_sync_status TEXT,
                last_sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                ok INTEGER NOT NULL DEFAULT 0,
                refreshed_token INTEGER NOT NULL DEFAULT 0,
                events INTEGER,
                detail TEXT
            );
            CREATE TABLE google_connections (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                token_type TEXT NOT NULL DEFAULT 'Bearer',
                scope TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL,
                calendar_id TEXT,
                migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
                connected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT
            );
            CREATE TABLE google_calendar_state (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                calendar_id TEXT,
                migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE google_event_links (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                calendar_id TEXT NOT NULL DEFAULT 'primary',
                source_key TEXT NOT NULL,
                google_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, calendar_id, source_key)
            );
            CREATE TABLE google_event_links_legacy (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source_key TEXT NOT NULL,
                google_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, source_key)
            );
            INSERT INTO users (id, oidc_sub, display_name, created_at) VALUES (1, 'subject', '', 'now');
            INSERT INTO sessions (id, owner_user_id, created_at, updated_at) VALUES ('legacy', 1, 'now', 'now');
            INSERT INTO google_connections (
                session_id, access_token_encrypted, refresh_token_encrypted, expires_at,
                calendar_id, migration_state, connected_at, updated_at
            ) VALUES ('legacy', 'access', 'refresh', 'later', 'app-calendar', 'app_calendar_ready', 'now', 'now');
            INSERT INTO google_calendar_state (session_id, calendar_id, migration_state, updated_at)
            VALUES ('legacy', 'app-calendar', 'app_calendar_ready', 'now');
            INSERT INTO google_event_links (session_id, calendar_id, source_key, google_event_id, updated_at)
            VALUES ('legacy', 'app-calendar', 'source-app', 'app-event', 'now');
            INSERT INTO google_event_links_legacy (session_id, source_key, google_event_id, updated_at)
            VALUES ('legacy', 'source-primary', 'primary-event', 'later');
            """)
            connection.commit()
            connection.close()
            database = Database(path)
            links = database.list_google_event_links("legacy")
            self.assertEqual(
                [(row["calendar_id"], row["source_key"], row["google_event_id"]) for row in links],
                [("app-calendar", "source-app", "app-event"), ("primary", "source-primary", "primary-event")],
            )
            stored = database.get_google_connection("legacy")
            assert stored is not None
            self.assertEqual(stored["calendar_id"], "app-calendar")
            self.assertEqual(stored["migration_state"], "primary_cleanup_pending")
            state = database.get_google_calendar_state("legacy")
            assert state is not None
            self.assertEqual(state["migration_state"], "primary_cleanup_pending")
            database.close()

            rerun = Database(path)
            self.assertEqual(len(rerun.list_google_event_links("legacy", "primary")), 1)
            rerun_connection = rerun.get_google_connection("legacy")
            assert rerun_connection is not None
            self.assertEqual(rerun_connection["migration_state"], "primary_cleanup_pending")
            schema_connection = sqlite3.connect(path)
            legacy_table = schema_connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'google_event_links_legacy'"
            ).fetchone()
            schema_connection.close()
            self.assertIsNone(legacy_table)
            rerun.close()

    def test_google_calendar_migration_reasserts_pending_when_primary_links_reappear(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.db"
            database = Database(path)
            user = database.get_or_create_user("subject")
            session_id = database.create_session(user["id"])
            database.upsert_google_connection(
                session_id,
                access_token_encrypted="access",
                refresh_token_encrypted="refresh",
                expires_at="2026-08-30T00:00:00+00:00",
            )
            database.set_google_calendar_id(session_id, "app-calendar")
            database.upsert_google_event_link(session_id, "source-primary", "primary-event", "primary")
            database.set_google_migration_state(session_id, "app_calendar_ready")
            database.close()

            migrated = Database(path)
            connection = migrated.get_google_connection(session_id)
            assert connection is not None
            self.assertEqual(connection["migration_state"], "primary_cleanup_pending")
            state = migrated.get_google_calendar_state(session_id)
            assert state is not None
            self.assertEqual(state["migration_state"], "primary_cleanup_pending")
            migrated.close()

    def test_google_calendar_migration_sanitizes_primary_dedicated_calendar_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.db"
            database = Database(path)
            user = database.get_or_create_user("subject")
            session_id = database.create_session(user["id"])
            database.upsert_google_connection(
                session_id,
                access_token_encrypted="access",
                refresh_token_encrypted="refresh",
                expires_at="2026-08-30T00:00:00+00:00",
            )
            database.close()
            connection = sqlite3.connect(path)
            connection.execute("UPDATE google_connections SET calendar_id = 'primary' WHERE session_id = ?", (session_id,))
            connection.execute("UPDATE google_calendar_state SET calendar_id = 'primary' WHERE session_id = ?", (session_id,))
            connection.commit()
            connection.close()

            migrated = Database(path)
            stored = migrated.get_google_connection(session_id)
            assert stored is not None
            self.assertIsNone(stored["calendar_id"])
            state = migrated.get_google_calendar_state(session_id)
            assert state is not None
            self.assertIsNone(state["calendar_id"])
            with self.assertRaisesRegex(ValueError, "cannot be primary"):
                migrated.set_google_calendar_id(session_id, "primary")
            migrated.close()


if __name__ == "__main__":
    unittest.main()
