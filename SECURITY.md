# Security and privacy

## Sensitive values

The portal's authenticated bootstrap data contains:

- `userId`: the portal's internal user identifier.
- `tokenJWT`: a bearer token that authorizes API calls as the logged-in user.
- Calendar output: course enrollment, room, lecturer, attendance and exam information.

Treat the token exactly like a password while it is valid. The exporter never logs or prints it.

## Required practices

1. Never commit `.auth.json`, saved authenticated HTML, Chromium cache files, or generated exports.
2. Keep authentication files readable only by your account: `chmod 600 .auth.json`.
3. Delete saved bootstrap HTML and copied cache data after extracting/exporting.
4. If a token appears in a terminal transcript, issue, chat, or repository, log out of the portal and sign in again to invalidate/replace the session.
5. Only use the exporter for an account you are authorized to access.

## What the project stores

The exporter writes only the requested JSON, XLSX and ICS files. It does not save the bearer token. `--cache-dir` reads the local cache in place and keeps the decoded session in process memory only.

## Network behavior

The normal command sends one authenticated POST request to:

`https://qldtbeta.phenikaa-uni.edu.vn/sinhvienapi3/api/SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv`

No credentials or calendar data are sent to third-party services.
