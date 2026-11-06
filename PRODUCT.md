# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Phenikaa University students (primary and only confirmed audience). Situation: they have an authenticated session on the Phenikaa student portal (`qldtbeta.phenikaa-uni.edu.vn`) and want their class/exam timetable in their calendar tool. Job: export the current semester's events as ICS/XLSX/JSON in one shot, or set up continuous one-way sync into their own Google Calendar. Confirmed 2026-10-29: no staff/admin audience; the developers API portal exists but its users are not a design audience.

## Product Purpose

Reads the authenticated Phenikaa student-calendar API and exports the student's schedule:

- `.ics` — timezone-aware import for Apple/Google/Outlook calendars
- `.xlsx` — formatted Excel calendar plus summary sheet
- `.json` — normalized records for auditing

Server mode adds: public home page with one-shot export, login (external OIDC or Google), a dashboard managing retained Phenikaa sessions, and optional one-way Phenikaa→Google sync into a dedicated app-created calendar ("Phenikaa Learning Calendar"), never the primary calendar. A CLI mode exists for direct local export.

Success (user-confirmed): a student exports their calendar unaided in under 2 minutes, with zero support requests.

## Positioning

The project never stores passwords and never enters credentials on the user's behalf — it reads session data from the user's own authenticated browser (or a brokered Playwright login). Google sync writes only to a dedicated app-created calendar, so the student's primary calendar is never touched. That trust posture is the claim a timetable-scraper alternative could not truthfully copy.

## Operating Context

- Deployed via k8s GitOps (Flux, repo `b4iterdev/cluster-config`): production `pca`, dev `pca-dev.b4iterdev.net.eu.org`, Web3 variant `pca-web3.b4iterdev.net.eu.org` (token-gated API credits on Celo mainnet; separate repo PhenikaaCalendarExporter-Web3).
- Auth modes: `oidc` (default), `google` (Google for both sign-in and Calendar destination), `disabled` (local dev only).
- One Phenikaa session per application user; sessions refresh via retained portal cookies, JWTs encrypted at rest (Fernet + SQLite).
- Operator contact surfaces on public `/privacy` and `/terms` pages (no auth) for OAuth consent screens.
- Frontend: server-rendered pages in `server/`, styled with Tailwind (`frontend/input.css` → `server/static/styles.css` via `npm run build`).
- Verification basis: API workflow verified against the live logged-in portal 2026-08-26 (70 events, 65 classes + 5 exams, 2026-08-04→10-28).

## Capabilities and Constraints

- The Phenikaa API is internal and may change without notice.
- "Current semester" is an explicit broad date range, not official semester metadata.
- Generated exports contain private academic information; gitignored by default.
- Server must run over HTTPS (session cookies are Secure); server key and state volume must stay stable across upgrades.
- No binding brand, bilingual, or accessibility constraints (user-confirmed 2026-10-29: free to restyle).

## Evidence on Hand

- Verified live API exchange (see Operating Context); test suite covering crypto, login capture, API exchange, dedup, XLSX/ICS output.
- Docs: `docs/USAGE.md`, `docs/AUTHENTICATION.md`, `docs/SERVER.md`, `docs/TROUBLESHOOTING.md`, `docs/API_PROTOCOL.md`, `SECURITY.md`.
- No testimonials, user counts, or adoption data — future design work must not fabricate any.

## Product Principles

1. Unaided success: a student completes the export first-visit, unassisted, in minutes — every screen is accountable to that.
2. Trust by behavior: never store passwords, never type credentials, never touch the student's primary Google calendar; the UI states this plainly where trust decisions happen.
3. The internal API is unstable by nature; flows must degrade and explain (expired session, API change) instead of failing silently.
4. Private academic data stays private: exports are per-session artifacts, encrypted at rest, never committed.

## Accessibility & Inclusion

None established beyond defaults; no product-specific requirement was confirmed. Record one here when set.
