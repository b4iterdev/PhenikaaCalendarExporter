from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Callable, Optional

from phenikaa_exporter import TIMEZONE, clean_html_breaks, event_datetime, normalize_events

from server.crypto import TokenVault
from server.db import Database

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
APP_PRIVATE_KEY = "phenikaaCalendarSourceKey"


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class GoogleSyncResult:
    attempted: bool
    ok: bool
    created: int = 0
    updated: int = 0
    deleted: int = 0
    detail: str = ""


@dataclass(frozen=True)
class GoogleHttpResponse:
    status: int
    body: bytes


HttpRequest = Callable[[str, str, dict[str, str], Optional[bytes], float], GoogleHttpResponse]
Clock = Callable[[], datetime]


class GoogleCalendarError(RuntimeError):
    pass


def default_http_request(method: str, url: str, headers: dict[str, str], body: Optional[bytes], timeout: float) -> GoogleHttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return GoogleHttpResponse(response.status, response.read())
    except urllib.error.HTTPError as error:
        return GoogleHttpResponse(error.code, error.read())


def authorization_url(config: GoogleOAuthConfig, state: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    })
    return AUTH_URL + "?" + query


class GoogleCalendarService:
    def __init__(
        self,
        config: GoogleOAuthConfig,
        database: Database,
        vault: TokenVault,
        *,
        http_request: HttpRequest = default_http_request,
        clock: Optional[Clock] = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.database = database
        self.vault = vault
        self.http_request = http_request
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout = timeout

    def authorization_url(self, state: str) -> str:
        return authorization_url(self.config, state)

    def exchange_code(self, session_id: str, code: str) -> None:
        token = self._token_request({
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
        })
        self._store_tokens(session_id, token, existing_refresh_token=self._existing_refresh_token(session_id))

    def disconnect(self, session_id: str) -> None:
        connection = self.database.get_google_connection(session_id)
        if connection is None:
            return
        token = self._revocation_token(connection)
        response = self.http_request(
            "POST",
            REVOKE_URL,
            {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            urllib.parse.urlencode({"token": token}).encode("ascii"),
            self.timeout,
        )
        if response.status not in (200, 400):
            raise GoogleCalendarError(self._error_message(response.status, self._json(response)))
        self.database.delete_google_connection(session_id)

    def sync_session(self, session_id: str, events: list[dict[str, Any]]) -> GoogleSyncResult:
        connection = self.database.get_google_connection(session_id)
        if connection is None:
            return GoogleSyncResult(attempted=False, ok=True, detail="Google Calendar is not connected")
        try:
            access_token = self._valid_access_token(session_id, connection)
            result = self._reconcile(session_id, access_token, events)
            self.database.set_google_connection_error(session_id, None)
            return result
        except Exception as error:
            detail = f"Google Calendar sync failed: {error.__class__.__name__}: {str(error)[:160]}"
            self.database.set_google_connection_error(session_id, detail)
            return GoogleSyncResult(attempted=True, ok=False, detail=detail)

    def _valid_access_token(self, session_id: str, connection: dict[str, Any]) -> str:
        expires_at = datetime.fromisoformat(str(connection["expires_at"]))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at - self.clock() > timedelta(seconds=60):
            return self.vault.decrypt(str(connection["access_token_encrypted"]))
        refresh_token = self.vault.decrypt(str(connection["refresh_token_encrypted"]))
        token = self._token_request({
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        self._store_tokens(session_id, token, existing_refresh_token=refresh_token)
        return str(token["access_token"])

    def _existing_refresh_token(self, session_id: str) -> Optional[str]:
        connection = self.database.get_google_connection(session_id)
        if connection is None:
            return None
        return self.vault.decrypt(str(connection["refresh_token_encrypted"]))

    def _revocation_token(self, connection: dict[str, Any]) -> str:
        refresh_token_encrypted = str(connection.get("refresh_token_encrypted") or "")
        if refresh_token_encrypted:
            return self.vault.decrypt(refresh_token_encrypted)
        return self.vault.decrypt(str(connection["access_token_encrypted"]))

    def _store_tokens(self, session_id: str, token: dict[str, Any], *, existing_refresh_token: Optional[str]) -> None:
        access_token = str(token.get("access_token") or "")
        refresh_token = str(token.get("refresh_token") or existing_refresh_token or "")
        if not access_token or not refresh_token:
            raise GoogleCalendarError("Google did not return the required access and refresh tokens")
        expires_in = int(token.get("expires_in") or 3600)
        expires_at = (self.clock() + timedelta(seconds=max(0, expires_in))).isoformat()
        self.database.upsert_google_connection(
            session_id,
            access_token_encrypted=self.vault.encrypt(access_token),
            refresh_token_encrypted=self.vault.encrypt(refresh_token),
            token_type=str(token.get("token_type") or "Bearer"),
            scope=str(token.get("scope") or SCOPE),
            expires_at=expires_at,
        )

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        body = urllib.parse.urlencode(data).encode("ascii")
        response = self.http_request("POST", TOKEN_URL, {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }, body, self.timeout)
        payload = self._json(response)
        if response.status < 200 or response.status >= 300:
            raise GoogleCalendarError(str(payload.get("error_description") or payload.get("error") or response.status))
        return payload

    def _reconcile(self, session_id: str, access_token: str, events: list[dict[str, Any]]) -> GoogleSyncResult:
        desired = {source_key(event): google_event_body(event) for event in normalize_events(events)}
        links = {str(row["source_key"]): str(row["google_event_id"]) for row in self.database.list_google_event_links(session_id)}
        created = updated = deleted = 0
        for key, body in desired.items():
            body["extendedProperties"] = {"private": {APP_PRIVATE_KEY: key}}
            if key in links:
                status, payload = self._calendar_request("PUT", f"{EVENTS_URL}/{urllib.parse.quote(links[key], safe='')}", access_token, body)
                if status == 404:
                    event_id = self._insert_event(access_token, body)
                    self.database.upsert_google_event_link(session_id, key, event_id)
                    created += 1
                elif 200 <= status < 300:
                    updated += 1
                else:
                    raise GoogleCalendarError(self._error_message(status, payload))
            else:
                event_id = self._insert_event(access_token, body)
                self.database.upsert_google_event_link(session_id, key, event_id)
                created += 1
        for key, event_id in links.items():
            if key not in desired:
                status, payload = self._calendar_request("DELETE", f"{EVENTS_URL}/{urllib.parse.quote(event_id, safe='')}", access_token, None)
                if status not in (200, 204, 404, 410):
                    raise GoogleCalendarError(self._error_message(status, payload))
                self.database.delete_google_event_link(session_id, key)
                deleted += 1
        detail = f"Google Calendar sync created {created}, updated {updated}, deleted {deleted}"
        return GoogleSyncResult(True, True, created, updated, deleted, detail)

    def _insert_event(self, access_token: str, body: dict[str, Any]) -> str:
        status, payload = self._calendar_request("POST", EVENTS_URL, access_token, body)
        if status < 200 or status >= 300:
            raise GoogleCalendarError(self._error_message(status, payload))
        event_id = str(payload.get("id") or "")
        if not event_id:
            raise GoogleCalendarError("Google event insert response did not include an id")
        return event_id

    def _calendar_request(
        self, method: str, url: str, access_token: str, body: Optional[dict[str, Any]]
    ) -> tuple[int, dict[str, Any]]:
        payload = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Authorization": "Bearer " + access_token, "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        response = self.http_request(method, url, headers, payload, self.timeout)
        return response.status, self._json(response)

    def _json(self, response: GoogleHttpResponse) -> dict[str, Any]:
        if not response.body:
            return {}
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GoogleCalendarError(f"Google returned invalid JSON with HTTP {response.status}") from error
        if not isinstance(payload, dict):
            raise GoogleCalendarError(f"Google returned an unexpected JSON payload with HTTP {response.status}")
        return payload

    def _error_message(self, status: int, payload: dict[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or status)
        return str(error or status)


def source_key(event: dict[str, Any]) -> str:
    identity = _source_identity(event)
    prefix = "phenikaa:id:" if identity[0] else "phenikaa:derived:"
    digest = sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return prefix + digest


def _source_identity(event: dict[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    section = clean_html_breaks(event.get("TENLOPHOCPHAN"))
    if not section:
        section = clean_html_breaks(event.get("DANGKY_LOPHOCPHAN_TEN"))
    return (
        clean_html_breaks(event.get("ID")),
        str(event.get("NGAYHOC") or ""),
        str(event.get("GIOBATDAU") or ""),
        str(event.get("PHUTBATDAU") or ""),
        clean_html_breaks(event.get("TENHOCPHAN")),
        section,
        str(event.get("GIOKETTHUC") or ""),
        str(event.get("PHUTKETTHUC") or ""),
    )


def google_event_body(event: dict[str, Any]) -> dict[str, Any]:
    start = event_datetime(event)
    end = event_datetime(event, end=True)
    return {
        "summary": _summary(event),
        "location": clean_html_breaks(event.get("TENPHONGHOC") or event.get("PHONGHOC_TEN")),
        "description": _description(event),
        "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
    }


def _summary(event: dict[str, Any]) -> str:
    prefix = "Exam: " if event.get("PHANLOAI") == "LICHTHI" else ""
    return prefix + clean_html_breaks(event.get("TENHOCPHAN"))


def _description(event: dict[str, Any]) -> str:
    lines = []
    section = clean_html_breaks(event.get("TENLOPHOCPHAN") or event.get("DANGKY_LOPHOCPHAN_TEN"))
    lecturer = clean_html_breaks(event.get("GIANGVIEN"))
    if section:
        lines.append("Class: " + section)
    if lecturer:
        lines.append("Lecturer: " + lecturer)
    if event.get("TIETBATDAU") is not None:
        lines.append(f"Periods: {int(float(event.get('TIETBATDAU') or 0))}-{int(float(event.get('TIETKETTHUC') or 0))}")
    attendance = clean_html_breaks(event.get("THONGTINCHUYENCAN"))
    if attendance:
        lines.append("Attendance: " + attendance)
    return "\n".join(lines)
