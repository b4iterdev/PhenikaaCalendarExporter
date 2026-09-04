"""Streamed headless-login broker for creating Phenikaa sessions.

Ports the dev/experimental remote-seed flow: a headless Chromium persistent
context is opened on the session's profile directory, its screen is screencast
as JPEG frames (served to the browser by server/web.py), and keystrokes/clicks
arrive back as validated events which are forwarded over CDP. Credentials are
captured passively exactly like phenikaa_login.login_flow; the Phenikaa
password never touches this server's storage.
"""

from __future__ import annotations

import base64
import queue
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

from server.config import ServerConfig
from server.refresh import ProfileLocks

STREAM_WAIT_SECONDS = 1.0
TICK_MS = 100
MAX_INSERT_CHARS = 1024
MAX_QUEUE_EVENTS = 200

SPECIAL_KEYS: dict[str, int] = {
    "Enter": 13, "Tab": 9, "Backspace": 8, "Delete": 46, "Escape": 27,
    "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
    "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34,
}


def validate_event(event: Any) -> dict[str, Any] | None:
    """Return a sanitized forwarding-legal event, or None if it must be dropped."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "click":
        x, y = event.get("x"), event.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return {"type": "click", "x": max(0.0, min(float(x), 10000.0)), "y": max(0.0, min(float(y), 10000.0))}
        return None
    if kind == "char":
        key = event.get("key")
        if isinstance(key, str) and len(key) == 1:
            return {"type": "char", "key": key}
        return None
    if kind == "special":
        key = event.get("key")
        if isinstance(key, str) and key in SPECIAL_KEYS:
            return {"type": "special", "key": key}
        return None
    if kind == "insert":
        text = event.get("text")
        if isinstance(text, str) and 0 < len(text) <= MAX_INSERT_CHARS:
            return {"type": "insert", "text": text}
        return None
    return None


def dispatch_event(cdp: Any, event: dict[str, Any]) -> None:
    """Forward one validated UI event into the headless page via CDP."""
    kind = event["type"]
    if kind == "click":
        for action in ("mousePressed", "mouseReleased"):
            cdp.send("Input.dispatchMouseEvent", {
                "type": action, "x": event["x"], "y": event["y"],
                "button": "left", "clickCount": 1,
            })
    elif kind == "char":
        cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": event["key"]})
        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": event["key"]})
    elif kind == "special":
        key = event["key"]
        code = SPECIAL_KEYS[key]
        for action in ("keyDown", "keyUp"):
            cdp.send("Input.dispatchKeyEvent", {
                "type": action, "key": key, "code": key,
                "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code,
            })
    elif kind == "insert":
        cdp.send("Input.insertText", {"text": event["text"]})


class LoginAttempt:
    """Shared state between the Playwright thread and the web handlers."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.jpeg: bytes | None = None
        self.seq: int = 0
        self.session_id: str | None = None
        self.pending_ack: bool = False
        self.events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=MAX_QUEUE_EVENTS)
        self.captured: dict[str, Any] = {}
        self.error: BaseException | None = None
        self.finished = threading.Event()

    def publish_frame(self, params: dict[str, Any]) -> None:
        jpeg = base64.b64decode(params.get("data") or "")
        with self.condition:
            self.jpeg = jpeg
            self.session_id = params.get("sessionId")
            self.pending_ack = True
            self.seq += 1
            self.condition.notify_all()

    def latest_frame(self, last_seq: int) -> tuple[bytes | None, int]:
        with self.condition:
            if self.seq == last_seq:
                self.condition.wait(timeout=STREAM_WAIT_SECONDS)
            if self.seq == last_seq or self.jpeg is None:
                return None, last_seq
            return self.jpeg, self.seq

    def push_event(self, event: dict[str, Any]) -> bool:
        try:
            self.events.put_nowait(event)
            return True
        except queue.Full:
            return False


