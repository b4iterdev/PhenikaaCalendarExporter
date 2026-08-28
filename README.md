# Phenikaa Calendar Exporter

A reproducible command-line project that reads the authenticated Phenikaa student-calendar API and exports:

- `.xlsx` — formatted Excel calendar plus summary sheet.
- `.ics` — timezone-aware calendar import for Apple Calendar, Google Calendar and Outlook.
- `.json` — normalized source records for auditing and future processing.

The project does **not** store a password and never enters credentials on your behalf. You sign in through the official portal yourself; the exporter only reads the session data your own logged-in browser already receives.

## What was verified

The API workflow was verified against the logged-in student portal on 26 August 2026. A current-semester request returned 70 events covering 4 August–28 October 2026: 65 classes and 5 exams. The committed tests also exercise encryption/decryption, Chromium-cache extraction, automated-login capture helpers (bootstrap-response decoding and `Authorization`-header parsing), a local end-to-end API exchange, deduplication, XLSX structure, ICS timezone/event structure, UTF-8 line folding, and the CLI's three-file output.

## Requirements

- Python 3.9 or newer.
- Network access to `qldtbeta.phenikaa-uni.edu.vn`.
- A currently authenticated Phenikaa portal session.
- `openpyxl` 3.1.5 for Excel output.
- Optional: `playwright` (plus its Chromium build) for the automated browser login.

## Setup

```bash
cd /path/to/PhenikaaCalendarExporter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

Optional editable installation, which creates the `phenikaa-calendar` command:

```bash
python -m pip install -e .
```

Without installation, invoke `python phenikaa_exporter.py ...` directly.

## Server mode

Server mode keeps separate Phenikaa browser profiles for OIDC-authenticated users, encrypts captured JWTs in SQLite, refreshes expired tokens through retained portal cookies, and writes each session's `calendar.json` and `calendar.ics` daily. Users can configure the calendar date range from the dashboard.

Install and configure it behind an HTTPS reverse proxy:

```bash
python -m pip install -e ".[server]"
playwright install chromium

export PHENIKAA_SERVER_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu"
export PHENIKAA_OIDC_ISSUER="https://identity.example.edu"
export PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar"
export PHENIKAA_OIDC_CLIENT_SECRET="..."

phenikaa-calendar-server --host 127.0.0.1 --port 8416
```

Register `${PHENIKAA_SERVER_BASE_URL}/auth/callback` as the OIDC redirect URI. The provider must expose standard discovery metadata and RS256 JWKS keys. OIDC identities are keyed by the stable `sub` claim.

Private state defaults to `server-state/`:

- `server.db` stores users, sessions, encrypted JWTs, and sync history.
- `profiles/<session-id>/` stores live Phenikaa cookies for silent token refresh.
- `exports/<session-id>/` stores the latest JSON and ICS files.
- `cookie.secret` signs application and OIDC transaction cookies.

The default sync interval is 24 hours. Set `PHENIKAA_SERVER_SYNC_INTERVAL_HOURS` to change it. The HTTPS reverse proxy must apply per-IP request limits, connection limits, body-size limits, and timeouts for long-lived login streams; configure it not to log `/auth/callback` query strings. In a container that cannot use Chromium's sandbox, `PHENIKAA_BROWSER_NO_SANDBOX=1` is available only for an otherwise trusted, isolated deployment. For local development, `PHENIKAA_SERVER_AUTH=disabled` bypasses OIDC and must never be exposed to a network.

### Docker deployment

The [`Dockerfile`](Dockerfile) builds a self-contained server image: Python 3.12, the package installed from source, and a managed Chromium under `/opt/ms-playwright` for streamed logins and silent token refresh. It runs as an unprivileged `phenikaa` user, stores all private state in the `/data` volume, listens on `0.0.0.0:8416`, and ships a `/healthz`-based `HEALTHCHECK`. Containers cannot use Chromium's sandbox, so the image sets `PHENIKAA_BROWSER_NO_SANDBOX=1` — keep the deployment otherwise isolated as documented above.

```bash
docker build -t phenikaa-calendar-server .

docker run -d --name phenikaa-calendar \
  -p 8416:8416 \
  -v phenikaa-data:/data \
  -e PHENIKAA_SERVER_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  -e PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu" \
  -e PHENIKAA_OIDC_ISSUER="https://identity.example.edu" \
  -e PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar" \
  -e PHENIKAA_OIDC_CLIENT_SECRET="..." \
  phenikaa-calendar-server
