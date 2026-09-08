"""Silent token refresh through a retained Playwright profile.

Ports probe.py's silent_relogin: opens the session's persistent profile
headlessly, visits the portal, and passively captures a fresh userId/tokenJWT
pair while the retained portal cookies keep the user signed in. No screen is
streamed; if the portal presents a login page this raises LoginTimeout and the
session is flagged needs_human for a streamed re-login.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, cast

from phenikaa_login import (
    LoginTimeout,
    PORTAL_CALENDAR_URL,
    USER_ID_SCRIPT,
    session_from_response,
    token_from_authorization,
)


def silent_refresh(
    profile_dir: Path | str,
    *,
    timeout: float = 180.0,
    portal_url: str = PORTAL_CALENDAR_URL,
    launch_context: Callable[..., Any] | None = None,
    no_sandbox: bool = False,
) -> dict[str, Any]:
    """Recapture credentials from a logged-in profile, headlessly.

    `launch_context` is injectable for tests; by default a real Playwright
    persistent context is used.
    """
    if launch_context is None:
        def launch_context(
            profile_dir_str: str,
            headless: bool,
            viewport: dict[str, int],
            args: list[str],
        ) -> tuple[Any, Any]:
            from playwright.sync_api import ViewportSize, sync_playwright

            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(
                profile_dir_str,
                headless=headless,
                viewport=cast(ViewportSize, cast(object, viewport)),
                args=args,
            )
            return context, playwright

    session: dict[str, Any] = {}

    def merge_candidate(candidate: Any) -> None:
        if isinstance(candidate, dict):
            for key in ("userId", "tokenJWT"):
                value = candidate.get(key)
                if value:
                    session[key] = str(value)

    args = ["--no-sandbox"] if no_sandbox else []
    launched = launch_context(str(Path(profile_dir).expanduser()), True, {"width": 1280, "height": 860}, args)
    if isinstance(launched, tuple):
        context, playwright_owner = launched
    else:
        context, playwright_owner = launched, None
    try:
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response: Any) -> None:
            try:
                if "AXYZCLRVN" not in (response.url or ""):
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type:
                        return
                merge_candidate(session_from_response(response.url, response.text()))
            except Exception:
                return

        def on_request(request: Any) -> None:
            try:
                if "/sinhvienapi3/" not in (request.url or ""):
                    return
                token = token_from_authorization(request.header_value("authorization"))
            except Exception:
                return
            if token:
                session["tokenJWT"] = token

        page.on("response", on_response)
        page.on("request", on_request)
        try:
            page.goto(portal_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            pass

        deadline = time.monotonic() + timeout
        while set(session) != {"userId", "tokenJWT"}:
            page.wait_for_timeout(1000)
            if time.monotonic() > deadline:
                raise LoginTimeout("silent refresh timed out; the portal wants a human sign-in")
            try:
                merge_candidate({"userId": page.evaluate(USER_ID_SCRIPT)})
            except Exception:
                pass
            if "userId" not in session:
                try:
                    merge_candidate(session_from_response(portal_url, page.content()))
                except Exception:
                    pass
    finally:
        context.close()
        if playwright_owner is not None:
            try:
                playwright_owner.stop()
            except Exception:
                pass

    return {"userId": session["userId"], "tokenJWT": session["tokenJWT"]}


class ProfileLocks:
    """Per-profile mutexes so sync refresh and streamed login never overlap."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def for_profile(self, key: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())
