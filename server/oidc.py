"""Generic OpenID Connect client and signed application sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import jwt
from jwt import PyJWKClient


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unbase64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def load_or_create_secret(path: Path) -> bytes:
    """Load a 0600 cookie-signing secret, creating it on first use."""
    import os

    if path.exists():
        os.chmod(path, 0o600)
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "wb") as stream:
        stream.write(value)
    return value


class SignedSessions:
    """HMAC-signed, expiring cookie payloads."""

    def __init__(self, secret: bytes, *, lifetime: int = 8 * 60 * 60) -> None:
        self._secret = secret
        self._lifetime = lifetime

    def create(
        self,
        claims: dict[str, Any],
        *,
        now: int | None = None,
        lifetime: int | None = None,
    ) -> str:
        payload = dict(claims)
        payload["exp"] = (now if now is not None else int(time.time())) + (
            lifetime if lifetime is not None else self._lifetime
        )
        encoded = _base64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signature = _base64url(hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return encoded + "." + signature

    def verify(self, value: str, *, now: int | None = None) -> dict[str, Any] | None:
        try:
            encoded, supplied = value.split(".", 1)
            expected = _base64url(hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(supplied, expected):
                return None
            payload = json.loads(_unbase64url(encoded))
            if not isinstance(payload, dict) or int(payload.get("exp", 0)) <= (now if now is not None else int(time.time())):
                return None
            return payload
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return None


class OidcClient:
    """Small synchronous OIDC authorization-code client."""

    def __init__(self, issuer: str, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._metadata: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            url = self.issuer + "/.well-known/openid-configuration"
            with urllib.request.urlopen(url, timeout=15) as response:
                value = json.loads(response.read())
            if value.get("issuer", "").rstrip("/") != self.issuer:
                raise RuntimeError("OIDC discovery issuer did not match configured issuer")
            self._metadata = value
        metadata = self._metadata
        if metadata is None:
            raise RuntimeError("OIDC discovery metadata was not loaded")
        return metadata

    def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
        return str(self.metadata()["authorization_endpoint"]) + "?" + query

    def exchange_code(self, code: str, code_verifier: str, nonce: str) -> dict[str, Any]:
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code_verifier": code_verifier,
        }).encode("ascii")
        request = urllib.request.Request(
            str(self.metadata()["token_endpoint"]),
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            token_response = json.loads(response.read())
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str):
            raise RuntimeError("OIDC token response did not contain an id_token")
        key = PyJWKClient(str(self.metadata()["jwks_uri"])).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=self.client_id,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise RuntimeError("OIDC nonce did not match")
        return claims


def new_authorization_state() -> tuple[str, str, str, str]:
    """Return state, nonce, PKCE verifier, and S256 challenge."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return state, nonce, verifier, challenge
