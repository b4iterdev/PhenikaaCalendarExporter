# Authentication

[Back to the README](../README.md)

The exporter never stores passwords. It reads session data produced by your own authenticated Phenikaa portal session. Choose exactly one authentication source.

## Automated browser login (recommended)

```bash
python -m pip install -e "[login]"
playwright install chromium
python phenikaa_exporter.py --start 2026-08-01 --end 2027-01-31 --browser-login --out-dir exports
```

Chromium opens the portal and captures `userId` and `tokenJWT` from the page’s own responses. A persistent `.browser-profile/` may keep the login between runs.

## Local Chromium cache

Sign in and run against the browser’s `Cache_Data` directory:

```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2026-10-31 \
  --cache-dir "$HOME/Library/Application Support/Hermes/Partitions/hermes-preview/Cache/Cache_Data" \
  --out-dir exports --prefix current_semester
```

Chrome commonly uses `~/Library/Caches/Google/Chrome/<Profile>/Cache/Cache_Data`. Paths vary by browser and version.

## Saved authenticated HTML

Save the authenticated `index.aspx` response and run:

```bash
python phenikaa_exporter.py --start 2026-08-01 --end 2026-10-31 --bootstrap-html /private/path/authenticated-index.html --out-dir exports
```

The file contains a bearer token; delete it after use.

## Private authentication JSON

Create `.auth.json` containing the internal user ID and token:

```json
{
  "userId": "YOUR_32_CHARACTER_INTERNAL_USER_ID",
  "tokenJWT": "YOUR_TOKEN_WITHOUT_THE_BEARER_PREFIX"
}
```

```bash
chmod 600 .auth.json
python phenikaa_exporter.py --start 2026-08-01 --end 2027-01-31 --auth-json .auth.json --out-dir exports
```

`userId` can be read from `window.edu?.system?.userId` in the authenticated portal. `tokenJWT` is the value after `Bearer` in an authenticated calendar API request. Never share either value.

## Server one-shot export

After signing in to the calendar server through its configured OIDC provider, the dashboard can create an export without creating or syncing a retained Phenikaa session. Choose either the saved authenticated `index.aspx` HTML method or the manual `userId` plus `tokenJWT` method. Do not fill both credential sections.

The server decodes or uses these values only for the current request and returns a ZIP containing JSON, XLSX, and ICS files. It does not retain the submitted HTML or credentials. “Bootstrap HTML” in this workflow refers to the portal's saved authenticated response, not the Bootstrap CSS framework.

## Security

- `.auth.json` contains a bearer token and is git-ignored; never commit, paste, or screenshot it.
- `.browser-profile/` contains live cookies and should be treated like a password.
- Exports may contain private academic information.

See [Troubleshooting](TROUBLESHOOTING.md) for expired sessions and browser-login problems.
