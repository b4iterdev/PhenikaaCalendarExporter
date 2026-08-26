#!/usr/bin/env python3
"""Interactive browser login that captures Phenikaa credentials automatically.

Opens a Playwright-driven Chromium window at the student portal. The user signs
in manually; the session bootstrap (userId + tokenJWT) is captured passively by
watching network traffic, mirroring exactly what a logged-in browser receives.
Credentials are never printed and only ever written to a 0600 JSON file.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from phenikaa_exporter import PORTAL_BASE_URL, parse_bootstrap_html

PORTAL_CALENDAR_URL = PORTAL_BASE_URL + "/congsinhvien/index.aspx#lichhoc"
DEFAULT_PROFILE_DIR = ".browser-profile"
DEFAULT_AUTH_JSON = ".auth.json"
DEFAULT_TIMEOUT = 300
_MARKER = "AXYZCLRVN"


def session_from_response(url: str, body: str) -> dict[str, Any] | None:
    """Extract a session from an HTML response containing the bootstrap blob."""
    if _MARKER not in body:
        return None
    try:
        return parse_bootstrap_html(body)
    except ValueError:
        return None


def token_from_authorization(value: str | None) -> str | None:
    """Return the raw JWT from an Authorization header value, or None."""
    if value and value.startswith("Bearer ") and len(value) > 7:
        return value[7:].strip()
    return None


USER_ID_SCRIPT = "window.edu?.system?.userId || null"


class LoginTimeout(RuntimeError):
    """Raised when the sign-in was not completed within the allotted time."""


def login_flow(
    profile_dir: Path | str = DEFAULT_PROFILE_DIR,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    portal_url: str = PORTAL_CALENDAR_URL,
    progress: Callable[[str], None] = lambda message: print(message, file=sys.stderr, flush=True),
) -> dict[str, Any]:
    """Open the portal, wait for manual sign-in, and capture userId + tokenJWT.

    The persistent profile keeps cookies between runs, so subsequent calls skip
    the sign-in while the portal session remains valid.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "playwright is required for --browser-login; install it with "
            "`pip install playwright` then `playwright install chromium`"
        ) from error

    session: dict[str, Any] = {}

    def merge_candidate(candidate: Any) -> None:
        if isinstance(candidate, dict):
            for key in ("userId", "tokenJWT"):
                value = candidate.get(key)
                if value:
                    session[key] = str(value)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(Path(profile_dir).expanduser()),
            headless=False,
            viewport={"width": 1280, "height": 860},
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response: Any) -> None:
            try:
                if _MARKER not in (response.url or ""):
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type:
                        return
                body = response.text()
            except Exception:
                return
            merge_candidate(session_from_response(response.url, body))

        def on_request(request: Any) -> None:
            try:
                url = request.url or ""
                if "/sinhvienapi3/" not in url:
                    return
                token = token_from_authorization(request.header_value("authorization"))
            except Exception:
                return
            if token:
                session["tokenJWT"] = token

        page.on("response", on_response)
        page.on("request", on_request)
        progress(f"Opening {portal_url} — sign in and wait for the calendar to load.")
        try:
            page.goto(portal_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            progress("Navigation warning: continuing; complete sign-in in the open window.")

        deadline = time.monotonic() + timeout
        while set(session) != {"userId", "tokenJWT"}:
            page.wait_for_timeout(1_000)
            if time.monotonic() > deadline:
                context.close()
                raise LoginTimeout(
                    "timed out waiting for sign-in; run the command again and finish "
                    "signing in before the timeout expires"
                )
            try:
                merge_candidate({"userId": page.evaluate(USER_ID_SCRIPT)})
            except Exception:
                pass
            if "userId" not in session:
                try:
                    merge_candidate(session_from_response(portal_url, page.content()))
                except Exception:
                    pass

        context.close()
    progress("Sign-in captured.")
    return {"userId": session["userId"], "tokenJWT": session["tokenJWT"]}


def save_auth_json(session: dict[str, Any], path: Path | str = DEFAULT_AUTH_JSON) -> Path:
    """Write credentials to a 0600 JSON file without exposing them in output."""
    destination = Path(path).expanduser()
    payload = json.dumps(
        {"userId": session["userId"], "tokenJWT": session["tokenJWT"]}, ensure_ascii=False, indent=2
    )
    handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(payload + "\n")
    return destination


if __name__ == "__main__":
    saved = save_auth_json(login_flow())
    print(json.dumps({"saved": str(saved.resolve())}))
