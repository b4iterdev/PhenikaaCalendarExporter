# Security and privacy

## Sensitive values

The portal's authenticated bootstrap data contains:

- `userId`: the portal's internal user identifier.
- `tokenJWT`: a bearer token that authorizes API calls as the logged-in user.
- Calendar output: course enrollment, room, lecturer, attendance and exam information.

Treat the token exactly like a password while it is valid. The exporter never logs or prints it.

## Required practices

1. Never commit `.auth.json`, saved authenticated HTML, Chromium cache files, or generated exports.
2. Keep authentication files readable only by your account: `chmod 600 .auth.json`.
3. Delete saved bootstrap HTML and copied cache data after extracting/exporting.
4. If a token appears in a terminal transcript, issue, chat, or repository, log out of the portal and sign in again to invalidate/replace the session.
5. Only use the exporter for an account you are authorized to access.

## What the project stores

The command-line exporter writes only the requested JSON, XLSX and ICS files. It does not save the bearer token unless `--browser-login` is used, which writes the documented private `.auth.json`. `--cache-dir` keeps the decoded session in process memory only.

Server mode intentionally persists more sensitive state under `server-state/`:

- JWTs are encrypted in SQLite with the Fernet key supplied through `PHENIKAA_SERVER_KEY`.
- Per-session Playwright profiles contain live Phenikaa cookies used for silent token refresh.
- JSON and ICS exports contain private academic data.
- Optional Google Calendar connections store encrypted access and refresh tokens in SQLite using the same server Fernet key.
- Google event links are retained after disconnect so reconnecting can update existing app-owned events without duplicating them; upgraded primary-calendar links are retained only until their one-time cleanup succeeds.
- A 0600 random secret signs OIDC transactions and application cookies.

The authenticated one-shot web export is separate from retained server sessions. Pasted bootstrap HTML or manually entered `userId` and `tokenJWT` values remain in process memory only for that request. Temporary JSON, XLSX and ICS files are created in an isolated temporary directory, returned under fixed names in a ZIP response with `Cache-Control: no-store`, and removed when the request finishes. The flow does not write credentials to SQLite or a browser profile and does not call Google Calendar or the background sync engine. The request requires application authentication and CSRF validation and is limited to 1 MiB.

Protect and back up the Fernet key separately. Losing it makes stored JWTs and Google tokens unreadable; exposing it allows their decryption. Deleting a session through the dashboard removes its database row, browser profile, exports, Google connection, and retained Google event links. Disconnecting Google revokes the Google token and deletes the local token connection, but keeps event links for safe reconnect/no duplication. Deleting `server-state/` wipes all local server data.

Run the server behind HTTPS, keep its direct listener private, and configure a generic OIDC provider. Never expose `PHENIKAA_SERVER_AUTH=disabled`. `PHENIKAA_BROWSER_NO_SANDBOX=1` weakens Chromium isolation and is only appropriate inside another trusted sandbox such as a locked-down container.

## Network behavior

The normal command sends one authenticated POST request to:

`https://qldtbeta.phenikaa-uni.edu.vn/sinhvienapi3/api/SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv`

The command-line exporter does not send credentials or calendar data to third-party services. Server mode contacts the configured OIDC provider for sign-in. When, and only when, a session is connected to Google Calendar, the server sends outbound Google OAuth and Calendar API requests to exchange/refresh/revoke tokens, create a dedicated app calendar, and create, update, or delete that session's linked events in that dedicated calendar. Upgraded legacy connections may also GET-verify and delete only stored primary-calendar event IDs whose private app marker matches before revoking the temporary broad token.
