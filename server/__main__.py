from __future__ import annotations

import argparse
from pathlib import Path

from server.config import ServerConfig
from server.crypto import TokenVault
from server.db import Database
from server.login_broker import LoginBroker
from server.oidc import OidcClient, SignedSessions, load_or_create_secret
from server.refresh import ProfileLocks
from server.sync import SyncEngine
from server.web import ServerApplication, make_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phenikaa calendar synchronization server")
    parser.add_argument("--host", help="Listen address (default from PHENIKAA_SERVER_HOST)")
    parser.add_argument("--port", type=int, help="Listen port (default from PHENIKAA_SERVER_PORT)")
    parser.add_argument("--state-dir", type=Path, help="Private database/profile/export directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ServerConfig()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.state_dir:
        config.state_dir = args.state_dir
    config.ensure_dirs()

    database = Database(config.db_path)
    if not config.encryption_key:
        raise RuntimeError("PHENIKAA_SERVER_KEY must contain a Fernet key")
    vault = TokenVault(config.encryption_key.encode("ascii"))
    signed_sessions = SignedSessions(load_or_create_secret(config.cookie_secret_path))
    locks = ProfileLocks()
    broker = LoginBroker(config, locks=locks)
    sync_engine = SyncEngine(config, database, vault, locks=locks)
    oidc = None
    if config.auth_mode != "disabled":
        missing = [
            name for name, value in (
                ("PHENIKAA_OIDC_ISSUER", config.oidc_issuer),
                ("PHENIKAA_OIDC_CLIENT_ID", config.oidc_client_id),
                ("PHENIKAA_OIDC_CLIENT_SECRET", config.oidc_client_secret),
            ) if not value
        ]
        if missing:
            raise RuntimeError("missing OIDC configuration: " + ", ".join(missing))
        redirect_uri = config.oidc_redirect_uri or config.external_url("/auth/callback")
        oidc = OidcClient(config.oidc_issuer, config.oidc_client_id, config.oidc_client_secret, redirect_uri)

    application = ServerApplication(config, database, vault, signed_sessions, broker, sync_engine, oidc)
    server = make_server(application)
    sync_engine.start()
    print(f"Phenikaa calendar server listening on {config.external_url('/')}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        sync_engine.stop()
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
