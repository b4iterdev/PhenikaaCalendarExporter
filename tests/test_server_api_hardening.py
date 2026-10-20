import threading
import unittest
from types import SimpleNamespace

from server.web import ServerApplication


def make_app(proxies=frozenset()):
    return SimpleNamespace(
        _api_v1_rate_lock=threading.Lock(),
        _api_v1_request_times={},
        config=SimpleNamespace(trusted_proxies=frozenset(proxies)),
    )


class RateLimitHelperTests(unittest.TestCase):
    def test_limit_then_retry_after(self):
        app = make_app()
        for _ in range(3):
            self.assertEqual(ServerApplication._api_v1_rate_check(app, "ip:a", 3), 0)
        self.assertGreaterEqual(ServerApplication._api_v1_rate_check(app, "ip:a", 3), 1)
        self.assertEqual(ServerApplication._api_v1_rate_check(app, "ip:b", 3), 0)

    def test_stale_keys_are_dropped_when_table_is_large(self):
        app = make_app()
        app._api_v1_request_times = {f"ip:{i}": [-1000.0] for i in range(5001)}
        ServerApplication._api_v1_rate_check(app, "ip:new", 3)
        self.assertLess(len(app._api_v1_request_times), 10)

    def test_client_ip_trusts_forwarded_headers_only_from_trusted_peers(self):
        app = make_app({"10.0.0.1"})

        def handler(peer, **headers):
            return SimpleNamespace(client_address=(peer, 1), headers=headers)

        def client_ip(h):
            return ServerApplication._api_v1_client_ip(app, h)

        self.assertEqual(client_ip(handler("9.9.9.9", **{"X-Forwarded-For": "1.1.1.1"})), "9.9.9.9")
        self.assertEqual(client_ip(handler("10.0.0.1", **{"X-Forwarded-For": "6.6.6.6, 1.2.3.4"})), "1.2.3.4")
        self.assertEqual(client_ip(handler("10.0.0.1", **{"CF-Connecting-IP": "5.5.5.5"})), "5.5.5.5")
        self.assertEqual(client_ip(handler("10.0.0.1")), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
