# System Architecture

This document describes the architectural design, core subsystems, and data flows of the **Phenikaa Calendar Exporter** project.

---

## 1. High-Level Architecture Overview

The system is designed with a layered, decoupled architecture allowing both standalone CLI execution and multi-user web server hosting:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              Entry Points                              │
│                                                                        │
│    [ CLI Tool: phenikaa_exporter.py ]     [ Web Server: server/ ]      │
└───────────────────┬──────────────────────────────────┬─────────────────┘
                    │                                  │
                    ▼                                  ▼
┌──────────────────────────────────────┐   ┌─────────────────────────────┐
│       Core Domain Services           │   │      Server Subsystems      │
│                                      │   │                             │
│ • XOR Encryption/Decryption          │   │ • Auth & OIDC / Google SSO  │
│ • Calendar API Client                │   │ • SQLite Database & Vault   │
│ • Event Normalization & Dedup        │   │ • Background SyncEngine     │
│ • Exporters (XLSX, ICS, JSON)        │   │ • Playwright Login Broker   │
│ • Playwright Headless / Sniffer      │   │ • Google Calendar Syncer    │
└───────────────────┬──────────────────┘   └──────────────┬──────────────┘
                    │                                     │
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │ Phenikaa Portal API   │             │ Google Calendar API   │
        │ (qldtbeta.phenikaa...)│             │ (App-created events)  │
        └───────────────────────┘             └───────────────────────┘
```

---

## 2. Core Modules Breakdown

### 2.1. Standalone Core (`phenikaa_exporter.py`)
Zero external framework dependencies beyond `openpyxl` (for Excel) and Python standard library:
- **`xor_b64_encode` / `xor_b64_decode`**: Implements the portal's client-side obfuscation functions (`AE` and `AD`).
- **`parse_bootstrap_html` & `extract_auth_from_cache`**: Decodes `AXYZCLRVN` blobs from raw HTML or scans Chromium disk cache chunks.
- **`fetch_calendar`**: Constructs obfuscated POST payloads, dispatches HTTP requests with bearer tokens, and decodes outer and inner JSON envelopes.
- **`normalize_events`**: Sanitizes HTML `<br>` tags, strips redundant whitespace, deduplicates repeated records by compound identity `(ID, NGAYHOC, GIOBATDAU, PHUTBATDAU, TENHOCPHAN, TENLOPHOCPHAN)`, and sorts events chronologically.
- **`write_xlsx`**: Generates a stylized workbook with freeze panes, color-coded exam highlighting, and a dynamic `Summary` tab.
- **`write_ics`**: Produces RFC 5545-compliant iCalendar files with `Asia/Ho_Chi_Minh` timezones and 75-octet UTF-8 line folding.

### 2.2. Interactive Authentication Helper (`phenikaa_login.py`)
- Uses Playwright to launch a Chromium window pointing to the student portal.
- Installs network response listeners to intercept `AXYZCLRVN` bootstrap responses and request listeners to capture `Authorization: Bearer <tokenJWT>` headers.
- Emits atomic, permissions-restricted (`0600`) `.auth.json` files.

### 2.3. Multi-User Server (`server/`)
- **`server/config.py`**: Central dataclass handling environment variables (`PHENIKAA_SERVER_*`), path resolution, and default academic term dates.
- **`server/crypto.py`**: AES-128-CBC encryption with Fernet (`TokenVault`) to secure bearer tokens and Google OAuth refresh tokens at rest. Token fingerprinting using SHA-256.
- **`server/db.py`**: SQLite database manager with schema versioning, foreign keys, cascade deletes, and transaction isolation.
- **`server/login_broker.py`**: Coordinates remote browser login sessions streamed over HTTP Server-Sent Events (SSE).
- **`server/sync.py`**: Threaded background scheduler that periodically refreshes expired Phenikaa sessions and triggers one-way Google Calendar synchronization.
- **`server/google.py` & `server/google_login.py`**: Google OAuth token management, dedicated `Phenikaa Learning Calendar` lifecycle, event diffing, creation, update, and tombstone pruning.
- **`server/oidc.py`**: Generic OIDC client supporting RS256 JWKS key discovery and state/nonce validation.
- **`server/web.py`**: HTTP server implementation handling public one-shot exports, bilingual UI rendering, session cookies, and dashboard actions.

---

## 3. Data Flow & Security Model

### 3.1. One-Shot Public Export Data Flow
```
User Browser                       Web Server Process                 Phenikaa API
     │                                      │                              │
     ├─── 1. POST HTML or token ──────────►│                              │
     │    (max 1MB payload)                 ├── 2. Extract credentials     │
     │                                      ├── 3. Fetch calendar ────────►│
     │                                      │◄── 4. Encrypted JSON ────────┘
     │                                      ├── 5. Decrypt in memory       │
     │                                      ├── 6. Generate ZIP in /tmp    │
     │◄── 7. Stream ZIP (no-store) ─────────┤                              │
     │                                      └── 8. Wipe credentials & temp │
```
*At no point are one-shot credentials or calendar files written to the database or long-term disk.*

### 3.2. Background Synchronization Data Flow
1. **SyncEngine** wakes up every `sync_interval_hours` (default 24h).
2. For each active session in SQLite:
   - Acquires a file lock on the user's browser profile.
   - Refreshes the portal session if the JWT has expired by launching headless Chromium with the persistent profile.
   - Queries `fetch_calendar()` for the academic year date window.
   - Updates local static exports (`exports/<session_id>.ics`).
   - If Google Calendar is linked, calls `google.sync_session()`:
     - Resolves or creates the dedicated calendar `"Phenikaa Learning Calendar"`.
     - Queries existing app-created events in Google Calendar.
     - Computes diff (New, Updated, Deleted).
     - Batches upserts and deletes stale events.
     - Logs sync history and timestamp into SQLite.
