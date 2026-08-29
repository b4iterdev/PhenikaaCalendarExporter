# Usage

[Back to the README](../README.md)

## Quick start

Install browser-login support if desired:

```bash
python -m pip install -e "[login]"
playwright install chromium
```

Automated login:

```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2027-01-31 \
  --browser-login --out-dir exports
```

Later runs can use the captured credentials:

```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2027-01-31 \
  --auth-json .auth.json --out-dir exports
```

## CLI options

Exactly one authentication source is required.

| Option | Purpose |
|---|---|
| `--browser-login` | Open Chromium, capture credentials into `.auth.json`, and export. |
| `--auth-json PATH` | Read credentials from a private JSON file. |
| `--bootstrap-html PATH` | Decode credentials from a saved authenticated `index.aspx` response. |
| `--cache-dir PATH` | Recover credentials from a Chromium `Cache_Data` directory. |
| `--start YYYY-MM-DD` | Inclusive range start; required. |
| `--end YYYY-MM-DD` | Inclusive range end; required. |
| `--out-dir DIR` | Output directory; default `exports`. |
| `--prefix NAME` | Output filename prefix; default `phenikaa_calendar`. |
| `--calendar-name NAME` | Calendar display name written into the ICS file. |

## Choosing the date range

Dates are inclusive and use ISO `YYYY-MM-DD`. The API does not expose a semester ID, so use a broad range covering the expected term.

```bash
# Three months
python phenikaa_exporter.py --start 2026-08-01 --end 2026-10-31 --auth-json .auth.json --out-dir exports

# Academic term spanning the year boundary
python phenikaa_exporter.py --start 2026-08-01 --end 2027-01-31 --auth-json .auth.json --out-dir exports
```

## Output

For `--prefix current_semester`, the command writes:

```text
exports/current_semester.json
exports/current_semester.xlsx
exports/current_semester.ics
```

The JSON is normalized source data. XLSX includes Date, weekday, start/end time, class or exam type, course, section, room or online location, lecturer, periods, session, attendance status, event ID, and a Summary sheet. ICS contains one timezone-aware `VEVENT` per record using `Asia/Ho_Chi_Minh`; exams are categorized and prefixed with `Exam:`. UTF-8 lines are folded to RFC 5545’s 75-octet limit.
