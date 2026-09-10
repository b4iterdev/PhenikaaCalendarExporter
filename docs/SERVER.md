# Server and Docker Deployment

[Back to the README](../README.md)

Server mode keeps one Phenikaa account session per authenticated user, encrypts captured JWTs in SQLite, refreshes tokens through the retained portal cookies, and writes that session's JSON and ICS exports. App login can use an external OIDC provider (default) or Google directly.

The public home page offers one-shot export and links to the configured login. After login, the dashboard manages retained Phenikaa sessions and Google Calendar sync.

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

## Google login mode

Set `PHENIKAA_SERVER_AUTH=google` to use Google for both app sign-in and the Calendar destination. The existing `oidc` mode remains the default; `disabled` is for local development only. Unknown auth modes are rejected at startup.

Configure a Google **Web application** OAuth client, enable the Google Calendar API, and register the exact callback below. Keep the server encryption key and state volume stable, and serve the application over HTTPS (session cookies are Secure).

```bash
export PHENIKAA_SERVER_AUTH="google"
export PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu"
export PHENIKAA_GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export PHENIKAA_GOOGLE_CLIENT_SECRET="..."
export PHENIKAA_GOOGLE_REDIRECT_URI="${PHENIKAA_SERVER_BASE_URL}/auth/google/callback"
# Keep your existing PHENIKAA_SERVER_KEY and PHENIKAA_POLICY_CONTACT settings.
phenikaa-calendar-server --host 127.0.0.1 --port 8416
```

No `PHENIKAA_OIDC_*` settings are required in this mode. For Docker, add `-e PHENIKAA_SERVER_AUTH=google` to the example below and omit the three OIDC settings.

The user selects **Sign in with Google**, grants Calendar permission, and then connects their Phenikaa account. The destination is automatically the **same Google account**, with events in the dedicated **Phenikaa Learning Calendar**, not the primary calendar. No separate Google connection step is needed when permission and offline access were granted. Google authentication still uses OAuth/OIDC, but no separate identity-provider deployment is required.

The combined authorization requests `openid email profile` and `https://www.googleapis.com/auth/calendar.app.created`, with offline access. Calendar permission can be declined without preventing app login; the dashboard then shows **Authorize Google Calendar**. The same action recovers missing refresh credentials or revoked access. Reauthorization checks the verified Google subject, not just email or an account-picker hint. Ordinary logins reuse existing refresh credentials and do not force a fresh consent screen.

Google grants are encrypted and owned by the application user, so they exist before a Phenikaa session is created. **Pause calendar sync** does not revoke Google login, and **Resume calendar sync** resumes the saved destination. Signing out does not stop scheduled sync. Deleting a Phenikaa session removes its exports, profile, calendar state, and event links but retains the user-level Google grant; recreating a session can create a new dedicated calendar. Deleting the application account revokes its Google grant, including when no Phenikaa session exists, and removes the local account. Existing events/calendars are not deleted by account deletion.

Existing OIDC identities and session-bound Google connections are not automatically linked or migrated by matching email. Switching an existing deployment to Google mode creates separate Google app accounts; existing OIDC data remains stored and is available again in OIDC mode. Use a separate state directory if you want isolated deployments.

For external OAuth projects in **Testing**, refresh tokens with Calendar access generally expire after seven days. Configure publishing status and any verification required by Google before relying on unattended production sync. Users may still need to reauthorize if access is revoked or expires. See [Google's web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server).

## One-shot web export

The public home page provides **Public export** without requiring an account. After authentication, the dashboard provides the retained-session management tools and can also offer **Download without syncing**, which accepts exactly one Phenikaa authentication source:

- Paste a saved authenticated `index.aspx` response containing `AXYZCLRVN`.
- Enter both the portal `userId` and raw `tokenJWT` manually.

Here, “bootstrap HTML” means the authenticated portal response, not the Bootstrap CSS framework. Submitted credentials remain in process memory only for that request; the server does not add them to SQLite, retain the HTML, create a browser profile, request a background sync, or contact Google. The request uses the signed public export token or the normal application CSRF token as appropriate. The response is `phenikaa-calendar-export.zip` containing `calendar.json`, `calendar.xlsx`, and `calendar.ics`, with `Cache-Control: no-store`. The form body is limited to 1 MiB.

Saved HTML and JWTs are bearer credentials. Do not share them, and delete saved HTML after export.

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
