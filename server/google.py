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
from server.db import Database, GOOGLE_APP_CALENDAR_READY, GOOGLE_PRIMARY_CLEANUP_PENDING

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CALENDARS_URL = "https://www.googleapis.com/calendar/v3/calendars"
EVENTS_BASE_URL = "https://www.googleapis.com/calendar/v3/calendars"
PRIMARY_CALENDAR_ID = "primary"
APP_CALENDAR_SUMMARY = "Phenikaa Learning Calendar"
APP_CREATED_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
SCOPE = APP_CREATED_SCOPE
LEGACY_CLEANUP_SCOPE = APP_CREATED_SCOPE + " " + EVENTS_SCOPE
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


def authorization_url(config: GoogleOAuthConfig, state: str, scope: str = SCOPE) -> str:
    query = urllib.parse.urlencode({
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": scope,
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

    def authorization_url(self, state: str, scope: str = SCOPE) -> str:
        return authorization_url(self.config, state, scope)

    def exchange_code(self, session_id: str, code: str, requested_scope: str = SCOPE) -> None:
        existing = self.database.get_google_connection(session_id)
        token = self._token_request({
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
        })
        existing_refresh_token = None if existing is None else self.vault.decrypt(str(existing["refresh_token_encrypted"]))
        self._store_tokens(
            session_id, token, existing_refresh_token=existing_refresh_token, scope_fallback=requested_scope
        )

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
            connection = self.database.get_google_connection(session_id) or connection
            calendar_id = self._ensure_app_calendar(session_id, access_token, connection)
            connection = self.database.get_google_connection(session_id) or connection
            if connection.get("migration_state") == GOOGLE_PRIMARY_CLEANUP_PENDING:
                self._cleanup_primary_links(session_id, access_token)
            result = self._reconcile(session_id, access_token, calendar_id, events)
            connection = self.database.get_google_connection(session_id) or connection
            if self._has_scope(connection, EVENTS_SCOPE):
                self._revoke_broad_legacy_connection(session_id, connection)
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
        self._store_tokens(
            session_id, token, existing_refresh_token=refresh_token, scope_fallback=str(connection.get("scope") or "")
        )
        return str(token["access_token"])

    def _revocation_token(self, connection: dict[str, Any]) -> str:
        refresh_token_encrypted = str(connection.get("refresh_token_encrypted") or "")
        if refresh_token_encrypted:
            return self.vault.decrypt(refresh_token_encrypted)
        return self.vault.decrypt(str(connection["access_token_encrypted"]))

    def _store_tokens(
        self,
        session_id: str,
        token: dict[str, Any],
        *,
        existing_refresh_token: Optional[str],
        scope_fallback: str,
    ) -> None:
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
            scope=str(token.get("scope") or scope_fallback),
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

    def _reconcile(
        self, session_id: str, access_token: str, calendar_id: str, events: list[dict[str, Any]]
    ) -> GoogleSyncResult:
        desired = {source_key(event): google_event_body(event) for event in normalize_events(events)}
        links = {
            str(row["source_key"]): str(row["google_event_id"])
            for row in self.database.list_google_event_links(session_id, calendar_id)
        }
        created = updated = deleted = 0
        for key, body in desired.items():
            body["extendedProperties"] = {"private": {APP_PRIVATE_KEY: key}}
            if key in links:
                status, payload = self._calendar_request(
                    "PUT", self._event_url(calendar_id, links[key]), access_token, body
                )
                if status == 404:
                    event_id = self._insert_event(access_token, calendar_id, body)
                    self.database.upsert_google_event_link(session_id, key, event_id, calendar_id)
                    created += 1
                elif 200 <= status < 300:
                    updated += 1
                else:
                    raise GoogleCalendarError(self._error_message(status, payload))
            else:
                event_id = self._insert_event(access_token, calendar_id, body)
                self.database.upsert_google_event_link(session_id, key, event_id, calendar_id)
                created += 1
        for key, event_id in links.items():
            if key not in desired:
                if self._linked_event_absent_or_verified(access_token, calendar_id, event_id, key):
                    status, payload = self._calendar_request("DELETE", self._event_url(calendar_id, event_id), access_token, None)
                    if status not in (200, 204, 404, 410):
                        raise GoogleCalendarError(self._error_message(status, payload))
                self.database.delete_google_event_link(session_id, key, calendar_id)
                deleted += 1
        detail = f"Google Calendar sync created {created}, updated {updated}, deleted {deleted}"
        return GoogleSyncResult(True, True, created, updated, deleted, detail)

    def _ensure_app_calendar(self, session_id: str, access_token: str, connection: dict[str, Any]) -> str:
        calendar_id = self._app_calendar_id(connection.get("calendar_id"))
        if calendar_id:
            status, payload = self._calendar_request("GET", self._calendar_url(calendar_id), access_token, None)
            if 200 <= status < 300:
                return calendar_id
            if status != 404:
                raise GoogleCalendarError(self._error_message(status, payload))
            replacement_id = self._create_app_calendar(session_id, access_token, connection)
            self.database.delete_google_event_links_for_calendar(session_id, calendar_id)
            return replacement_id
        return self._create_app_calendar(session_id, access_token, connection)

    def _create_app_calendar(self, session_id: str, access_token: str, connection: dict[str, Any]) -> str:
        if not self._has_scope(connection, APP_CREATED_SCOPE):
            raise GoogleCalendarError("Reconnect Google Calendar to authorize dedicated calendar creation")
        status, payload = self._calendar_request("POST", CALENDARS_URL, access_token, {"summary": APP_CALENDAR_SUMMARY})
        if status < 200 or status >= 300:
            raise GoogleCalendarError(self._error_message(status, payload))
        calendar_id = str(payload.get("id") or "")
        if not calendar_id:
            raise GoogleCalendarError("Google calendar insert response did not include an id")
        self.database.set_google_calendar_id(session_id, calendar_id)
        return calendar_id

    def _has_scope(self, connection: dict[str, Any], required_scope: str) -> bool:
        granted = {scope for scope in str(connection.get("scope") or "").split() if scope}
        return required_scope in granted

    def _app_calendar_id(self, value: Any) -> str:
        calendar_id = str(value or "").strip()
        if not calendar_id or calendar_id == PRIMARY_CALENDAR_ID:
            return ""
        return calendar_id

    def _revoke_broad_legacy_connection(self, session_id: str, connection: dict[str, Any]) -> None:
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

    def _calendar_url(self, calendar_id: str) -> str:
        return CALENDARS_URL + "/" + urllib.parse.quote(calendar_id, safe="")

    def _cleanup_primary_links(self, session_id: str, access_token: str) -> None:
        links = self.database.list_google_event_links(session_id, PRIMARY_CALENDAR_ID)
        for row in links:
            source = str(row["source_key"])
            event_id = str(row["google_event_id"])
            if not self._linked_event_absent_or_verified(access_token, PRIMARY_CALENDAR_ID, event_id, source):
                self.database.delete_google_event_link(session_id, source, PRIMARY_CALENDAR_ID)
                continue
            status, payload = self._calendar_request(
                "DELETE", self._event_url(PRIMARY_CALENDAR_ID, event_id), access_token, None
            )
            if status not in (200, 204, 404, 410):
                raise GoogleCalendarError(self._error_message(status, payload))
            self.database.delete_google_event_link(session_id, source, PRIMARY_CALENDAR_ID)
        self.database.set_google_migration_state(session_id, GOOGLE_APP_CALENDAR_READY)


    def _linked_event_absent_or_verified(
        self, access_token: str, calendar_id: str, event_id: str, source: str
    ) -> bool:
        status, payload = self._calendar_request("GET", self._event_url(calendar_id, event_id), access_token, None)
        if status in (404, 410):
            return False
        if status < 200 or status >= 300:
            raise GoogleCalendarError(self._error_message(status, payload))
        extended_properties = payload.get("extendedProperties")
        if not isinstance(extended_properties, dict):
            raise GoogleCalendarError("Google event did not include the app private marker")
        private_properties = extended_properties.get("private")
        if not isinstance(private_properties, dict) or private_properties.get(APP_PRIVATE_KEY) != source:
            raise GoogleCalendarError("Google event app private marker did not match the stored source key")
        return True

    def _insert_event(self, access_token: str, calendar_id: str, body: dict[str, Any]) -> str:
        status, payload = self._calendar_request("POST", self._events_url(calendar_id), access_token, body)
        if status < 200 or status >= 300:
            raise GoogleCalendarError(self._error_message(status, payload))
        event_id = str(payload.get("id") or "")
        if not event_id:
            raise GoogleCalendarError("Google event insert response did not include an id")
        return event_id

    def _events_url(self, calendar_id: str) -> str:
        return EVENTS_BASE_URL + "/" + urllib.parse.quote(calendar_id, safe="") + "/events"

    def _event_url(self, calendar_id: str, event_id: str) -> str:
        return self._events_url(calendar_id) + "/" + urllib.parse.quote(event_id, safe="")

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
