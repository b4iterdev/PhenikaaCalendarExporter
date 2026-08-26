# Phenikaa Calendar Exporter

A reproducible command-line project that reads the authenticated Phenikaa student-calendar API and exports:

- `.xlsx` — formatted Excel calendar plus summary sheet.
- `.ics` — timezone-aware calendar import for Apple Calendar, Google Calendar and Outlook.
- `.json` — normalized source records for auditing and future processing.

The project does **not** automate login or store a password. You sign in through the official portal, then provide a short-lived authenticated bootstrap source.

## What was verified

The API workflow was verified against the logged-in student portal on 26 August 2026. A current-semester request returned 70 events covering 4 August–28 October 2026: 65 classes and 5 exams. The committed tests also exercise encryption/decryption, Chromium-cache extraction, a local end-to-end API exchange, deduplication, XLSX structure, ICS timezone/event structure, UTF-8 line folding, and the CLI's three-file output.

## Requirements

- Python 3.9 or newer.
- Network access to `qldtbeta.phenikaa-uni.edu.vn`.
- A currently authenticated Phenikaa portal session.
- `openpyxl` 3.1.5 for Excel output.

## Setup

```bash
cd /Users/b4iterdev/PhenikaaCalendarExporter
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

## Recommended authentication method: local Chromium cache

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

## Alternative authentication sources

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

Create `.auth.json` from `auth.example.json`:

```json
{
  "userId": "...",
  "tokenJWT": "..."
}
```

Protect and use it:

```bash
chmod 600 .auth.json
python phenikaa_exporter.py \
  --start 2026-08-01 \
  --end 2027-01-31 \
  --auth-json .auth.json \
  --out-dir exports
```

`.auth.json` is ignored by Git. Never commit it.

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

The API test uses a local HTTP server and does not contact Phenikaa or require credentials. A separate live smoke run is needed to prove that the current internal API contract still works.

## Internal protocol

See [docs/API_PROTOCOL.md](docs/API_PROTOCOL.md) for the endpoint, headers, request payload, XOR/Base64 encoding and response fields.

See [SECURITY.md](SECURITY.md) before handling tokens or sharing exports, and [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for expired sessions and portal changes.

## Known limitations

- The API is internal and may change without notice.
- Authentication expires; the project intentionally does not capture credentials or automate Microsoft login.
- “Current semester” is represented by an explicit broad date range, not an official semester metadata endpoint.
- Generated exports contain private academic information and are ignored by Git by default.
