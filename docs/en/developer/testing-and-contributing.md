# Testing & Contributing Guide

This document describes how to execute the automated test suite, verify changes, and contribute to **Phenikaa Calendar Exporter**.

---

## 1. Running the Automated Test Suite

All tests use Python's built-in `unittest` framework and require zero external test runners:

```bash
# Run the complete test suite
python -m unittest discover -s tests -v
```

To run an individual test module:

```bash
# Test the core exporter and encryption
python -m unittest tests/test_exporter.py -v

# Test server database and token encryption
python -m unittest tests/test_server_storage.py -v

# Test Google Calendar sync logic
python -m unittest tests/test_server_google.py -v

# Test web endpoints and CSRF
python -m unittest tests/test_server_web.py -v
```

---

## 2. Test Suite Architecture

| Test File | What It Validates |
|---|---|
| `test_exporter.py` | XOR encryption/decryption, bootstrap extraction from HTML and Chromium cache, date range checks, event deduplication, Excel formatting, RFC 5545 ICS folding, and CLI argument parsing. |
| `test_server_storage.py` | SQLite schema initialization, foreign key constraints, cascade deletions, and `TokenVault` Fernet encryption/decryption roundtrips. |
| `test_server_web.py` | Web application routing, session cookie signing, CSRF protection, public one-shot export (both HTML and manual tokens), and language toggle cookies. |
| `test_server_sync.py` | `SyncEngine` scheduling, interval timers, error handling, and thread-safe profile locking. |
| `test_server_google.py` | Google OAuth token exchange, token refresh, dedicated calendar lifecycle, and event synchronization (insert, update, delete diffing). |
| `test_server_google_login.py`| Combined Google login and calendar authorization mode, reauthorization flows, and offline token storage. |
| `test_server_oidc.py` | Generic OIDC flow, RS256 JWKS key discovery, JWT verification, and transaction state cookies. |
| `test_server_browser.py` | Concurrency locks for browser profiles and Playwright login streaming. |
| `test_server_packaging.py` | Setuptools entry points, console scripts, and wheel packaging metadata. |

---

## 3. Contributing Guidelines

### 3.1. Philosophy
1. **Zero Unnecessary Dependencies**: Keep the core CLI standalone and lightweight. Do not introduce heavy web or scientific dependencies into `phenikaa_exporter.py`.
2. **Privacy First**: Secrets (bearer tokens, refresh tokens, passwords) must never be written to stdout, unencrypted database columns, or unhandled exception traces.
3. **Regression Tests First**: If fixing an issue with a changed portal endpoint or date format, write a failing unit test reproducing the problem before applying the fix.

### 3.2. Code Quality & Standards
- Target **Python 3.9+**.
- Always include `from __future__ import annotations`.
- Use standard Python type hinting on all function signatures.
- Avoid wildcard imports.
- Keep tests self-contained using `tempfile.TemporaryDirectory` and `unittest.mock`.

### 3.3. Submitting Pull Requests
1. Create a feature branch: `git checkout -b feature/my-new-feature`.
2. Implement your changes with corresponding tests.
3. Ensure all tests pass: `python -m unittest discover -s tests -v`.
4. Open a pull request describing the change, the motivation, and test verification.
