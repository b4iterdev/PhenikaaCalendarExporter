# Authentication Internals & Reverse Engineering

This document explains the technical details of Phenikaa University's portal authentication, how session tokens are derived, and how this project captures them without ever storing passwords.

---

## 1. The Portal Bootstrap Mechanism

When a student or teacher logs into the Phenikaa University portal (`qldtbeta.phenikaa-uni.edu.vn`) through Microsoft Entra ID (Azure AD), the portal server renders an authenticated base page at `/congsinhvien/index.aspx`.

Inside the HTML, a dynamic script tag embeds a closure containing an obfuscated string:

```html
<script>
  AXYZCLRVN = () => "BASE64_OBFUSCATED_STRING";
</script>
```

### De-obfuscation Algorithm
The portal's frontend helper `AD(ciphertext, "AzzS")` unpacks this string through three steps:

```
┌────────────────────────┐
│ Base64 Encoded Payload │
└───────────┬────────────┘
            │ 1. Base64 Decode
            ▼
┌────────────────────────┐
│  UTF-8 Encrypted Bytes │
└───────────┬────────────┘
            │ 2. Character-wise XOR with repeating key "AzzS"
            ▼
┌────────────────────────┐
│    Raw JSON String     │
└───────────┬────────────┘
            │ 3. json.loads()
            ▼
┌──────────────────────────────────────────────┐
│ { "userId": "...", "tokenJWT": "..." }       │
└──────────────────────────────────────────────┘
```

In Python, this is implemented cleanly as:

```python
def xor_b64_decode(encoded: str, key: str) -> str:
    encrypted = base64.b64decode(encoded).decode("utf-8")
    return "".join(chr(ord(char) ^ ord(key[index % len(key)])) for index, char in enumerate(encrypted))
```

The resulting JSON dictionary contains:
- `userId`: A 32-character hexadecimal identifier representing the student/lecturer record.
- `tokenJWT`: A short-lived JSON Web Token passed as a `Bearer` token in all subsequent API requests.

---

## 2. Interactive Playwright Login (`phenikaa_login.py`)

To eliminate the need for users to manually inspect Developer Tools, `phenikaa_login.py` implements a passive network sniffer using Playwright:

1. **Persistent Browser Context**: Chromium is launched with a dedicated user data directory (`.browser-profile/`). This preserves Microsoft session cookies between runs.
2. **Dual-Channel Interception**:
   - **Response Interception**: Listens to all incoming HTTP responses. If a response contains `AXYZCLRVN`, the body is decoded through `parse_bootstrap_html()`.
   - **Request Header Interception**: Watches all outgoing requests to `/sinhvienapi3/`. When an `Authorization: Bearer <token>` header is detected, the raw JWT is extracted.
   - **In-Page DOM Fallback**: Periodically executes `window.edu?.system?.userId` within the page context.
3. **Safe Credential Storage**:
   Once both `userId` and `tokenJWT` are acquired, the session is written to disk using POSIX file descriptor mode `0600` (read/write by owner only):
   ```python
   handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
   with os.fdopen(handle, "w", encoding="utf-8") as stream:
       stream.write(payload + "\n")
   ```

---

## 3. Chromium Disk Cache Extraction (`extract_auth_from_cache`)

For environments where Playwright cannot be launched (such as headless servers or environments without graphical displays), the CLI can scan the local Chromium/Chrome disk cache:

1. Chromium stores cache entries in a binary block format under `Cache/Cache_Data/`.
2. The scanner inspects candidate cache files sorted by modification time (`mtime`).
3. Compressed HTTP response streams inside cache blocks begin with gzip headers (`\x1f\x8b\x08`).
4. The scanner decompresses these streams using Python's `zlib.decompressobj(16 + zlib.MAX_WBITS)`.
5. When the `AXYZCLRVN` token is found, the HTML is parsed and credentials returned immediately without writing any secrets to stdout.

### Common Cache Directories
- **Google Chrome (macOS)**:
  `~/Library/Caches/Google/Chrome/<Profile>/Cache/Cache_Data`
- **Google Chrome (Linux)**:
  `~/.cache/google-chrome/<Profile>/Cache/Cache_Data`
- **Hermes Preview (macOS)**:
  `~/Library/Application Support/Hermes/Partitions/hermes-preview/Cache/Cache_Data`

---

## 4. Token Lifecycle & Server-Side TokenVault

In server mode (`server/`):
- Tokens captured from users are never stored in plaintext SQLite.
- `server/crypto.py` (`TokenVault`) encrypts each `tokenJWT` using **Fernet (AES-128-CBC with HMAC-SHA256)** under `PHENIKAA_SERVER_KEY`.
- SHA-256 fingerprints are stored for auditing without revealing the token.
- When tokens expire (typically after 24–48 hours), the server's `SyncEngine` re-opens a background Playwright session using the preserved browser profile cookies to harvest a fresh token automatically.
