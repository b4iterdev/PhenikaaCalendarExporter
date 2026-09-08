"""Server-side secret handling: Fernet key management and token vaults."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_FILE_MODE = 0o600


def load_or_create_key(path: Path | str) -> bytes:
    """Load the Fernet key at `path`, creating it (mode 0600) on first use."""
    key_file = Path(path)
    if key_file.exists():
        data = key_file.read_bytes().strip()
        if data:
            return data
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    handle = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, KEY_FILE_MODE)
    with os.fdopen(handle, "wb") as stream:
        stream.write(key)
    return key


def token_fingerprint(token: str | None) -> str | None:
    """Short non-reversible identifier that is safe for logs and API responses."""
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


class TokenVault:
    """Encrypts and decrypts Phenikaa bearer tokens with a server-owned key."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt(self, blob: str) -> str:
        try:
            return self._fernet.decrypt(blob.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as error:
            raise ValueError("stored credential could not be decrypted with the server key") from error
