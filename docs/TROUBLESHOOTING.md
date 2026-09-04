# Troubleshooting

[Back to the README](../README.md) · [Authentication guide](AUTHENTICATION.md) · [Usage guide](USAGE.md)

## Browser login problems

| Symptom | Fix |
|---|---|
| `playwright is required for --browser-login` | Run `python -m pip install -e "[login]"` then `playwright install chromium`. |
| Browser fails to launch on Linux | Run `playwright install-deps chromium`, then retry. |
| Sign-in times out after five minutes | Rerun the command and complete sign-in sooner. |
| Sign-in is requested every run | Delete `.browser-profile/` and sign in again. |
| Window opens behind other windows | Bring the Chromium window titled like the Phenikaa portal to the front. |

## `401` or “session expired”

The bearer token is short-lived or can be invalidated by another login.

1. Open the portal and sign in again.
2. Reload `index.aspx#lichhoc` so a fresh authenticated index response enters the cache.
3. Re-run the command with `--cache-dir`, or regenerate the private authentication source.

Do not paste the token into an issue or chat transcript.

## No bootstrap page found in `Cache_Data`

- Confirm that the selected browser/profile is the one used for login.
- Reload the authenticated portal home page before scanning.
- Chromium may evict disk-cache entries; use a saved authenticated HTML response or a private `.auth.json` instead.
- The Hermes preview cache on macOS is normally:

```text
~/Library/Application Support/Hermes/Partitions/hermes-preview/Cache/Cache_Data
```

Chrome profiles normally store cache data under:

```text
~/Library/Caches/Google/Chrome/<Profile>/Cache/Cache_Data
```

Exact paths vary by browser and version.

## The API returns no events

- Check the inclusive date range.
- Try a broader range that covers the full semester.
- Verify the same dates visibly contain events in the portal.
- Refresh authentication if the portal changed sessions.

The CLI intentionally refuses to create an apparently successful XLSX from an empty API result.

## XLSX import error

Install the pinned dependency in the active virtual environment:

```bash
python -m pip install -r requirements.txt
```

## ICS shows the wrong time

The file declares `Asia/Ho_Chi_Minh` and fixed UTC+07:00. Confirm the importing calendar application has timezone support enabled. Do not reinterpret the exported local times as UTC.

## Portal changes

This is an internal API. If a future portal update breaks the exporter, inspect these assets first:

- `Config.js`: service base paths.
- `Core/systemroot.js`: `makeRequest` request construction.
- `assets/js/crypto-js.js`: `AE` / `AD` helpers.
- `modules/thoikhoabieu/script/lichgiang.js`: action, function, and payload fields.

Update the constants and add a failing regression test before changing implementation.
