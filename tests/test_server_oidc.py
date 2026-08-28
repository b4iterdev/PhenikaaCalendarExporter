import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

if find_spec("jwt") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from server.oidc import SignedSessions, load_or_create_secret, new_authorization_state


class SignedSessionTests(unittest.TestCase):
    def test_cookie_signature_expiry_and_pkce_shape(self):
        sessions = SignedSessions(b"x" * 32, lifetime=60)
        value = sessions.create({"sub": "student"}, now=100)
        verified = sessions.verify(value, now=120)
        assert verified is not None
        self.assertEqual(verified["sub"], "student")
        self.assertIsNone(sessions.verify(value + "x", now=120))
        self.assertIsNone(sessions.verify(value, now=161))
        short = sessions.create({"state": "oidc"}, now=100, lifetime=10)
        self.assertIsNotNone(sessions.verify(short, now=109))
        self.assertIsNone(sessions.verify(short, now=111))
        state, nonce, verifier, challenge = new_authorization_state()
        self.assertTrue(all((state, nonce, verifier, challenge)))
        self.assertNotEqual(verifier, challenge)

    def test_existing_cookie_secret_is_restricted_to_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookie.secret"
            path.write_bytes(b"x" * 32)
            os.chmod(path, 0o644)
            self.assertEqual(load_or_create_secret(path), b"x" * 32)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
