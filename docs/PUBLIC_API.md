# Phenikaa Calendar Exporter — Public API v1

## Base URL

Use the base URL where the Phenikaa Calendar Exporter server is deployed.
All API responses are non-cacheable (`Cache-Control: no-store`).

## Authentication

Protected endpoints use:

`Authorization: Bearer <token>`

Create a token while signed in to the web application:

`POST /api/v1/tokens`

Send a JSON body with `name` and `scopes`, and include the authenticated
application session cookie plus a valid `X-CSRF-Token` header.

The token secret is returned only once. Store it securely. The database stores
a SHA-256 hash rather than the raw token. Revoked tokens can no longer be used.

Supported scopes:

- `me:read`
- `tokens:read`
- `tokens:write`
- `sessions:read`
- `sessions:write`
- `events:read`
- `sync:write`

## Response format

Successful JSON responses use:

`{"ok": true, "data": {...}}`

Errors use:

`{"ok": false, "error": {"code": "...", "message": "..."}}`

Some errors add an optional `details` object, for example
`{"ok": false, "error": {"code": "conflict_running", "message": "...", "details": {"runId": 12}}}`.
Unknown `/api/v1/` routes return `404` with the same envelope.

## Health and service status

- `GET /api/v1/health` — public health check.
- `GET /api/v1/status` — public service status; cached for 15 seconds.
- `GET /api/v1/status?refresh=1` — force a status refresh.
- `GET /api/v1/openapi.json` — OpenAPI 3.1 specification.

## One-shot calendar export

`POST /api/v1/export/one-shot?format=json`

This endpoint does not create a persistent session or request Google Calendar
authorization. The request body must be JSON and must be at most 1 MiB.

Example:

`{"start":"2026-09-01","end":"2027-01-31","userId":"YOUR_USER_ID","tokenJWT":"YOUR_CURRENT_TOKEN"}`

Provide either `bootstrapHtml` or both `userId` and `tokenJWT`. Dates accept
`YYYY-MM-DD` or `DD/MM/YYYY`.

Supported `format` values:

- `json` (default): summary and event data in JSON.
- `ics`: calendar file download.
- `xlsx`: spreadsheet download.
- `zip`: JSON, ICS, and XLSX files in one archive.

The one-shot endpoint is rate-limited to 10 requests per minute per client IP.
It does not persist the supplied Phenikaa credentials.

## API tokens

- `POST /api/v1/tokens` — create a token using the browser session and CSRF.
- `GET /api/v1/tokens` — list tokens (`tokens:read`).
- `POST /api/v1/tokens/{tokenId}/revoke` — revoke a token (`tokens:write`).
- `GET /api/v1/me` — token owner information (`me:read`).

## Sessions

- `GET /api/v1/sessions` — list the current token owner's sessions.
- `POST /api/v1/sessions` — create a session (`sessions:write`).
- `GET /api/v1/sessions/{sessionId}` — get session information.
- `PATCH /api/v1/sessions/{sessionId}` — update label, date range, or sync interval.
- `DELETE /api/v1/sessions/{sessionId}?calendar=keep|hide|delete` — delete a session and clean up its resources (`sessions:write`).

Session creation and updates accept JSON fields `label`, `rangeStart`, `rangeEnd`,
and `syncIntervalHours`. Sync interval must be between 0.25 and 720 hours.

The API only exposes sessions owned by the authenticated token owner.

Sessions created through the API start as `pending_login`. The Phenikaa sign-in
itself still happens in the web application at `/sessions/{sessionId}/login`.
Until the owner has signed in there, sync requests return `409 login_required`.

`DELETE` keeps the owner's Google calendar by default (`calendar=keep`).
`calendar=hide` removes it from the owner's calendar list, and `calendar=delete`
permanently deletes the calendar and its events. Any other value returns
`400 invalid_request` and nothing is deleted. If a sync or sign-in is holding the
session, the request returns `409 conflict_running`; the session is already
disabled at that point, so retry shortly.

## Events, exports, and sync history

- `GET /api/v1/sessions/{sessionId}/events?start=YYYY-MM-DD&end=YYYY-MM-DD`
  — filter events from the latest stored calendar JSON export.
- `GET /api/v1/sessions/{sessionId}/exports` — list available stored exports.
- `GET /api/v1/sessions/{sessionId}/exports/{filename}`
  — download `calendar.json`, `calendar.ics`, or `calendar.xlsx` (`events:read`).
- `POST /api/v1/sessions/{sessionId}/sync` — queue a sync and return its run id (`sync:write`).
- `GET /api/v1/sessions/{sessionId}/sync/runs` — list recent sync runs.
- `GET /api/v1/sessions/{sessionId}/sync/runs/{runId}` — get a sync run.

A successful sync request returns `202` with
`{"ok": true, "data": {"runId": 12, "status": "running"}}`. The sync runs in the
background; poll the run endpoint until `status` is `succeeded` or `failed`.
Possible errors:

- `409 login_required` — the owner has not signed in to Phenikaa yet.
- `409 session_disabled` — the session is disabled.
- `409 conflict_running` — a sync is already running; `error.details.runId` is that run.
- `429 rate_limited` — the previous run finished less than 60 seconds ago.
- `503 sync_unavailable` — the sync could not be queued.

`calendar.xlsx` is generated from the latest `calendar.json` the first time it is
requested, and regenerated after a newer sync. It appears in the export listing
once a sync has stored at least one event. Without a stored export, or when the
export has no events, the download returns `404 not_found`.

## Rate limits

- One-shot export: 10 requests per minute per client IP.
- Authenticated endpoints: 60 requests per minute per token.
- Sync: one sync per session at a time, and at least 60 seconds after the previous run finished.

Limited requests return `429` with `error.code` set to `rate_limited`, a
`Retry-After` header, and `error.details.retryAfter` in seconds. Counters are
kept in server memory and reset when the server restarts.

When the server runs behind a reverse proxy, set `PHENIKAA_SERVER_TRUSTED_PROXIES`
to a comma-separated list of the proxy addresses (default `127.0.0.1,::1`). Only
requests whose direct peer is in that list may supply the client address through
`CF-Connecting-IP` or `X-Forwarded-For`; the last `X-Forwarded-For` entry, which
the proxy appends, is the one used.

## Common HTTP errors

- `400` — invalid request, date, format, or scope.
- `401` — missing, invalid, or expired authentication.
- `403` — insufficient scope or invalid CSRF.
- `404` — resource not found or not owned by the caller.
- `409` — conflict: session already exists, sync already running, login required, or session disabled.
- `413` — request body too large.
- `429` — rate limit exceeded (see the `Retry-After` header).
- `502` — upstream export or cleanup failure.
- `503` — sync could not be queued.

## OpenAPI

The machine-readable specification is served at `/api/v1/openapi.json`.
The source definition lives in `server/api_v1.py`.

## Operations notes

- Run a single server process. The rate-limit counters, the sync queue and the
  cleanup of unfinished sync runs at startup all assume one process.
- Keep `PHENIKAA_SERVER_KEY` unchanged. Stored Phenikaa and Google credentials are
  encrypted with it and become unreadable if it changes. API tokens only store
  SHA-256 hashes, so they do not depend on it.
- Browser profiles under `profiles/` are created when an owner signs in through the
  web application and can use much more disk space than the exports. Monitor the
  size of the state directory.
- Never log `Authorization` headers, `tokenJWT` or `bootstrapHtml`.
- Sync runs left unfinished by a crash or restart are marked as failed at startup.
