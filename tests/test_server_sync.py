import json
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

if find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from cryptography.fernet import Fernet

from phenikaa_login import LoginTimeout
from server.config import ServerConfig
from server.crypto import TokenVault, token_fingerprint
from server.db import Database, STATUS_NEEDS_HUMAN
from server.sync import SyncEngine


class FailingGoogleSyncer:
    def __call__(self, *_args, **_kwargs):
        raise RuntimeError("calendar unavailable")

SAMPLE_EVENT = {
    "ID": "class-1",
    "TENHOCPHAN": "Distributed Systems",
    "NGAYHOC": "24/08/2026",
    "GIOBATDAU": 8,
    "PHUTBATDAU": 0,
    "GIOKETTHUC": 10,
    "PHUTKETTHUC": 0,
    "PHANLOAI": "LICHHOC",
}


class SyncEngineTests(unittest.TestCase):
    def make_session(self, root, token="old-token"):
        config = ServerConfig(state_dir=Path(root), auth_mode="disabled")
        config.ensure_dirs()
        database = Database(config.db_path)
        vault = TokenVault(Fernet.generate_key())
        user = database.get_or_create_user("student")
        session_id = database.create_session(
            user["id"], range_start="2026-08-01", range_end="2027-07-31", sync_interval_hours=24
        )
        database.update_session_credentials(
            session_id, "student-id", vault.encrypt(token), str(token_fingerprint(token))
        )
        return config, database, vault, session_id

    def test_sync_writes_json_and_ics(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, vault, session_id = self.make_session(directory)
            engine = SyncEngine(config, database, vault, fetcher=lambda *_args, **_kwargs: [SAMPLE_EVENT])
            stored = database.get_session(session_id)
            assert stored is not None
            result = engine.sync_session(stored)
            self.assertTrue(result.ok)
            self.assertEqual(json.loads((config.exports_dir / session_id / "calendar.json").read_text())[0]["ID"], "class-1")
            self.assertTrue((config.exports_dir / session_id / "calendar.ics").exists())
            database.close()

    def test_401_refreshes_and_retries_once(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, vault, session_id = self.make_session(directory)
            calls = []

            def fetch(auth, *_args):
                calls.append(auth["tokenJWT"])
                if auth["tokenJWT"] == "old-token":
                    raise PermissionError("expired")
                return [SAMPLE_EVENT]

            def refresh(*_args, **_kwargs):
                return {"userId": "student-id", "tokenJWT": "new-token"}

            engine = SyncEngine(config, database, vault, fetcher=fetch, refresher=refresh)
            stored_before = database.get_session(session_id)
            assert stored_before is not None
            result = engine.sync_session(stored_before)
            self.assertTrue(result.ok)
            self.assertTrue(result.refreshed)
            self.assertEqual(calls, ["old-token", "new-token"])
            stored = database.get_session(session_id)
            assert stored is not None
            self.assertEqual(vault.decrypt(stored["token_encrypted"]), "new-token")
            database.close()

    def test_refresher_receives_old_token_to_bypass_stale_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, vault, session_id = self.make_session(directory)
            received_old_token = []

            def fetch(auth, *_args):
                if auth["tokenJWT"] == "old-token":
                    raise PermissionError("expired")
                return [SAMPLE_EVENT]

            def refresh(profile_dir, *, old_token=None, **_kwargs):
                received_old_token.append(old_token)
                return {"userId": "student-id", "tokenJWT": "fresh-token"}

            engine = SyncEngine(config, database, vault, fetcher=fetch, refresher=refresh)
            stored = database.get_session(session_id)
            assert stored is not None
            result = engine.sync_session(stored)
            self.assertTrue(result.ok)
            self.assertEqual(received_old_token, ["old-token"])
            database.close()

    def test_sync_extracts_auth_cookie_from_stored_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, vault, session_id = self.make_session(directory)
            received_auth = []

            def fetch(auth, *_args):
                received_auth.append(auth)
                return [SAMPLE_EVENT]

            stored_payload = json.dumps({"tokenJWT": "jwt-123", "authCookie": "auth-abc"})
            database.update_session_credentials(session_id, "user-1", vault.encrypt(stored_payload), "fp")

            engine = SyncEngine(config, database, vault, fetcher=fetch)
            stored = database.get_session(session_id)
            assert stored is not None
            result = engine.sync_session(stored)
            self.assertTrue(result.ok)
            self.assertEqual(received_auth[0]["tokenJWT"], "jwt-123")
            self.assertEqual(received_auth[0]["authCookie"], "auth-abc")
            database.close()

    def test_failed_refresh_requires_human(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, vault, session_id = self.make_session(directory)

            def fetch(*_args, **_kwargs):
                raise PermissionError("expired")

            def refresh(*_args, **_kwargs):
                raise LoginTimeout("login required")

            engine = SyncEngine(config, database, vault, fetcher=fetch, refresher=refresh)
            stored = database.get_session(session_id)
            assert stored is not None
            result = engine.sync_session(stored)
            self.assertFalse(result.ok)
            updated = database.get_session(session_id)
            assert updated is not None
            self.assertEqual(updated["status"], STATUS_NEEDS_HUMAN)
            database.close()

    def test_google_failure_does_not_invalidate_export_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, vault, session_id = self.make_session(directory)
            engine = SyncEngine(
                config,
                database,
                vault,
                fetcher=lambda *_args, **_kwargs: [SAMPLE_EVENT],
                google_syncer=FailingGoogleSyncer(),
            )
            stored = database.get_session(session_id)
            assert stored is not None
            result = engine.sync_session(stored)
            self.assertTrue(result.ok)
            self.assertIn("saved 1 events", result.detail)
            self.assertIn("Google Calendar sync failed", result.detail)
            self.assertTrue((config.exports_dir / session_id / "calendar.json").exists())
            self.assertTrue(database.last_sync_runs(session_id)[0]["ok"])
            database.close()


if __name__ == "__main__":
    unittest.main()
