# Server & Docker Deployment Guide

The multi-user calendar server (`phenikaa-calendar-server`) coordinates background timetable polling, token refresh, and automatic Google Calendar synchronization.

---

## 1. Quick Start with Docker (Recommended)

Pre-built multi-architecture Docker images (`linux/amd64` and `linux/arm64`) are published to GitHub Container Registry:

```bash
# 1. Generate an encryption key
KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 2. Run the Docker container
docker run -d \
  --name phenikaa-calendar \
  --restart unless-stopped \
  -p 8416:8416 \
  -v phenikaa-data:/data \
  -e PHENIKAA_SERVER_KEY="$KEY" \
  -e PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu" \
  -e PHENIKAA_POLICY_CONTACT="admin@example.edu" \
  -e PHENIKAA_SERVER_AUTH="google" \
  -e PHENIKAA_GOOGLE_CLIENT_ID="YOUR_CLIENT_ID.apps.googleusercontent.com" \
  -e PHENIKAA_GOOGLE_CLIENT_SECRET="YOUR_CLIENT_SECRET" \
  -e PHENIKAA_GOOGLE_REDIRECT_URI="https://calendar.example.edu/auth/google/callback" \
  ghcr.io/b4iterdev/phenikaa-calendar-exporter:latest
```

---

## 2. Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `PHENIKAA_SERVER_KEY` | **Yes** | *None* | 32-byte Fernet key used to encrypt bearer tokens and refresh tokens in SQLite. |
| `PHENIKAA_SERVER_BASE_URL` | **Yes** | `http://127.0.0.1:8416` | Canonical public URL (e.g., `https://calendar.example.edu`). |
| `PHENIKAA_POLICY_CONTACT` | No | `the server operator` | Operator email/name displayed on `/privacy` and `/terms`. |
| `PHENIKAA_SERVER_AUTH` | No | `oidc` | Authentication strategy: `google`, `oidc`, or `disabled` (local dev only). |
| `PHENIKAA_SERVER_HOST` | No | `127.0.0.1` | Local IP address to bind. |
| `PHENIKAA_SERVER_PORT` | No | `8416` | TCP port to listen on. |
| `PHENIKAA_SERVER_STATE` | No | `server-state` | Local filesystem directory storing `server.db`, exports, and browser profiles. Set to `/data` in Docker. |
| `PHENIKAA_SERVER_SYNC_INTERVAL_HOURS`| No | `24` | Hours between automatic background synchronization runs. |
| `PHENIKAA_BROWSER_NO_SANDBOX` | No | `false` | Pass `--no-sandbox` to Chromium if running in unprivileged containers. |

---

## 3. Authentication Modes

### Mode 1: Integrated Google Login (`PHENIKAA_SERVER_AUTH=google`)
In this mode, users click **Sign in with Google**. The same Google identity is used to log in to the web app AND serves as the destination for the **Phenikaa Learning Calendar**.

#### Requirements:
1. In Google Cloud Console, enable the **Google Calendar API**.
2. Configure OAuth Consent Screen (add test users if app is in Testing mode).
3. Create OAuth Credentials of type **Web application**.
4. Set Authorized Redirect URI to:
   `${PHENIKAA_SERVER_BASE_URL}/auth/google/callback`
5. Supply:
   - `PHENIKAA_GOOGLE_CLIENT_ID`
   - `PHENIKAA_GOOGLE_CLIENT_SECRET`
   - `PHENIKAA_GOOGLE_REDIRECT_URI`

### Mode 2: External OIDC (`PHENIKAA_SERVER_AUTH=oidc`)
Used for university-wide single-sign-on (Keycloak, Authentik, Azure AD / Entra ID, Okta).
- Supply:
  - `PHENIKAA_OIDC_ISSUER`: Discovery URL (`https://identity.example.edu`).
  - `PHENIKAA_OIDC_CLIENT_ID`: OAuth client ID.
  - `PHENIKAA_OIDC_CLIENT_SECRET`: OAuth client secret.
  - `PHENIKAA_OIDC_REDIRECT_URI`: `${PHENIKAA_SERVER_BASE_URL}/auth/callback`.

---

## 4. State Storage Architecture (`/data`)

The server uses a persistent directory (`/data` inside Docker) structured as follows:

```text
/data/
├── server.db        # SQLite database containing users, sessions, Google links
├── cookie.secret    # Cryptographic secret for signing session cookies
├── secret.key       # (Optional fallback)
├── profiles/        # Subdirectories containing Chromium browser profiles
│   └── <session_id>/
└── exports/         # Cached .ics, .xlsx, .json static exports
    └── <session_id>/
```

> **Important**: Run exactly **one container replica**. The SQLite database, Playwright browser profiles, and sync locks are node-local. Do not scale horizontally across multiple instances unless using an external load-balancing proxy with sticky sessions.

---

## 5. Reverse Proxy Configuration (Nginx Example)

Session cookies use the `Secure` flag when served over HTTPS. Use this recommended Nginx reverse proxy configuration:

```nginx
server {
    listen 443 ssl http2;
    server_name calendar.example.edu;

    ssl_certificate /etc/letsencrypt/live/calendar.example.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/calendar.example.edu/privkey.pem;

    client_max_body_size 2M;

    location / {
        proxy_pass http://127.0.0.1:8416;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Keep alive settings for streaming Playwright login
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 600s;
    }

    # Security: Do not log sensitive OAuth callbacks
    location ~* ^/auth/(callback|google/callback) {
        proxy_pass http://127.0.0.1:8416;
        access_log off;
    }
}
```
