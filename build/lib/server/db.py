"""SQLite persistence for server users, Phenikaa sessions, and sync history."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_PENDING_LOGIN = "pending_login"
STATUS_ACTIVE = "active"
STATUS_NEEDS_HUMAN = "needs_human"
STATUS_DISABLED = "disabled"
ALL_STATUSES = (STATUS_PENDING_LOGIN, STATUS_ACTIVE, STATUS_NEEDS_HUMAN, STATUS_DISABLED)
SESSION_OWNER_UNIQUE_INDEX = "idx_sessions_owner_user_id_unique"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oidc_sub TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
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
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    refreshed_token INTEGER NOT NULL DEFAULT 0,
    events INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS google_connections (
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
CREATE TABLE IF NOT EXISTS google_calendar_state (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    calendar_id TEXT,
    migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_event_links (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL DEFAULT 'primary',
    source_key TEXT NOT NULL,
    google_event_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, calendar_id, source_key)
);
"""

GOOGLE_APP_CALENDAR_READY = "app_calendar_ready"
GOOGLE_PRIMARY_CLEANUP_PENDING = "primary_cleanup_pending"
GOOGLE_PRIMARY_CALENDAR_ID = "primary"


def _dedicated_google_calendar_id(calendar_id: object) -> str | None:
    value = str(calendar_id or "").strip()
    if not value or value == GOOGLE_PRIMARY_CALENDAR_ID:
        return None
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return uuid.uuid4().hex


class OwnerSessionExistsError(Exception):
    def __init__(self, owner_user_id: int) -> None:
        super().__init__(f"user {owner_user_id} already has a Phenikaa session")
        self.owner_user_id: int = owner_user_id


def _is_owner_session_unique_error(error: sqlite3.IntegrityError) -> bool:
    return "UNIQUE constraint failed: sessions.owner_user_id" in str(error)


