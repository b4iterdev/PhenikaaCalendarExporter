# Server and Docker Deployment

[Back to the README](../README.md)

Server mode keeps separate browser profiles for OIDC-authenticated users, encrypts captured JWTs in SQLite, refreshes tokens through retained portal cookies, and writes each session’s JSON and ICS exports.

## Configuration

```bash
python -m pip install -e "[server]"
playwright install chromium
export PHENIKAA_SERVER_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu"
export PHENIKAA_OIDC_ISSUER="https://identity.example.edu"
export PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar"
export PHENIKAA_OIDC_CLIENT_SECRET="..."
phenikaa-calendar-server --host 127.0.0.1 --port 8416
```

Register `${PHENIKAA_SERVER_BASE_URL}/auth/callback` with the OIDC provider. The provider must expose standard discovery metadata and RS256 JWKS keys. Use `client_secret_basic` for the token endpoint authentication method.

Keep `PHENIKAA_SERVER_KEY` unchanged for the lifetime of the state directory. State includes `server.db`, browser profiles, exports, and `cookie.secret`.

## Docker

The image listens on `0.0.0.0:8416`, stores state in `/data`, runs as an unprivileged user, and includes managed Chromium.

```bash
docker run -d --name phenikaa-calendar \
  -p 8416:8416 -v phenikaa-data:/data \
  -e PHENIKAA_SERVER_KEY="..." \
  -e PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu" \
  -e PHENIKAA_OIDC_ISSUER="https://identity.example.edu" \
  -e PHENIKAA_OIDC_CLIENT_ID="phenikaa-calendar" \
  -e PHENIKAA_OIDC_CLIENT_SECRET="..." \
  ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server
```

GitHub Actions publishes multi-architecture images for `linux/amd64` and `linux/arm64`:

```text
ghcr.io/b4iterdev/phenikaa-calendar-exporter:main
ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server
ghcr.io/b4iterdev/phenikaa-calendar-exporter:dev-server-<sha>
ghcr.io/b4iterdev/phenikaa-calendar-exporter:latest
```

Keep one server replica because SQLite, browser profiles, and filesystem state are local. Configure the reverse proxy with limits and timeouts suitable for long-lived login streams, and do not log `/auth/callback` query strings.
