"""Daily calendar synchronization and profile-backed token refresh."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from phenikaa_exporter import fetch_calendar, write_ics
from phenikaa_login import LoginTimeout

from server.config import ServerConfig, academic_year_range
from server.crypto import TokenVault, token_fingerprint
from server.db import Database, STATUS_ACTIVE, STATUS_NEEDS_HUMAN
from server.refresh import ProfileLocks, silent_refresh


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    events: int
    refreshed: bool
    detail: str


class SyncEngine:
    """Synchronizes sessions serially while exposing testable single-cycle APIs."""

    def __init__(
        self,
        config: ServerConfig,
        database: Database,
        vault: TokenVault,
        *,
        locks: ProfileLocks | None = None,
        fetcher: Callable[..., list[dict[str, Any]]] = fetch_calendar,
        refresher: Callable[..., dict[str, Any]] = silent_refresh,
    ) -> None:
        self.config = config
        self.database = database
        self.vault = vault
        self.locks = locks or ProfileLocks()
        self.fetcher = fetcher
        self.refresher = refresher
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._forced: set[str] = set()
        self._forced_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def request_sync(self, session_id: str) -> None:
        with self._forced_lock:
            self._forced.add(session_id)
        self._wake.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, name="calendar-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            self.sync_due()
            self._wake.wait(timeout=60)
            self._wake.clear()

    def sync_due(self, *, now: datetime | None = None) -> list[SyncResult]:
        current = now or datetime.now(timezone.utc)
        with self._forced_lock:
            forced = set(self._forced)
            self._forced.clear()
        results: list[SyncResult] = []
        for session in self.database.list_sessions():
            if session["status"] != STATUS_ACTIVE and session["id"] not in forced:
                continue
            interval = float(session.get("sync_interval_hours") or self.config.sync_interval_hours)
            last_sync = session.get("last_sync_at")
            due = not last_sync or current - datetime.fromisoformat(str(last_sync)) >= timedelta(hours=interval)
            if session["id"] in forced or due:
                results.append(self.sync_session(session))
        return results

    def sync_session(self, session: dict[str, Any]) -> SyncResult:
        session_id = str(session["id"])
        with self.locks.for_profile(session_id):
            current = self.database.get_session(session_id)
            if current is None:
                return SyncResult(False, 0, False, "session was deleted")
            return self._sync_locked(current)

    def _sync_locked(self, session: dict[str, Any]) -> SyncResult:
        session_id = str(session["id"])
        run_id = self.database.start_sync_run(session_id)
        refreshed = False
        try:
            encrypted = session.get("token_encrypted")
            user_id = session.get("phenikaa_user_id")
            if not encrypted or not user_id:
                raise LoginTimeout("session requires an interactive login")
            auth = {"userId": str(user_id), "tokenJWT": self.vault.decrypt(str(encrypted))}
            start, end = self._date_range(session)
            try:
                events = self.fetcher(auth, start, end)
            except PermissionError:
                profile_dir = self.config.profiles_dir / session_id
                auth = self.refresher(
                    profile_dir,
                    timeout=self.config.refresh_timeout,
                    no_sandbox=self.config.browser_no_sandbox,
                )
                token = str(auth["tokenJWT"])
                self.database.update_session_credentials(
                    session_id,
                    str(auth["userId"]),
                    self.vault.encrypt(token),
                    str(token_fingerprint(token)),
                )
                refreshed = True
                try:
                    events = self.fetcher(auth, start, end)
                except PermissionError as error:
                    raise LoginTimeout("silent refresh did not restore the Phenikaa session") from error
            self._write_outputs(session_id, events)
            detail = f"saved {len(events)} events"
            self.database.mark_synced(session_id, ok=True, detail=detail)
            self.database.finish_sync_run(run_id, ok=True, refreshed_token=refreshed, events=len(events), detail=detail)
            return SyncResult(True, len(events), refreshed, detail)
        except LoginTimeout as error:
            detail = str(error)
            self.database.update_session_status(session_id, STATUS_NEEDS_HUMAN, detail)
            self.database.finish_sync_run(run_id, ok=False, refreshed_token=refreshed, detail=detail)
            return SyncResult(False, 0, refreshed, detail)
        except Exception as error:
            detail = f"{error.__class__.__name__}: {str(error)[:160]}"
            self.database.mark_synced(session_id, ok=False, detail=detail)
            self.database.finish_sync_run(run_id, ok=False, refreshed_token=refreshed, detail=detail)
            return SyncResult(False, 0, refreshed, detail)

    def _date_range(self, session: dict[str, Any]) -> tuple[date, date]:
        default_start, default_end = academic_year_range()
        start = date.fromisoformat(str(session.get("range_start") or default_start.isoformat()))
        end = date.fromisoformat(str(session.get("range_end") or default_end.isoformat()))
        if start > end:
            raise ValueError("session start date must not be after end date")
        return start, end

    def _write_outputs(self, session_id: str, events: list[dict[str, Any]]) -> None:
        output = self.config.exports_dir / session_id
        output.mkdir(parents=True, exist_ok=True)
        temporary = output / "calendar.json.tmp"
        temporary.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output / "calendar.json")
        temporary_ics = output / "calendar.ics.tmp"
        write_ics(temporary_ics, events, calendar_name="Phenikaa Learning Calendar")
        temporary_ics.replace(output / "calendar.ics")
