import http.client
import tempfile
import threading
import unittest
import urllib.parse
from importlib.util import find_spec
from pathlib import Path

if find_spec("jwt") is None or find_spec("cryptography") is None:
    raise unittest.SkipTest("server tests require `pip install -e .[server]`")

from cryptography.fernet import Fernet

from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database
from server.login_broker import LoginBroker
from server.oidc import SignedSessions
from server.refresh import ProfileLocks
from server.sync import SyncEngine
from server.web import ServerApplication, make_server


class WebSmokeTests(unittest.TestCase):
    def test_disabled_auth_dashboard_and_session_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ServerConfig(state_dir=Path(directory), host="127.0.0.1", port=0, auth_mode="disabled")
            config.ensure_dirs()
            database = Database(config.db_path)
            vault = TokenVault(Fernet.generate_key())
            locks = ProfileLocks()
            sync = SyncEngine(config, database, vault, locks=locks, fetcher=lambda *_args: [])
            broker = LoginBroker(config, locks=locks)
            app = ServerApplication(config, database, vault, SignedSessions(b"x" * 32), broker, sync, None)
            server = make_server(app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                response.read()
                invalid = urllib.parse.urlencode({
                    "csrf": "development", "label": "Invalid", "range_start": "2027-01-01", "range_end": "2026-01-01"
                })
                connection.request(
                    "POST", "/sessions", body=invalid,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                self.assertEqual(database.list_sessions(), [])
                body = urllib.parse.urlencode({"csrf": "development", "label": "My calendar"})
                connection.request(
                    "POST", "/sessions", body=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 303)
                response.read()
                sessions = database.list_sessions()
                self.assertEqual(len(sessions), 1)
                session_id = sessions[0]["id"]
                connection.request(
                    "POST", f"/sessions/{session_id}/event", body=b"{broken",
                    headers={"Content-Type": "application/json", "X-CSRF-Token": "development"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                export_dir = config.exports_dir / session_id
                export_dir.mkdir(parents=True)
                (export_dir / "calendar.json").write_text("[]")
                connection.request("GET", f"/sessions/{session_id}/download/calendar.json")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                response.read()
                lock = broker.try_profile_lock(session_id)
                assert lock is not None
                delete_body = urllib.parse.urlencode({"csrf": "development"})
                try:
                    connection.request(
                        "POST", f"/sessions/{session_id}/delete", body=delete_body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 409)
                    response.read()
                finally:
                    lock.release()
                connection.close()
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
                database.close()


if __name__ == "__main__":
    unittest.main()
