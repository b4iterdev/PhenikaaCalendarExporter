import os
import tempfile
import unittest
from datetime import date
from importlib.util import find_spec
from pathlib import Path

if find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from server.config import ServerConfig, academic_year_range
from server.crypto import TokenVault, load_or_create_key, token_fingerprint
from server.db import Database, STATUS_ACTIVE


class ConfigAndCryptoTests(unittest.TestCase):
    def test_academic_year_surrounds_date(self):
        self.assertEqual(academic_year_range(date(2026, 8, 1)), (date(2026, 8, 1), date(2027, 7, 31)))
        self.assertEqual(academic_year_range(date(2026, 3, 1)), (date(2025, 8, 1), date(2026, 7, 31)))

    def test_key_file_permissions_and_token_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            key = load_or_create_key(path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            vault = TokenVault(key)
            encrypted = vault.encrypt("secret-token")
            self.assertNotIn("secret-token", encrypted)
            self.assertEqual(vault.decrypt(encrypted), "secret-token")
            fingerprint = token_fingerprint("secret-token")
            assert fingerprint is not None
            self.assertEqual(len(fingerprint), 12)


class DatabaseTests(unittest.TestCase):
    def test_user_session_credentials_and_sync_history(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "server.db")
            user = database.get_or_create_user("subject-1", "Student")
            self.assertEqual(database.get_or_create_user("subject-1")["id"], user["id"])
            session_id = database.create_session(
                user["id"], label="Main", range_start="2026-08-01", range_end="2027-07-31"
            )
            database.update_session_credentials(session_id, "student-id", "encrypted", "fingerprint")
            stored = database.get_session(session_id)
            assert stored is not None
            self.assertEqual(stored["status"], STATUS_ACTIVE)
            run_id = database.start_sync_run(session_id)
            database.finish_sync_run(run_id, ok=True, events=2, detail="saved")
            self.assertEqual(database.last_sync_runs(session_id)[0]["events"], 2)
            database.delete_session(session_id)
            self.assertEqual(database.last_sync_runs(session_id), [])
            database.close()


if __name__ == "__main__":
    unittest.main()
