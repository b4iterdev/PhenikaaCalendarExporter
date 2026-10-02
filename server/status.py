from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

DEFAULT_PROBE_TIMEOUT = 4.0
CACHE_TTL_SECONDS = 15.0


def check_phenikaa_portal(timeout: float = DEFAULT_PROBE_TIMEOUT) -> dict[str, Any]:
    url = "https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/login.aspx"
    start = time.monotonic()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            latency = int((time.monotonic() - start) * 1000)
            return {
                "name": "Phenikaa Student Portal",
                "target": "qldtbeta.phenikaa-uni.edu.vn",
                "ok": True,
                "status": "operational",
                "code": response.status,
                "latency_ms": latency,
                "message": "Portal reachable and responding",
            }
    except urllib.error.HTTPError as error:
        latency = int((time.monotonic() - start) * 1000)
        is_ok = error.code in (301, 302, 303, 307, 308, 403)
        return {
            "name": "Phenikaa Student Portal",
            "target": "qldtbeta.phenikaa-uni.edu.vn",
            "ok": is_ok,
            "status": "operational" if is_ok else "degraded",
            "code": error.code,
            "latency_ms": latency,
            "message": f"HTTP {error.code}" if is_ok else f"HTTP {error.code} {error.reason}",
        }
    except (socket.timeout, TimeoutError):
        latency = int((time.monotonic() - start) * 1000)
        return {
            "name": "Phenikaa Student Portal",
            "target": "qldtbeta.phenikaa-uni.edu.vn",
            "ok": False,
            "status": "unreachable",
            "code": None,
            "latency_ms": latency,
            "error": "Connection timed out (possible firewall geoblock or portal outage)",
        }
    except Exception as error:
        latency = int((time.monotonic() - start) * 1000)
        return {
            "name": "Phenikaa Student Portal",
            "target": "qldtbeta.phenikaa-uni.edu.vn",
            "ok": False,
            "status": "unreachable",
            "code": None,
            "latency_ms": latency,
            "error": str(error),
        }


def check_google_service(timeout: float = DEFAULT_PROBE_TIMEOUT) -> dict[str, Any]:
    url = "https://www.googleapis.com/discovery/v1/apis/calendar/v3/rest"
    start = time.monotonic()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PhenikaaCalendarServer/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            latency = int((time.monotonic() - start) * 1000)
            return {
                "name": "Google Calendar Service",
                "target": "googleapis.com",
                "ok": True,
                "status": "operational",
                "code": response.status,
                "latency_ms": latency,
                "message": "Google Calendar API reachable",
            }
    except urllib.error.HTTPError as error:
        latency = int((time.monotonic() - start) * 1000)
        is_ok = error.code in (200, 204, 403)
        return {
            "name": "Google Calendar Service",
            "target": "googleapis.com",
            "ok": is_ok,
            "status": "operational" if is_ok else "degraded",
            "code": error.code,
            "latency_ms": latency,
            "message": f"HTTP {error.code}",
        }
    except Exception as error:
        latency = int((time.monotonic() - start) * 1000)
        return {
            "name": "Google Calendar Service",
            "target": "googleapis.com",
            "ok": False,
            "status": "unreachable",
            "code": None,
            "latency_ms": latency,
            "error": str(error),
        }


def check_public_ip(timeout: float = 3.0) -> str | None:
    services = [
        "https://api.ipify.org",
        "https://icanhazip.com",
        "https://ifconfig.me/ip",
    ]
    for url in services:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                ip = response.read().decode("ascii").strip()
                if ip and len(ip) <= 45:
                    return ip
        except Exception:
            continue
    return None


class StatusCollector:
    """Collects and caches live availability of upstream dependencies and internal services."""

    def __init__(
        self,
        cache_ttl: float = CACHE_TTL_SECONDS,
        *,
        probe_phenikaa: Callable[[float], dict[str, Any]] = check_phenikaa_portal,
        probe_google: Callable[[float], dict[str, Any]] = check_google_service,
        probe_ip: Callable[[float], str | None] = check_public_ip,
    ) -> None:
        self.cache_ttl = cache_ttl
        self._probe_phenikaa = probe_phenikaa
        self._probe_google = probe_google
        self._probe_ip = probe_ip
        self._lock = threading.Lock()
        self._last_checked: float = 0.0
        self._cached_payload: dict[str, Any] | None = None

    def get_status(
        self,
        *,
        force_refresh: bool = False,
        include_system: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if not force_refresh and self._cached_payload is not None and (now - self._last_checked) < self.cache_ttl:
                result = dict(self._cached_payload)
                if include_system:
                    result["system"] = include_system
                return result

            phenikaa = self._probe_phenikaa(DEFAULT_PROBE_TIMEOUT)
            google = self._probe_google(DEFAULT_PROBE_TIMEOUT)
            public_ip = self._probe_ip(3.0)

            overall_ok = bool(phenikaa.get("ok")) and bool(google.get("ok"))
            overall_status = "operational" if overall_ok else ("degraded" if phenikaa.get("ok") or google.get("ok") else "major_outage")

            payload: dict[str, Any] = {
                "overall_status": overall_status,
                "overall_ok": overall_ok,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "public_ip": public_ip or "Unavailable",
                "services": {
                    "phenikaa": phenikaa,
                    "google": google,
                },
            }
            self._cached_payload = payload
            self._last_checked = now

            result = dict(payload)
            if include_system:
                result["system"] = include_system
            return result
