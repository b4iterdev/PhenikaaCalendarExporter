# Phenikaa Calendar Exporter

A reproducible command-line project that reads the authenticated Phenikaa student-calendar API and exports:

- `.xlsx` - formatted Excel calendar plus summary sheet.
- `.ics` - timezone-aware calendar import for Apple Calendar, Google Calendar and Outlook.
- `.json` - normalized source records for auditing and future processing.

Server mode can optionally connect a session to Google Calendar for one-way Phenikaa-to-Google sync into a dedicated app-created calendar; see [Server and Docker deployment](docs/SERVER.md).

The project does not store passwords or enter credentials on your behalf. It reads session data from your own authenticated browser.

## Requirements

- Python 3.9 or newer.
- Network access to `qldtbeta.phenikaa-uni.edu.vn`.
- A currently authenticated Phenikaa portal session.
- `openpyxl` 3.1.5 for Excel output.
- Optional `playwright` and Chromium for automated browser login.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
```

Without installation, invoke `python phenikaa_exporter.py ...` directly.

## Documentation

- [Usage and CLI reference](docs/USAGE.md)
- [Authentication methods](docs/AUTHENTICATION.md)
- [Server and Docker deployment](docs/SERVER.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Internal API protocol](docs/API_PROTOCOL.md)
- [Security guidance](SECURITY.md)

## Tests

```bash
python -m unittest discover -s tests -v
```

## Known limitations

- The API is internal and may change without notice.
- Authentication expires; the project never stores passwords or types credentials.
- “Current semester” is represented by an explicit broad date range, not official semester metadata.
- Generated exports contain private academic information and are ignored by Git by default.

## Verification

The API workflow was verified against the logged-in student portal on 26 August 2026. A current-semester request returned 70 events covering 4 August–28 October 2026: 65 classes and 5 exams. Tests cover encryption/decryption, browser-cache extraction, login capture, API exchange, deduplication, XLSX, ICS, UTF-8 folding, and CLI output.
