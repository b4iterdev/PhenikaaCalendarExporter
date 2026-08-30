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
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS google_event_links (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    google_event_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, source_key)
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return uuid.uuid4().hex


class Database:
    """Thread-safe SQLite store shared by the web and scheduler threads."""

    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _write(self, sql: str, params: tuple[object, ...] = ()) -> int | None:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor.lastrowid

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
        self._write(
            "INSERT INTO sessions (id, owner_user_id, label, range_start, range_end,"
            " sync_interval_hours, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, owner_user_id, label, range_start, range_end, sync_interval_hours,
             STATUS_PENDING_LOGIN, now, now),
        )
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
        self._write(
            "INSERT INTO google_connections (session_id, access_token_encrypted, refresh_token_encrypted,"
            " token_type, scope, expires_at, connected_at, updated_at, last_error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)"
            " ON CONFLICT(session_id) DO UPDATE SET access_token_encrypted = excluded.access_token_encrypted,"
            " refresh_token_encrypted = excluded.refresh_token_encrypted, token_type = excluded.token_type,"
            " scope = excluded.scope, expires_at = excluded.expires_at, updated_at = excluded.updated_at, last_error = NULL",
            (session_id, access_token_encrypted, refresh_token_encrypted, token_type, scope, expires_at, now, now),
        )

    def get_google_connection(self, session_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM google_connections WHERE session_id = ?", (session_id,))
        return dict(row) if row else None

    def set_google_connection_error(self, session_id: str, error: str | None) -> None:
        self._write(
            "UPDATE google_connections SET last_error = ?, updated_at = ? WHERE session_id = ?",
            (error, utc_now_iso(), session_id),
        )

    def delete_google_connection(self, session_id: str) -> None:
        self._write("DELETE FROM google_connections WHERE session_id = ?", (session_id,))

    def list_google_event_links(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM google_event_links WHERE session_id = ? ORDER BY source_key", (session_id,)
        )
        return [dict(row) for row in rows]

    def upsert_google_event_link(self, session_id: str, source_key: str, google_event_id: str) -> None:
        self._write(
            "INSERT INTO google_event_links (session_id, source_key, google_event_id, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(session_id, source_key) DO UPDATE SET google_event_id = excluded.google_event_id,"
            " updated_at = excluded.updated_at",
            (session_id, source_key, google_event_id, utc_now_iso()),
        )

    def delete_google_event_link(self, session_id: str, source_key: str) -> None:
        self._write(
            "DELETE FROM google_event_links WHERE session_id = ? AND source_key = ?", (session_id, source_key)
        )
