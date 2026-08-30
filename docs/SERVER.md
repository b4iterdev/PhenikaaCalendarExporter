# Server and Docker Deployment

[Back to the README](../README.md)

Server mode keeps separate browser profiles for OIDC-authenticated users, encrypts captured JWTs in SQLite, refreshes tokens through retained portal cookies, and writes each session’s JSON and ICS exports.

## Configuration

```bash
python -m pip install -e "[server]"
playwright install chromium
export PHENIKAA_SERVER_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu"
export PHENIKAA_POLICY_CONTACT="Calendar operations <calendar-ops@example.edu>"
export PHENIKAA_OIDC_ISSUER="https://identity.example.edu"
export PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar"
export PHENIKAA_OIDC_CLIENT_SECRET="..."
phenikaa-calendar-server --host 127.0.0.1 --port 8416
```

Register `${PHENIKAA_SERVER_BASE_URL}/auth/callback` with the OIDC provider. The provider must expose standard discovery metadata and RS256 JWKS keys. Use `client_secret_basic` for the token endpoint authentication method.

Keep `PHENIKAA_SERVER_KEY` unchanged for the lifetime of the state directory. State includes `server.db`, browser profiles, exports, and `cookie.secret`.

Set `PHENIKAA_POLICY_CONTACT` to the operator contact shown on the public Privacy Policy and Terms of Service pages. These pages do not require app authentication and are suitable for OAuth consent-screen links:

```text
${PHENIKAA_SERVER_BASE_URL}/privacy
${PHENIKAA_SERVER_BASE_URL}/terms
```

## Optional Google Calendar sync

Google Calendar integration is server-only and does not change the CLI. It performs one-way sync from Phenikaa to the connected user's Google primary calendar. Sync creates new linked events, updates previously linked events, and deletes stale app-owned linked events that disappeared from the Phenikaa range. Unrelated Google Calendar events are not touched. Calendar selection, two-way sync, and Google webhooks are not implemented.

To enable it:

1. In Google Cloud, enable the Google Calendar API for the project.
2. Configure the OAuth consent screen. If the app is in testing, add every operator/user account as a test user.
3. Create an OAuth client with application type `Web application`.
4. Register `PHENIKAA_GOOGLE_REDIRECT_URI` as an authorized redirect URI. This is normally `${PHENIKAA_SERVER_BASE_URL}/auth/google/callback`.
5. Export the Google OAuth settings before starting the server:

```bash
export PHENIKAA_GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export PHENIKAA_GOOGLE_CLIENT_SECRET="..."
export PHENIKAA_GOOGLE_REDIRECT_URI="${PHENIKAA_SERVER_BASE_URL}/auth/google/callback"
```

The requested Google scope is exactly `https://www.googleapis.com/auth/calendar.events`. After the server starts, open the dashboard and use each session's `Connect` link under `Google Calendar`. The OAuth callback stores encrypted access and refresh tokens, then requests an immediate sync. Use `Disconnect Google` to revoke the Google token and remove the local Google connection.

## Docker

The image listens on `0.0.0.0:8416`, stores state in `/data`, runs as an unprivileged user, and includes managed Chromium.

```bash
docker run -d --name phenikaa-calendar \
  -p 8416:8416 -v phenikaa-data:/data \
  -e PHENIKAA_SERVER_KEY="..." \
  -e PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu" \
  -e PHENIKAA_OIDC_ISSUER="https://identity.example.edu" \
  -e PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar" \
  -e PHENIKAA_OIDC_CLIENT_SECRET="..." \
  -e PHENIKAA_GOOGLE_CLIENT_ID="...apps.googleusercontent.com" \
  -e PHENIKAA_GOOGLE_CLIENT_SECRET="..." \
  -e PHENIKAA_GOOGLE_REDIRECT_URI="https://calendar.example.edu/auth/google/callback" \
  ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server
```

GitHub Actions publishes multi-architecture images for `linux/amd64` and `linux/arm64`:

```text
ghcr.io/b4iterdev/phenikaa-calendar-exporter:main
ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server
ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server-<sha>
ghcr.io/b4iterdev/phenikaa-calendar-exporter:latest
```

Keep one server replica because SQLite, browser profiles, and filesystem state are local. Configure the reverse proxy with limits and timeouts suitable for long-lived login streams, and do not log `/auth/callback` or `/auth/google/callback` query strings.
