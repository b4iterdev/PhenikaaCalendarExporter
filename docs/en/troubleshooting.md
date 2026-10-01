# Troubleshooting & FAQ

This guide collects common issues encountered when using **Phenikaa Calendar Exporter** (both CLI and Web Server modes) and their solutions.

---

## 1. Quick Problem-Solution Matrix

| Problem | Likely Cause | Solution |
|---|---|---|
| **API returns no events** | Date range is too narrow or semester hasn't started. | Provide a broader date range spanning the entire term (e.g., Aug 1 to Jan 31). |
| **HTTP 401 / Session Expired** | Bearer token expired or superseded by another login. | Sign in to the portal again and refresh your credentials or `.auth.json`. |
| **Events appear at the wrong time** | Calendar app timezone is not set to GMT+7. | Enable timezone support in your calendar app and select `Asia/Ho_Chi_Minh`. |
| **`playwright is required`** | Playwright extra is not installed. | Run `pip install -e ".[login]"` followed by `playwright install chromium`. |
| **Browser fails to launch on Linux** | Missing system graphics libraries. | Run `playwright install-deps chromium`. |
| **Google sync stopped after 7 days** | Google Cloud OAuth is in "Testing" mode. | Reauthorize in dashboard or publish your Google Cloud OAuth app. |
| **Decryption failed in Server mode** | `PHENIKAA_SERVER_KEY` was changed. | Restore the original Fernet key or recreate your state directory. |

---

## 2. Authentication & Session Issues

### "Phenikaa session expired; log in again" (HTTP 401)
- **Why it happens**: Phenikaa bearer tokens (`tokenJWT`) are short-lived. Logging in from another browser or device often invalidates the previous session token immediately.
- **Fix**:
  1. Open `https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx#lichhoc`.
  2. Log in with your Microsoft account.
  3. Re-run `python phenikaa_exporter.py --browser-login` to capture a fresh `.auth.json`.
  4. If using the web dashboard, click **Reconnect** next to your Phenikaa account.

### "No authenticated Phenikaa bootstrap page was found in the Chromium cache"
- **Why it happens**: Chromium regularly evicts old cache blocks from disk, or you scanned a different browser profile from the one you logged into.
- **Fix**:
  1. Open the portal in Chrome and refresh the page (`F5`).
  2. Ensure you specify the correct Chrome profile path (e.g. `Profile 1` vs `Default`).
  3. Alternatively, save the webpage as `index.aspx` and use `--bootstrap-html` instead.

---

## 3. Calendar Data & Display Issues

### "The API returned no calendar events for the requested range"
- **Why it happens**: The university database does not use semester IDs. It queries strictly between `--start` and `--end`. If your range falls during summer break or misses the first week of class, 0 events are returned.
- **Fix**: The tool deliberately refuses to generate an empty Excel or ICS file. Expand your date range to cover the full academic term:
  ```bash
  python phenikaa_exporter.py --start 2026-08-01 --end 2027-01-31 --auth-json .auth.json
  ```

### Class times shifted by hours in Google or Apple Calendar
- **Why it happens**: Vietnam does not observe Daylight Saving Time and operates permanently on **UTC+07:00** (`Asia/Ho_Chi_Minh`). If your calendar app defaults to UTC, events may appear shifted.
- **Fix**: Ensure your device and calendar app have timezone handling enabled with `Asia/Ho_Chi_Minh` selected as the calendar's timezone.

---

## 4. Google Calendar Synchronization Issues

### Google Calendar sync stops working after 7 days
- **Why it happens**: When you create an OAuth app in Google Cloud Console with the Publishing Status set to **Testing**, Google expires refresh tokens after exactly 7 days.
- **Fix**:
  - In [Google Cloud Console](https://console.cloud.google.com/apis/credentials/consent), set your app status to **In Production** (or click **Publish App**). For personal/internal use, verification is not required if users accept the unverified app warning.
  - In the dashboard, click **Authorize Google Calendar** to generate a new refresh token.

### Duplicate events in Google Calendar
- **Why it happens**: Importing an `.ics` file manually while also having background Google Calendar sync enabled.
- **Fix**: All automated sync events are placed in **`Phenikaa Learning Calendar`**. If you manually imported an `.ics` into your primary calendar, delete the manually imported events.

---

## 5. Server Deployment Issues

### "Chromium sandbox: Failed to launch" in Docker
- **Why it happens**: Running Docker containers without `SYS_ADMIN` capability prevents Chromium's setuid sandbox from executing.
- **Fix**: Set environment variable `-e PHENIKAA_BROWSER_NO_SANDBOX=true`.

### "database is locked" (SQLite)
- **Why it happens**: Running multiple replicas of the Docker container against the same shared network storage volume.
- **Fix**: Deploy exactly **one replica** of the container. SQLite, Playwright browser profiles, and process locks require a single local instance.

---

## 6. What to Do If the Portal Updates

Phenikaa's portal is an internal web application. If a university update changes the API, inspect these files on the portal:

1. `Config.js`: Base API URLs and service endpoints.
2. `Core/systemroot.js`: Request dispatching and obfuscation parameters.
3. `assets/js/crypto-js.js`: The `AE` and `AD` cipher helpers.
4. `modules/thoikhoabieu/script/lichgiang.js`: Action suffixes and parameter field names.
