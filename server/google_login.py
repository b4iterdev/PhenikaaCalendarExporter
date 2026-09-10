"""Google app identity and user-owned Calendar grants, independent of portal sessions."""

from __future__ import annotations

import hmac
import json
import urllib.parse
from datetime import timedelta
from typing import Any

import jwt
from jwt import PyJWKClient

from server.google import APP_CREATED_SCOPE, AUTH_URL, REVOKE_URL, GoogleCalendarError, GoogleCalendarService

LOGIN_SCOPE = "openid email profile " + APP_CREATED_SCOPE
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


class GoogleLoginService(GoogleCalendarService):
    user_bound: bool = True

    def login_url(self, state: str, nonce: str, challenge: str, *, consent: bool = False,
                  subject: str = "") -> str:
        params = {
            "client_id": self.config.client_id, "redirect_uri": self.config.redirect_uri,
            "response_type": "code", "scope": LOGIN_SCOPE, "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline",
        }
        if consent:
            params["prompt"] = "consent"
        if subject:
            params["login_hint"] = subject
        return AUTH_URL + "?" + urllib.parse.urlencode(params)

    def verify_identity(self, id_token: str, nonce: str) -> dict[str, Any]:
        key = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs").get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, key.key, algorithms=["RS256"], audience=self.config.client_id,
                            issuer=GOOGLE_ISSUERS, options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]})
        if not hmac.compare_digest(str(claims["nonce"]), nonce):
            raise GoogleCalendarError("Google nonce did not match")
        if claims.get("azp", self.config.client_id) != self.config.client_id:
            raise GoogleCalendarError("Google authorized party did not match")
        return claims

    def login(self, code: str, verifier: str, nonce: str, *, expected_sub: str = "") -> dict[str, Any]:
        token = self._token_request({
            "code": code, "code_verifier": verifier, "client_id": self.config.client_id,
            "client_secret": self.config.client_secret, "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
        })
        claims = self.verify_identity(str(token.get("id_token") or ""), nonce)
        subject = str(claims["sub"])
        if expected_sub and not hmac.compare_digest(expected_sub, subject):
            raise GoogleCalendarError("Use the same Google account that you used to sign in")
        # Separate identity namespaces: never link an existing OIDC user by email.
        prior_user = self.database.find_user("google:" + subject)
        if prior_user and self.database.get_google_user_grant(int(prior_user["id"])) is None:
            raise GoogleCalendarError("Google identity conflicts with an existing OIDC account")
        existing = self.database.get_google_user_grant(int(prior_user["id"])) if prior_user else None
        previous = self._credentials(existing) if existing else {}
        credentials = self._token_values(token, previous)
        user = self.database.get_or_create_user("google:" + subject, str(claims.get("name") or claims.get("email") or subject))
        user_id = int(user["id"])
        self.database.save_google_user_grant(user_id, subject, str(claims.get("email") or ""),
                                             self.vault.encrypt(json.dumps(credentials)))
        return {"sub": user["oidc_sub"], "google_sub": subject, "name": user["display_name"], "auth_mode": "google"}

    def _credentials(self, grant: dict[str, Any]) -> dict[str, Any]:
        return json.loads(self.vault.decrypt(str(grant["credentials_encrypted"])))

    def _token_values(self, token: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        access = str(token.get("access_token") or "")
        if not access:
            raise GoogleCalendarError("Google did not return an access token")
        return {
            "access_token_encrypted": self.vault.encrypt(access),
            "refresh_token_encrypted": self.vault.encrypt(str(token.get("refresh_token") or (
                self.vault.decrypt(str(previous["refresh_token_encrypted"])) if previous.get("refresh_token_encrypted") else ""))),
            "has_refresh": bool(token.get("refresh_token") or previous.get("has_refresh")),
            "scope": str(token.get("scope") or ""),
            "expires_at": (self.clock() + timedelta(seconds=max(0, int(token.get("expires_in") or 3600)))).isoformat(),
        }

    def grant_status(self, user_id: int) -> dict[str, Any] | None:
        grant = self.database.get_google_user_grant(user_id)
        if grant is None:
            return None
        credentials = self._credentials(grant)
        return {**grant, "ready": bool(credentials.get("has_refresh") and APP_CREATED_SCOPE in credentials["scope"].split())}

    def _owner(self, session_id: str) -> int:
        session = self.database.get_session(session_id)
        if session is None:
            raise GoogleCalendarError("Phenikaa session no longer exists")
        return int(session["owner_user_id"])

    def connection(self, session_id: str) -> dict[str, Any] | None:
        grant = self.grant_status(self._owner(session_id))
        if grant is None or not grant["sync_enabled"] or not grant["ready"]:
            return None
        state = self.database.get_google_calendar_state(session_id) or {}
        return {**self._credentials(grant), **state}

    def _store_tokens(self, session_id: str, token: dict[str, Any], *, existing_refresh_token: str | None,
                      scope_fallback: str) -> None:
        user_id = self._owner(session_id)
        grant = self.database.get_google_user_grant(user_id)
        if grant is None:
            raise GoogleCalendarError("Google authorization no longer exists")
        # Refresh responses may omit scope; authorization responses may not assume it.
        credentials = self._token_values({"scope": scope_fallback, **token}, self._credentials(grant))
        self.database.save_google_user_grant(user_id, str(grant["google_sub"]), str(grant["email"]),
                                             self.vault.encrypt(json.dumps(credentials)))

    def _set_error(self, session_id: str, error: str | None) -> None:
        self.database.set_google_user_error(self._owner(session_id), error)

    def revoke(self, user_id: int) -> None:
        grant = self.database.get_google_user_grant(user_id)
        if grant is None:
            return
        credentials = self._credentials(grant)
        encrypted = credentials["refresh_token_encrypted"] if credentials["has_refresh"] else credentials["access_token_encrypted"]
        response = self.http_request("POST", REVOKE_URL, {"Content-Type": "application/x-www-form-urlencoded"},
                                     urllib.parse.urlencode({"token": self.vault.decrypt(encrypted)}).encode("ascii"), self.timeout)
        if response.status not in (200, 400):
            raise GoogleCalendarError("Google access revocation failed; retry account deletion")
        self.database.set_google_user_sync(user_id, False)

    def disconnect(self, session_id: str) -> None:
        self.database.set_google_user_sync(self._owner(session_id), False)