class LoginBroker:
    """Runs one streamed login per profile directory, serialized by a lock.

    Playwright forbids two live browser instances on one user-data directory,
    so each profile owns a re-entrant lock held for the whole attempt.
    """

    def __init__(
        self,
        config: ServerConfig,
        *,
        locks: ProfileLocks | None = None,
        launch_context: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._locks = locks or ProfileLocks()
        self._attempts: dict[str, LoginAttempt] = {}
        self._attempts_guard = threading.Lock()
        # Injectable for tests: launch_context(profile_dir_str, headless, viewport, args)
        self._launch_context = launch_context or self._default_launch_context

    def _default_launch_context(
        self,
        profile_dir: str,
        headless: bool,
        viewport: dict[str, int],
        args: list[str],
    ) -> tuple[Any, Any]:
        from playwright.sync_api import ViewportSize, sync_playwright

        playwright = sync_playwright().start()
        context = playwright.chromium.launch_persistent_context(
            profile_dir, headless=headless, viewport=cast(ViewportSize, cast(object, viewport)), args=args
        )
        return context, playwright

    def _lock_for(self, profile_key: str) -> threading.RLock:
        return self._locks.for_profile(profile_key)

    def try_profile_lock(self, session_id: str, *, blocking: bool = False) -> threading.RLock | None:
        lock = self._lock_for(session_id)
        return lock if lock.acquire(blocking=blocking) else None

    def profile_dir(self, session_id: str) -> Path:
        return self._config.profiles_dir / session_id

    def delete_profile(self, session_id: str) -> None:
        import shutil

        with self._lock_for(session_id):
            path = self.profile_dir(session_id)
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def attempt_login(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
        portal_url: str = PORTAL_CALENDAR_URL,
        progress: Callable[[str], None] = lambda message: None,
        state: LoginAttempt | None = None,
    ) -> dict[str, Any]:
        """Run a blocking streamed sign-in and return the captured session.

        Raises LoginTimeout when the user does not finish in time; the caller
        keeps the session status as pending_login so the user can retry.
        """
        timeout = timeout if timeout is not None else self._config.login_timeout
        state = state or LoginAttempt()
        lock = self._lock_for(session_id)
        with lock:
            profile_dir = self.profile_dir(session_id)
            profile_dir.mkdir(parents=True, exist_ok=True)
            args = ["--no-sandbox"] if self._config.browser_no_sandbox else []
            launched = self._launch_context(str(profile_dir), True, {"width": 1280, "height": 860}, args)
            if isinstance(launched, tuple):
                context, playwright_owner = launched
            else:
                context, playwright_owner = launched, None
            cdp = None
            try:
                page = context.pages[0] if context.pages else context.new_page()
                cdp = context.new_cdp_session(page)
                self._wire_capture(page, state)

                def on_frame(params: dict[str, Any]) -> None:
                    state.publish_frame(params)

                cdp.on("Page.screencastFrame", on_frame)
                cdp.send("Page.startScreencast", {
                    "format": "jpeg", "quality": 70,
                    "maxWidth": 1280, "maxHeight": 860, "everyNthFrame": 1,
                })
                progress("stream ready")
                try:
                    page.goto(portal_url, wait_until="domcontentloaded", timeout=60_000)
                except Exception:
                    pass  # navigation warnings are non-fatal; sign-in continues

                deadline = time.monotonic() + timeout
                while set(state.captured) != {"userId", "tokenJWT"}:
                    page.wait_for_timeout(TICK_MS)
                    if state.pending_ack and state.session_id is not None:
                        try:
                            cdp.send("Page.screencastFrameAck", {"sessionId": state.session_id})
                        finally:
                            state.pending_ack = False
                    try:
                        dispatch_event(cdp, state.events.get_nowait())
                    except queue.Empty:
                        pass
                    self._probe_user_id(page, state, portal_url)
                    if time.monotonic() > deadline:
                        raise LoginTimeout(
                            "sign-in window timed out; start again and finish signing in sooner"
                        )
            finally:
                if cdp is not None:
                    try:
                        cdp.send("Page.stopScreencast")
                    except Exception:
                        pass
                context.close()
                if playwright_owner is not None:
                    try:
                        playwright_owner.stop()
                    except Exception:
                        pass
                state.finished.set()
        progress("sign-in captured")
        return {"userId": state.captured["userId"], "tokenJWT": state.captured["tokenJWT"]}

    def start_login(
        self,
        session_id: str,
        on_complete: Callable[[dict[str, Any]], None],
        on_error: Callable[[BaseException], None],
    ) -> LoginAttempt:
        with self._attempts_guard:
            current = self._attempts.get(session_id)
            if current and not current.finished.is_set():
                return current
            state = LoginAttempt()
            self._attempts[session_id] = state

        def worker() -> None:
            try:
                on_complete(self.attempt_login(session_id, state=state))
            except BaseException as error:
                state.error = error
                on_error(error)
            finally:
                state.finished.set()

        threading.Thread(target=worker, name=f"login-{session_id[:8]}", daemon=True).start()
        return state

    def get_attempt(self, session_id: str) -> LoginAttempt | None:
        with self._attempts_guard:
            return self._attempts.get(session_id)

    def forget_attempt(self, session_id: str) -> None:
        with self._attempts_guard:
            self._attempts.pop(session_id, None)

    def _wire_capture(self, page: Any, state: LoginAttempt) -> None:
        def merge_candidate(candidate: Any) -> None:
            if isinstance(candidate, dict):
                for key in ("userId", "tokenJWT"):
                    value = candidate.get(key)
                    if value:
                        state.captured[key] = str(value)

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
                state.captured["tokenJWT"] = token

        page.on("response", on_response)
        page.on("request", on_request)

    def _probe_user_id(self, page: Any, state: LoginAttempt, portal_url: str) -> None:
        try:
            value = page.evaluate(USER_ID_SCRIPT)
            if value:
                state.captured["userId"] = str(value)
        except Exception:
            pass
        if "userId" not in state.captured:
            try:
                candidate = session_from_response(portal_url, page.content())
                if isinstance(candidate, dict) and candidate.get("userId"):
                    state.captured["userId"] = str(candidate["userId"])
            except Exception:
                pass
