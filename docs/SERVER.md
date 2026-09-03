# Server and Docker Deployment

[Back to the README](../README.md)

Server mode keeps one Phenikaa account session per OIDC-authenticated user, encrypts captured JWTs in SQLite, refreshes tokens through the retained portal cookies, and writes that session's JSON and ICS exports.

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

On upgrade, SQLite keeps each application user's oldest Phenikaa session row and deletes later duplicate rows before enforcing the one-session limit. Database child rows such as sync history, Google connections, Google calendar state, and Google event links are removed through foreign-key cascading with the deleted duplicate session rows. Existing duplicate browser profiles or export directories are not migrated because the database cannot safely identify filesystem ownership beyond the deleted session IDs.

Set `PHENIKAA_POLICY_CONTACT` to the operator contact shown on the public Privacy Policy and Terms of Service pages. These pages do not require app authentication and are suitable for OAuth consent-screen links:

```text
${PHENIKAA_SERVER_BASE_URL}/privacy
${PHENIKAA_SERVER_BASE_URL}/terms
```

## Optional Google Calendar sync

Google Calendar integration is server-only and does not change the CLI. It performs one-way sync from Phenikaa to a dedicated Google calendar created by this app named `Phenikaa Learning Calendar`. Sync creates new linked events, updates previously linked events, and deletes stale app-owned linked events that disappeared from the Phenikaa range inside that dedicated calendar. Unrelated Google Calendar events are not touched. Calendar selection, two-way sync, and Google webhooks are not implemented.

If the dedicated Google calendar is deleted outside this service, the next sync detects the missing persisted calendar, creates and persists a replacement, and recreates linked Phenikaa events in the replacement calendar.

Servers upgraded from the earlier primary-calendar sync keep their stored legacy event links until migration finishes. On the first successful sync after upgrade, the server creates and persists the dedicated calendar ID, GET-verifies each stored primary event still carries this app's private source marker before DELETE, removes absent 404/410 primary links locally, and retries remaining stored primary links on later syncs if Google returns a transient error. Fresh Google connections do not call the primary calendar.

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

Fresh Google connections request only `https://www.googleapis.com/auth/calendar.app.created`. Sessions upgraded from the earlier primary-calendar sync request temporary `https://www.googleapis.com/auth/calendar.events` in addition to app-created scope only while primary cleanup is pending, so the server can GET-verify the app private marker and delete its previously linked primary-calendar events once. After verified cleanup and dedicated-calendar reconcile, the broad legacy token is revoked locally and at Google; the user reconnects app-only for ongoing sync. After the server starts, open the dashboard and use the session's `Connect` link under `Google Calendar`. The OAuth callback stores encrypted access and refresh tokens for the exact requested scope, then requests an immediate sync. Use `Disconnect Google` to revoke the Google token and remove the local Google connection.

Legacy Google connections authorized before the dedicated-calendar change may need to reconnect once so Google grants `calendar.app.created` before migration can create the dedicated calendar.

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