class Database:
    """Thread-safe SQLite store shared by the web and scheduler threads."""

    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._migrate_unique_session_owner()
        self._migrate_google_calendar_columns()

    def _migrate_unique_session_owner(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "DELETE FROM sessions WHERE id IN ("
                    "SELECT newer.id FROM sessions AS newer WHERE EXISTS ("
                    "SELECT 1 FROM sessions AS older "
                    "WHERE older.owner_user_id = newer.owner_user_id "
                    "AND (older.created_at < newer.created_at "
                    "OR (older.created_at = newer.created_at AND older.id < newer.id))))"
                )
                self._conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {SESSION_OWNER_UNIQUE_INDEX} ON sessions(owner_user_id)"
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _migrate_google_calendar_columns(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                connection_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(google_connections)")}
                if "calendar_id" not in connection_columns:
                    self._conn.execute("ALTER TABLE google_connections ADD COLUMN calendar_id TEXT")
                if "migration_state" not in connection_columns:
                    self._conn.execute(
                        "ALTER TABLE google_connections ADD COLUMN migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready'"
                    )

                tables = self._table_names()
                link_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(google_event_links)")}
                if "google_event_links" in tables and "calendar_id" not in link_columns:
                    self._conn.execute("ALTER TABLE google_event_links RENAME TO google_event_links_legacy")
                    tables = self._table_names()
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS google_event_links ("
                    "session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,"
                    "calendar_id TEXT NOT NULL DEFAULT 'primary',"
                    "source_key TEXT NOT NULL,"
                    "google_event_id TEXT NOT NULL,"
                    "updated_at TEXT NOT NULL,"
                    "PRIMARY KEY (session_id, calendar_id, source_key))"
                )
                if "google_event_links_legacy" in tables:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO google_event_links "
                        "(session_id, calendar_id, source_key, google_event_id, updated_at) "
                        "SELECT session_id, 'primary', source_key, google_event_id, updated_at "
                        "FROM google_event_links_legacy"
                    )
                    self._conn.execute("DROP TABLE google_event_links_legacy")

                self._conn.execute("UPDATE google_connections SET calendar_id = NULL WHERE calendar_id = ?", (GOOGLE_PRIMARY_CALENDAR_ID,))
                self._conn.execute("UPDATE google_calendar_state SET calendar_id = NULL WHERE calendar_id = ?", (GOOGLE_PRIMARY_CALENDAR_ID,))
                self._conn.execute(
                    "INSERT OR IGNORE INTO google_calendar_state (session_id, calendar_id, migration_state, updated_at) "
                    "SELECT session_id, calendar_id, migration_state, updated_at FROM google_connections"
                )
                self._backfill_primary_cleanup_pending()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _table_names(self) -> set[str]:
        return {
            str(row[0])
            for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    def _backfill_primary_cleanup_pending(self) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO google_calendar_state (session_id, calendar_id, migration_state, updated_at) "
            "SELECT google_event_links.session_id, NULL, ?, MAX(google_event_links.updated_at) "
            "FROM google_event_links JOIN sessions ON sessions.id = google_event_links.session_id "
            "WHERE google_event_links.calendar_id = 'primary' GROUP BY google_event_links.session_id",
            (GOOGLE_PRIMARY_CLEANUP_PENDING,),
        )
        self._conn.execute(
            "UPDATE google_calendar_state SET migration_state = ?, updated_at = "
            "COALESCE((SELECT MAX(updated_at) FROM google_event_links "
            "WHERE google_event_links.session_id = google_calendar_state.session_id "
            "AND google_event_links.calendar_id = 'primary'), updated_at) "
            "WHERE session_id IN (SELECT DISTINCT session_id FROM google_event_links WHERE calendar_id = 'primary')",
            (GOOGLE_PRIMARY_CLEANUP_PENDING,),
        )
        self._conn.execute(
            "UPDATE google_connections SET migration_state = ?, updated_at = "
            "COALESCE((SELECT updated_at FROM google_calendar_state "
            "WHERE google_calendar_state.session_id = google_connections.session_id), updated_at) "
            "WHERE session_id IN (SELECT DISTINCT session_id FROM google_event_links WHERE calendar_id = 'primary')",
            (GOOGLE_PRIMARY_CLEANUP_PENDING,),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _write(self, sql: str, params: tuple[object, ...] = ()) -> int | None:
        with self._lock:
            try:
                cursor = self._conn.execute(sql, params)
                self._conn.commit()
                return cursor.lastrowid
            except Exception:
                self._conn.rollback()
                raise

    def _fetchone(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # -- users ---------------------------------------------------------

    def get_or_create_user(self, oidc_sub: str, display_name: str = "") -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE oidc_sub = ?", (oidc_sub,)).fetchone()
            if row:
                if display_name and row["display_name"] != display_name:
                    self._conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, row["id"]))
                    self._conn.commit()
                    row = self._conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                return dict(row)
            cursor = self._conn.execute(
                "INSERT INTO users (oidc_sub, display_name, created_at) VALUES (?, ?, ?)",
                (oidc_sub, display_name, utc_now_iso()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
            if row is None:
                raise RuntimeError("failed to create user")
            return dict(row)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return dict(row) if row else None

    def delete_user(self, user_id: int) -> None:
        self._write("DELETE FROM users WHERE id = ?", (user_id,))

    # -- sessions ------------------------------------------------------

    def create_session(
        self,
        owner_user_id: int,
        *,
        label: str = "",
        range_start: str | None = None,
        range_end: str | None = None,
        sync_interval_hours: float | None = None,
    ) -> str:
        session_id = new_session_id()
        now = utc_now_iso()
        try:
            self._write(
                "INSERT INTO sessions (id, owner_user_id, label, range_start, range_end,"
                " sync_interval_hours, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, owner_user_id, label, range_start, range_end, sync_interval_hours,
                 STATUS_PENDING_LOGIN, now, now),
            )
        except sqlite3.IntegrityError as error:
            if _is_owner_session_unique_error(error):
                raise OwnerSessionExistsError(owner_user_id) from error
            raise
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return dict(row) if row else None

    def list_sessions(self, owner_user_id: int | None = None) -> list[dict[str, Any]]:
        if owner_user_id is None:
            rows = self._fetchall("SELECT * FROM sessions ORDER BY created_at")
        else:
            rows = self._fetchall(
                "SELECT * FROM sessions WHERE owner_user_id = ? ORDER BY created_at", (owner_user_id,)
            )
        return [dict(row) for row in rows]

    def update_session_credentials(
        self, session_id: str, phenikaa_user_id: str, token_encrypted: str, fingerprint: str
    ) -> None:
        self._write(
            "UPDATE sessions SET phenikaa_user_id = ?, token_encrypted = ?, token_fingerprint = ?,"
            " status = ?, last_sync_error = NULL, updated_at = ? WHERE id = ?",
            (phenikaa_user_id, token_encrypted, fingerprint, STATUS_ACTIVE, utc_now_iso(), session_id),
        )

    def update_session_status(self, session_id: str, status: str, error: str | None = None) -> None:
        if status not in ALL_STATUSES:
            raise ValueError(f"unknown session status: {status}")
        self._write(
            "UPDATE sessions SET status = ?, last_sync_error = ?, updated_at = ? WHERE id = ?",
            (status, error, utc_now_iso(), session_id),
        )

    def update_session_range(
        self,
        session_id: str,
        *,
        range_start: str | None = None,
        range_end: str | None = None,
        sync_interval_hours: float | None = None,
    ) -> None:
        current = self.get_session(session_id)
        if not current:
            raise KeyError(f"no such session: {session_id}")
        self._write(
            "UPDATE sessions SET range_start = ?, range_end = ?, sync_interval_hours = ?, updated_at = ?"
            " WHERE id = ?",
            (
                range_start if range_start is not None else current["range_start"],
                range_end if range_end is not None else current["range_end"],
                sync_interval_hours if sync_interval_hours is not None else current["sync_interval_hours"],
                utc_now_iso(),
                session_id,
            ),
        )

    def mark_synced(self, session_id: str, *, ok: bool, detail: str = "") -> None:
        status = STATUS_ACTIVE if ok else STATUS_NEEDS_HUMAN if "login" in detail.lower() else STATUS_ACTIVE
        error = None if ok else detail
        self._write(
            "UPDATE sessions SET last_sync_at = ?, last_sync_status = ?, last_sync_error = ?,"
            " status = ?, updated_at = ? WHERE id = ?",
            (utc_now_iso(), "ok" if ok else "error", error, status, utc_now_iso(), session_id),
        )

    def delete_session(self, session_id: str) -> None:
        self._write("DELETE FROM sessions WHERE id = ?", (session_id,))

    # -- sync runs -------------------------------------------------------

    def start_sync_run(self, session_id: str) -> int:
        row_id = self._write(
            "INSERT INTO sync_runs (session_id, started_at) VALUES (?, ?)",
            (session_id, utc_now_iso()),
        )
        if row_id is None:
            raise RuntimeError("failed to create sync run")
        return row_id

    def finish_sync_run(
        self, run_id: int, *, ok: bool, refreshed_token: bool = False, events: int | None = None,
        detail: str = "",
    ) -> None:
        self._write(
            "UPDATE sync_runs SET finished_at = ?, ok = ?, refreshed_token = ?, events = ?, detail = ?"
            " WHERE id = ?",
            (utc_now_iso(), int(ok), int(refreshed_token), events, detail, run_id),
        )

    def last_sync_runs(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM sync_runs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return [dict(row) for row in rows]

    def upsert_google_connection(
        self,
        session_id: str,
        *,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
        expires_at: str,
        token_type: str = "Bearer",
        scope: str = "",
    ) -> None:
        now = utc_now_iso()
        with self._lock:
            state = self._conn.execute(
                "SELECT calendar_id, migration_state FROM google_calendar_state WHERE session_id = ?", (session_id,)
            ).fetchone()
            calendar_id = None if state is None else _dedicated_google_calendar_id(state["calendar_id"])
            migration_state = str(state["migration_state"] if state else GOOGLE_APP_CALENDAR_READY)
            self._conn.execute(
                "INSERT INTO google_calendar_state (session_id, calendar_id, migration_state, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at",
                (session_id, calendar_id, migration_state, now),
            )
            self._conn.execute(
                "INSERT INTO google_connections (session_id, access_token_encrypted, refresh_token_encrypted,"
                " token_type, scope, expires_at, calendar_id, migration_state, connected_at, updated_at, last_error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)"
                " ON CONFLICT(session_id) DO UPDATE SET access_token_encrypted = excluded.access_token_encrypted,"
                " refresh_token_encrypted = excluded.refresh_token_encrypted, token_type = excluded.token_type,"
                " scope = excluded.scope, expires_at = excluded.expires_at, calendar_id = excluded.calendar_id,"
                " migration_state = excluded.migration_state, updated_at = excluded.updated_at, last_error = NULL",
                (
                    session_id,
                    access_token_encrypted,
                    refresh_token_encrypted,
                    token_type,
                    scope,
                    expires_at,
                    calendar_id,
                    migration_state,
                    now,
                    now,
                ),
            )
            self._conn.commit()

    def get_google_connection(self, session_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT google_connections.*, google_calendar_state.calendar_id AS state_calendar_id, "
            "google_calendar_state.migration_state AS state_migration_state "
            "FROM google_connections LEFT JOIN google_calendar_state "
            "ON google_calendar_state.session_id = google_connections.session_id "
            "WHERE google_connections.session_id = ?",
            (session_id,),
        )
        if row is None:
            return None
        connection = dict(row)
        if connection.pop("state_migration_state") is not None:
            connection["calendar_id"] = connection.pop("state_calendar_id")
            connection["migration_state"] = row["state_migration_state"]
        else:
            connection.pop("state_calendar_id")
        return connection

    def set_google_connection_error(self, session_id: str, error: str | None) -> None:
        self._write(
            "UPDATE google_connections SET last_error = ?, updated_at = ? WHERE session_id = ?",
            (error, utc_now_iso(), session_id),
        )

    def delete_google_connection(self, session_id: str) -> None:
        self._write("DELETE FROM google_connections WHERE session_id = ?", (session_id,))

    def get_google_calendar_state(self, session_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM google_calendar_state WHERE session_id = ?", (session_id,))
        return dict(row) if row else None

    def set_google_calendar_id(self, session_id: str, calendar_id: str) -> None:
        dedicated_calendar_id = _dedicated_google_calendar_id(calendar_id)
        if dedicated_calendar_id is None:
            raise ValueError("Google dedicated calendar ID cannot be primary")
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO google_calendar_state (session_id, calendar_id, migration_state, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET calendar_id = excluded.calendar_id, updated_at = excluded.updated_at",
                (session_id, dedicated_calendar_id, GOOGLE_APP_CALENDAR_READY, now),
            )
            self._conn.execute(
                "UPDATE google_connections SET calendar_id = ?, updated_at = ? WHERE session_id = ?",
                (dedicated_calendar_id, now, session_id),
            )
            self._conn.commit()

    def set_google_migration_state(self, session_id: str, migration_state: str) -> None:
        if migration_state not in (GOOGLE_APP_CALENDAR_READY, GOOGLE_PRIMARY_CLEANUP_PENDING):
            raise ValueError(f"unknown Google migration state: {migration_state}")
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO google_calendar_state (session_id, migration_state, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET migration_state = excluded.migration_state,"
                " updated_at = excluded.updated_at",
                (session_id, migration_state, now),
            )
            self._conn.execute(
                "UPDATE google_connections SET migration_state = ?, updated_at = ? WHERE session_id = ?",
                (migration_state, now, session_id),
            )
            self._conn.commit()

    def list_google_event_links(self, session_id: str, calendar_id: str | None = None) -> list[dict[str, Any]]:
        if calendar_id is None:
            rows = self._fetchall(
                "SELECT * FROM google_event_links WHERE session_id = ? ORDER BY calendar_id, source_key", (session_id,)
            )
            return [dict(row) for row in rows]
        rows = self._fetchall(
            "SELECT * FROM google_event_links WHERE session_id = ? AND calendar_id = ? ORDER BY source_key",
            (session_id, calendar_id),
        )
        return [dict(row) for row in rows]

    def upsert_google_event_link(
        self, session_id: str, source_key: str, google_event_id: str, calendar_id: str = "primary"
    ) -> None:
        self._write(
            "INSERT INTO google_event_links (session_id, calendar_id, source_key, google_event_id, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id, calendar_id, source_key) DO UPDATE SET google_event_id = excluded.google_event_id,"
            " updated_at = excluded.updated_at",
            (session_id, calendar_id, source_key, google_event_id, utc_now_iso()),
        )

    def delete_google_event_link(self, session_id: str, source_key: str, calendar_id: str = "primary") -> None:
        self._write(
            "DELETE FROM google_event_links WHERE session_id = ? AND calendar_id = ? AND source_key = ?",
            (session_id, calendar_id, source_key),
        )

    def delete_google_event_links_for_calendar(self, session_id: str, calendar_id: str) -> None:
        self._write(
            "DELETE FROM google_event_links WHERE session_id = ? AND calendar_id = ?",
            (session_id, calendar_id),
        )
