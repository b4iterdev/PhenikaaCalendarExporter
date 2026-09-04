# Repository Instructions

## Project Structure

- `phenikaa_exporter.py` — CLI/API/export implementation; entrypoint `phenikaa-calendar`
- `phenikaa_login.py` — Playwright-based browser login and credential capture
- `server/` — HTTP server, SQLite persistence, OIDC, Playwright broker, token refresh, Google Calendar sync, and inline HTML UI
- `tests/` — `unittest` test modules for exporter, browser, storage, web, OIDC, Google, and sync
- `frontend/input.css` and `tailwind.config.js` — Tailwind source/config for the server-rendered UI
- `server/static/styles.css` — generated Tailwind output; regenerate it instead of editing manually
- `experiments/` — untracked; do not modify or commit
- `skills.md` — Frontend design rules and hero design specification
- `AGENTS.md` — This file

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
``` 

Frontend assets:

```bash
npm install
npm run build
```

Server/browser extras:

```bash
# Server: python -m pip install -e ".[server]"
# Browser: python -m pip install -e ".[login]" && playwright install chromium
```

## Commands

- `python -m unittest discover -s tests -v` — full test suite
- `python -m unittest tests.test_server_web -v` — single test module
- `python -m unittest tests.test_server_web.WebSmokeTests.test_name -v` — single test case
- `npm run build` — compile Tailwind CSS to `server/static/styles.css`
- `python phenikaa_exporter.py --start/--end ...` — CLI export
- `phenikaa-calendar-server` — start server (port 8416 default)
- No lint/formatter/typecheck config exists in the repo

## Architecture Notes

- Two entrypoints: `phenikaa-calendar` (CLI) and `phenikaa-calendar-server` (HTTP server)
- **Server UI is server-rendered HTML in `server/web.py`**; Tailwind CSS is compiled from `frontend/input.css` and served from `server/static/styles.css`
- `server/config.py` loads all server config from `PHENIKAA_*` environment variables; defaults in `config.py`
- `server/db.py` owns SQLite schema, WAL mode, thread-safe connections, and migrations
- `server/web.py` has all route handlers, HTML layout, CSP headers in one file — `_layout()` drives every page
- `server/sync.py` handles scheduled syncs; `server/refresh.py` manages browser profile refresh
- `server/google.py` handles Google Calendar OAuth and sync with migration state switching
- `server/oidc.py` handles OIDC authentication and signed sessions
- The frontend skill (`skills.md`) defines the Tailwind design rules; there is no React/TypeScript application

## Testing Quirks

- Server-dependent tests call `unittest.SkipTest` unless `pip install -e .[server]` is installed
- Tests use `unittest`, not pytest
- CI installs `.[server]`, runs `python -m unittest discover -s tests -v`, then builds Docker
- `tests/test_server_web.py` uses `FakeGoogleService` and `RecordingSync` helpers for isolation

## Environment & Secrets

- `PHENIKAA_SERVER_KEY` is required for server startup; must be a Fernet key
- `PHENIKAA_SERVER_AUTH=disabled` is for local dev/tests only — never deploy with it
- `server-state/` contains encrypted JWTs, live browser cookies, SQLite data, private exports
- `.auth.json`, authenticated HTML, browser profiles/cache, and exports are git-ignored and contain sensitive data
- `server-state/cookie.secret` signs OIDC transactions and app cookies

## Key Constraints When Editing

- Preserve CSRF validation, HTML escaping, no-store headers, token encryption, and ownership checks in `server/web.py`
- Route paths, form field names, CSRF tokens, and download behavior must stay consistent
- `_layout()` in `server/web.py` defines all shared HTML structure and inline CSS — changing it affects every page
- Google Calendar sync uses `GOOGLE_PRIMARY_CLEANUP_PENDING` migration state

## Docker

```bash
docker run -d --name phenikaa-calendar -p 8416:8416 -v phenikaa-data:/data \
  -e PHENIKAA_SERVER_KEY="..." \
  -e PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu" \
  -e PHENIKAA_OIDC_ISSUER="https://identity.example.edu" \
  -e PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar" \
  -e PHENIKAA_OIDC_CLIENT_SECRET="..." \
  ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server
```

The image listens on `0.0.0.0:8416`, stores state in `/data`, runs as unprivileged user, includes managed Chromium.

## Documentation Sources

- `docs/USAGE.md` — CLI reference and date range guidance
- `docs/SERVER.md` — Server deployment and Google Calendar sync
- `docs/AUTHENTICATION.md` — Authentication methods
- `docs/API_PROTOCOL.md` — Internal API protocol
- `SECURITY.md` — Security and privacy practices
