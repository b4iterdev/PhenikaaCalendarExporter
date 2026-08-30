"""Server configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_STATE_DIR = "server-state"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8416
DEFAULT_SYNC_INTERVAL_HOURS = 24
DEFAULT_LOGIN_TIMEOUT = 600.0
DEFAULT_REFRESH_TIMEOUT = 180.0
# Academic-year window (Aug 1 -> Jul 31 next year), configurable per session.
DEFAULT_RANGE_START_MONTH = 8
DEFAULT_RANGE_START_DAY = 1


def academic_year_range(today: date | None = None) -> tuple[date, date]:
    """Return the (start, end) dates of the academic year surrounding `today`."""
    today = today or date.today()
    start = date(today.year, DEFAULT_RANGE_START_MONTH, DEFAULT_RANGE_START_DAY)
    if today < start:
        start = date(today.year - 1, DEFAULT_RANGE_START_MONTH, DEFAULT_RANGE_START_DAY)
    return start, date(start.year + 1, 7, 31)


@dataclass
class ServerConfig:
    state_dir: Path = field(default_factory=lambda: Path(os.environ.get("PHENIKAA_SERVER_STATE", DEFAULT_STATE_DIR)))
    host: str = field(default_factory=lambda: os.environ.get("PHENIKAA_SERVER_HOST", DEFAULT_HOST))
    port: int = field(default_factory=lambda: int(os.environ.get("PHENIKAA_SERVER_PORT", str(DEFAULT_PORT))))
    base_url: str = field(default_factory=lambda: os.environ.get("PHENIKAA_SERVER_BASE_URL", ""))
    sync_interval_hours: float = field(
        default_factory=lambda: float(os.environ.get("PHENIKAA_SERVER_SYNC_INTERVAL_HOURS", str(DEFAULT_SYNC_INTERVAL_HOURS)))
    )
    login_timeout: float = field(
        default_factory=lambda: float(os.environ.get("PHENIKAA_SERVER_LOGIN_TIMEOUT", str(DEFAULT_LOGIN_TIMEOUT)))
    )
    refresh_timeout: float = field(
        default_factory=lambda: float(os.environ.get("PHENIKAA_SERVER_REFRESH_TIMEOUT", str(DEFAULT_REFRESH_TIMEOUT)))
    )
    encryption_key: str = field(default_factory=lambda: os.environ.get("PHENIKAA_SERVER_KEY", ""))
    browser_no_sandbox: bool = field(
        default_factory=lambda: os.environ.get("PHENIKAA_BROWSER_NO_SANDBOX", "").lower() in ("1", "true", "yes")
    )
    # OIDC ("disabled" -> single local user for development and tests)
    auth_mode: str = field(default_factory=lambda: os.environ.get("PHENIKAA_SERVER_AUTH", "oidc"))
    oidc_issuer: str = field(default_factory=lambda: os.environ.get("PHENIKAA_OIDC_ISSUER", ""))
    oidc_client_id: str = field(default_factory=lambda: os.environ.get("PHENIKAA_OIDC_CLIENT_ID", ""))
    oidc_client_secret: str = field(default_factory=lambda: os.environ.get("PHENIKAA_OIDC_CLIENT_SECRET", ""))
    oidc_redirect_uri: str = field(default_factory=lambda: os.environ.get("PHENIKAA_OIDC_REDIRECT_URI", ""))
    google_client_id: str = field(default_factory=lambda: os.environ.get("PHENIKAA_GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("PHENIKAA_GOOGLE_CLIENT_SECRET", ""))
    google_redirect_uri: str = field(default_factory=lambda: os.environ.get("PHENIKAA_GOOGLE_REDIRECT_URI", ""))

    @property
    def db_path(self) -> Path:
        return self.state_dir / "server.db"

    @property
    def key_path(self) -> Path:
        return self.state_dir / "secret.key"

    @property
    def cookie_secret_path(self) -> Path:
        return self.state_dir / "cookie.secret"

    @property
    def profiles_dir(self) -> Path:
        return self.state_dir / "profiles"

    @property
    def exports_dir(self) -> Path:
        return self.state_dir / "exports"

    def ensure_dirs(self) -> None:
        for path in (self.state_dir, self.profiles_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_dir, 0o700)
        except OSError:
            pass

    def external_url(self, path: str = "") -> str:
        base = self.base_url.rstrip("/") or f"http://{self.host}:{self.port}"
        return base + path

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)