```

Generate the Fernet key once and reuse it for the lifetime of the `/data` volume; changing it makes every stored session token undecryptable. The `/data` volume holds `server.db`, browser profiles with live portal cookies, and exports — treat its contents and its backups as secrets.

A GitHub Actions workflow (`.github/workflows/docker.yml`) runs the offline test suite and then builds the image on every push or pull request touching the server code, the `Dockerfile`, or the workflow itself. On pushes (and manual dispatches) it publishes to GHCR:

- `ghcr.io/b4iterdev/phenikaa-calendar-exporter:main` / `:dev-server` — branch tag
- `ghcr.io/b4iterdev/phenikaa-calendar-exporter:main-<sha>` / `:dev-server-<sha>` — immutable commit tag
- `ghcr.io/b4iterdev/phenikaa-calendar-exporter:latest` — default branch only

Pull requests build the image but skip publishing, so forks and external contributors never need registry credentials.

## Quick start

Every command you need, in order:

```bash
# 1. One-time setup
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

# 2. One-time browser-login support (optional but recommended)
python -m pip install -e ".[login]"
playwright install chromium        # downloads the managed Chromium (~170MB)

# 3. Export with automated sign-in — a window opens, you sign in once
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --browser-login \
  --out-dir exports

# 4. Later reruns while the captured token is still valid (no sign-in)
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --auth-json .auth.json \
  --out-dir exports

# 5. Run the test suite at any time
python -m unittest discover -s tests -v
```

### Command-line options reference

Exactly one authentication source is required; everything else is optional.

| Option | Purpose |
|---|---|
| `--browser-login` | Open a sign-in window, capture credentials into `.auth.json`, then export immediately |
| `--auth-json PATH` | Read credentials from an existing JSON file (default target: `.auth.json`) |
| `--bootstrap-html PATH` | Decode credentials from a saved authenticated `index.aspx` response |
| `--cache-dir PATH` | Recover credentials from a Chromium disk cache (`Cache_Data`) |
| `--start YYYY-MM-DD` | Inclusive range start (required) |
| `--end YYYY-MM-DD` | Inclusive range end (required) |
| `--out-dir DIR` | Output directory (default: `exports`) |
| `--prefix NAME` | Output filename prefix (default: `phenikaa_calendar`) |
| `--calendar-name NAME` | Calendar display name written into the ICS |

## Recommended authentication method: automated browser login

The exporter can open its own Chromium window at the portal. You sign in once; `userId` and `tokenJWT` are captured automatically from the page's own network traffic — no DevTools, no copying.

One-time setup:

```bash
python -m pip install -e ".[login]"
playwright install chromium
```

Then run with `--browser-login` (dates as usual):

```bash
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --browser-login \
  --out-dir exports
```

How it works: a headed Chromium window opens at `index.aspx#lichhoc`. Sign in normally. The exporter watches responses for the server-rendered `AXYZCLRVN` bootstrap blob and decodes it, falling back to in-page `window.edu.system.userId` evaluation and the `Authorization` header of calendar API requests. Once both values are captured it writes `.auth.json` (permissions 600) and continues straight into the export. Tokens are never printed.

A persistent profile in `.browser-profile/` keeps you signed in between runs; while the portal session is valid, later runs skip the sign-in entirely. The directory is ignored by Git because it contains live session cookies. Delete it whenever you want to force a fresh sign-in.

### Troubleshooting browser login

| Symptom | Fix |
|---|---|
| `playwright is required for --browser-login` | Run `python -m pip install -e ".[login]"` then `playwright install chromium`. |
| Browser fails to launch on Linux (missing libraries) | Run `playwright install-deps chromium`, then retry. |
| `timed out waiting for sign-in` (5 minutes) | Rerun the command and finish signing in sooner; the window stays open until capture succeeds or the timeout hits. |
| Sign-in window appears but asks for login every run | The profile is stale — delete `.browser-profile/` and run again. |
| Export fails with HTTP `401` after a successful earlier run | The portal rotated your token; simply rerun with `--browser-login` to refresh `.auth.json`. |
| Window opens behind other windows | Look for a Chromium window titled like the Phenikaa portal; bring it forward and sign in there. |

### Security notes for generated files

- `.auth.json` is written automatically with permissions `600` and contains your bearer token. It is git-ignored; never commit it, paste it into chat, or screenshot it.
- `.browser-profile/` holds **live portal session cookies** — treat it like a password. Deleting the directory signs you out locally and forces a fresh sign-in next run.
- Exports in `exports/` contain private academic information and are git-ignored by default.

## Alternative authentication methods

### Local Chromium cache

1. Open the portal and sign in normally:
   `https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx#lichhoc`
2. Wait until the learning calendar is visible.
3. Run the exporter against the cache used by that browser.

For the Hermes preview pane on macOS:

```bash
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --cache-dir "$HOME/Library/Application Support/Hermes/Partitions/hermes-preview/Cache/Cache_Data" \
  --out-dir exports \
  --prefix current_semester
```

The cache is read locally. The decoded token remains in process memory and is never printed or written by the exporter.

### Saved authenticated HTML

Save the authenticated `index.aspx` response locally and run:

```bash
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --bootstrap-html /private/path/authenticated-index.html \
  --out-dir exports
```

