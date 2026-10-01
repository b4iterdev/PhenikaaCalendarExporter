# CLI Reference

The command-line interface `phenikaa_exporter.py` provides a standalone, scriptable tool to extract, decrypt, and export calendar records without running a web server.

---

## 1. Syntax Overview

```bash
python phenikaa_exporter.py \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  <AUTH_SOURCE> \
  [OUTPUT_OPTIONS]
```

Or, if installed with `pip install -e .`:

```bash
phenikaa-calendar-exporter \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  <AUTH_SOURCE> \
  [OUTPUT_OPTIONS]
```

---

## 2. Argument Reference

### 2.1. Date Range Arguments (Required)

| Flag | Format | Required | Description |
|---|---|---|---|
| `--start` | `YYYY-MM-DD` | **Yes** | Inclusive start date for the schedule query. |
| `--end` | `YYYY-MM-DD` | **Yes** | Inclusive end date for the schedule query. Must not be before `--start`. |

> **Tip**: Because the portal API does not accept semester IDs, provide a wide range covering the entire semester (e.g., `--start 2026-08-01 --end 2027-01-31`). The exporter will automatically detect all events within the range.

---

### 2.2. Authentication Source (Choose Exactly One)

Exactly one of the following four flags must be provided:

| Flag | Type | Description |
|---|---|---|
| `--browser-login` | Flag | Opens a Playwright-controlled Chromium window, waits for you to sign in manually, captures credentials into `.auth.json` (chmod 0600), and continues the export. |
| `--auth-json PATH` | File Path | Reads credentials from a JSON file formatted as `{"userId": "...", "tokenJWT": "..."}`. |
| `--bootstrap-html PATH` | File Path | Extracts and decodes credentials from a locally saved `index.aspx` (or `index.html`) page containing `AXYZCLRVN`. |
| `--cache-dir PATH` | Directory | Automatically scans a Chromium/Chrome disk cache directory for the newest authenticated bootstrap response. |

---

### 2.3. Output Options (Optional)

| Flag | Default | Description |
|---|---|---|
| `--out-dir DIR` | `exports` | Directory where output files will be written. Created automatically if it does not exist. |
| `--prefix NAME` | `phenikaa_calendar` | File name prefix for output files (e.g., `<prefix>.xlsx`, `<prefix>.ics`, `<prefix>.json`). |
| `--calendar-name NAME` | `Phenikaa Learning Calendar` | Calendar display name written into the ICS calendar header (`X-WR-CALNAME`). |

---

## 3. Machine-Readable Output

Upon successful completion, the CLI prints a structured JSON object to `stdout`:

```json
{
  "events": 70,
  "classes": 65,
  "exams": 5,
  "date_start": "2026-08-04",
  "date_end": "2026-10-28",
  "json": "/Users/user/PhenikaaCalendarExporter/exports/phenikaa_calendar.json",
  "xlsx": "/Users/user/PhenikaaCalendarExporter/exports/phenikaa_calendar.xlsx",
  "ics": "/Users/user/PhenikaaCalendarExporter/exports/phenikaa_calendar.ics"
}
```

Informational messages, progress warnings, and credential notifications are sent strictly to `stderr`, making stdout completely safe for piping into tools like `jq`.

---

## 4. Exit Codes & Error Handling

| Exit Code | Condition | Cause & Remedy |
|---|---|---|
| `0` | Success | All files successfully generated and written. |
| `1` / `2` | Argument Error | Missing required arguments or mutually exclusive flags conflict. |
| `RuntimeError` | No Events Returned | The API returned 0 events for the given date range. Check that your `--start` and `--end` cover active semester dates. |
| `PermissionError` | HTTP 401 | Phenikaa session expired or token was revoked by another login. Re-authenticate. |
| `ValueError` | Corrupt Data | The specified auth file or cache directory did not contain valid `userId` and `tokenJWT`. |

---

## 5. Practical Automation Examples

### Example 1: First-Time Login & Export
```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2027-01-31 \
  --browser-login \
  --out-dir ./my_schedule \
  --prefix semester_1
```

### Example 2: Headless Scripted Run with Stored Credentials
```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2027-01-31 \
  --auth-json .auth.json \
  --out-dir ./my_schedule \
  --prefix semester_1
```

### Example 3: Extract from Mac Chrome Browser Cache
```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2026-10-31 \
  --cache-dir "$HOME/Library/Caches/Google/Chrome/Default/Cache/Cache_Data" \
  --out-dir exports
```
