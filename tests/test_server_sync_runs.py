import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database
from server.sync import SyncEngine


class SyncRunGuardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = ServerConfig(state_dir=self.root, host="127.0.0.1", port=0, auth_mode="disabled")
        self.config.ensure_dirs()
        self.db = Database(self.config.db_path)
        self.addCleanup(self.db.close)
        self.vault = TokenVault(Fernet.generate_key())
        self.user = self.db.get_or_create_user("a")["id"]
        self.sid = self.db.create_session(self.user)
        self.db.update_session_credentials(self.sid, "uid-1", self.vault.encrypt("jwt"), "fp")

    def run_row(self, run_id):
        return next(r for r in self.db.last_sync_runs(self.sid, 10) if r["id"] == run_id)

    def test_second_start_reports_the_running_run(self):
        first, running = self.db.start_sync_run_if_idle(self.sid)
        self.assertIsNone(running)
        second, running = self.db.start_sync_run_if_idle(self.sid)
        self.assertIsNone(second)
        self.assertEqual(running["id"], first)
        self.db.finish_sync_run(first, ok=True, events=1)
        third, running = self.db.start_sync_run_if_idle(self.sid)
        self.assertIsNone(running)
        self.assertNotEqual(third, first)

    def test_stale_run_is_failed_and_replaced(self):
        old, _ = self.db.start_sync_run_if_idle(self.sid)
        self.db._write("UPDATE sync_runs SET started_at = ? WHERE id = ?",
                       ("2000-01-01T00:00:00+00:00", old))
        new, running = self.db.start_sync_run_if_idle(self.sid)
        self.assertIsNone(running)
        self.assertNotEqual(new, old)
        self.assertEqual(self.run_row(old)["detail"], "timed out")

    def test_restart_fails_unfinished_runs(self):
        run, _ = self.db.start_sync_run_if_idle(self.sid)
        self.assertEqual(self.db.fail_unfinished_sync_runs(), 1)
        self.assertEqual(self.db.fail_unfinished_sync_runs(), 0)
        self.assertIsNotNone(self.run_row(run)["finished_at"])

    def make_engine(self):
        return SyncEngine(self.config, self.db, self.vault, fetcher=lambda auth, start, end: [])

    def test_engine_reuses_the_forced_run_id(self):
        engine = self.make_engine()
        run, _ = self.db.start_sync_run_if_idle(self.sid)
        engine.request_sync(self.sid, run_id=run)
        results = engine.sync_due()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        runs = self.db.last_sync_runs(self.sid, 10)
        self.assertEqual([r["id"] for r in runs], [run])
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_engine_without_run_id_still_creates_its_own_run(self):
        engine = self.make_engine()
        engine.request_sync(self.sid)
        engine.sync_due()
        self.assertEqual(len(self.db.last_sync_runs(self.sid, 10)), 1)


if __name__ == "__main__":
    unittest.main()