The HTML must contain `AXYZCLRVN = () => "..."`. A login page or DOM copy without that server-rendered script will not work. Delete the file after use because it contains a bearer token.

### Private authentication JSON

#### Get `userId` with DevTools

1. Sign in and keep the authenticated portal page open.
2. Open **DevTools → Console**.
3. Run:

```js
window.edu?.system?.userId;
```

The result is the portal's internal student identifier, normally a 32-character hexadecimal string. Copy it without displaying it again with:

```js
copy(window.edu.system.userId);
```

If `edu.system.userId` is not initialized, reload the authenticated `index.aspx` page, wait for it to finish loading, and try again. A fallback using the portal's own bootstrap decoder is:

```js
copy(JSON.parse(AD(AXYZCLRVN(), "AzzS")).userId);
```

This `userId` is used by the API as both `strQLSV_NguoiHoc_Id` and `strNguoiThucHien_Id`. It is not the visible student number and is not derived from the bearer token.

#### Get `tokenJWT` from the Network panel

1. Open **DevTools → Network** while signed in.
2. Reload the portal or open **Lịch học** so the calendar API runs.
3. Select an authenticated request, preferably the request ending in:

```text
/sinhvienapi3/api/SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv
```

4. Open **Headers → Request Headers**.
5. Find:

```text
Authorization: Bearer <token>
```

6. Copy only the text after `Bearer `. Do **not** include the word `Bearer` or the following space in `tokenJWT`.

If the browser hides the header value, right-click the request and use **Copy → Copy as cURL**, paste it only into a private local text editor, take the authorization header's value after the scheme name, and immediately delete the temporary text. Do not execute or share the copied cURL command because it contains an active credential.

#### Create `.auth.json`

Create `.auth.json` from `auth.example.json` using the two values:

```json
{
  "userId": "YOUR_32_CHARACTER_INTERNAL_USER_ID",
  "tokenJWT": "YOUR_TOKEN_WITHOUT_THE_BEARER_PREFIX"
}
```

JSON does not support comments or trailing commas. Protect and use the file:

```bash
chmod 600 .auth.json
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --auth-json .auth.json \
  --out-dir exports
```

`.auth.json` is ignored by Git. Never commit it, paste either value into chat, or include it in screenshots. The bearer token is short-lived; if the API returns HTTP `401`, sign in again and replace `tokenJWT` with the new value.

## Choosing the date range

`--start` and `--end` are inclusive and use ISO `YYYY-MM-DD`. The API itself expects `DD/MM/YYYY`; the exporter performs that conversion.

The calendar flow does not expose a semester ID. For “current semester,” request a broad date window covering the expected term. The output summary reports the actual first and last scheduled dates returned by the API.

Examples:

```bash
# Three months
python phenikaa_exporter.py --start 2026-08-01 --end 2026-10-31 --cache-dir "..." --out-dir exports

# Academic term spanning the year boundary
python phenikaa_exporter.py --start 2026-08-01 --end 2027-01-31 --cache-dir "..." --out-dir exports
```

## Output

For `--prefix current_semester`, the command writes:

```text
exports/current_semester.json
exports/current_semester.xlsx
exports/current_semester.ics
```

The command prints only a summary containing counts, returned date bounds and absolute output paths.

### Excel columns

Date, weekday, start/end time, class/exam type, course, section, room/online location, lecturer, teaching periods, session, attendance status and event ID. Exams receive a distinct fill color. The Summary sheet contains counts and per-course meeting totals.

### ICS behavior

- One `VEVENT` per normalized API record.
- Stable UID derived from the portal event ID.
- `Asia/Ho_Chi_Minh` timezone.
- Classes and exams receive `CLASS`/`EXAM` categories.
- Exams are prefixed with `Exam:` in the event title.
- UTF-8 content lines are folded to the RFC 5545 75-octet limit.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Install `.[server]` to execute server-mode tests; without that optional extra, unittest reports the server test module as skipped. The API tests use local HTTP servers and do not contact Phenikaa or require credentials. `BrowserLoginCaptureTests` covers the pure capture helpers used by `--browser-login` without launching a browser. A separate live smoke run is needed to prove that the current internal API contract and the interactive login flow still work.

## Internal protocol

See [docs/API_PROTOCOL.md](docs/API_PROTOCOL.md) for the endpoint, headers, request payload, XOR/Base64 encoding and response fields.

See [SECURITY.md](SECURITY.md) before handling tokens or sharing exports, and [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for expired sessions and portal changes.

## Known limitations

- The API is internal and may change without notice.
- Authentication expires; the project never stores passwords or types credentials for you — even `--browser-login` waits for you to sign in manually before capturing the resulting session.
- “Current semester” is represented by an explicit broad date range, not an official semester metadata endpoint.
- Generated exports contain private academic information and are ignored by Git by default.
