import unittest
from unittest.mock import patch

from server.status import StatusCollector, check_google_service, check_phenikaa_portal


class StatusCollectorTests(unittest.TestCase):
    def test_collector_returns_operational_payload_when_healthy(self):
        mock_p = lambda timeout: {
            "name": "Phenikaa Student Portal",
            "target": "qldtbeta.phenikaa-uni.edu.vn",
            "ok": True,
            "status": "operational",
            "code": 200,
            "latency_ms": 50,
            "message": "OK",
        }
        mock_g = lambda timeout: {
            "name": "Google Calendar Service",
            "target": "googleapis.com",
            "ok": True,
            "status": "operational",
            "code": 200,
            "latency_ms": 120,
            "message": "OK",
        }

        collector = StatusCollector(cache_ttl=10.0, probe_phenikaa=mock_p, probe_google=mock_g)
        res = collector.get_status(include_system={"db": "ok"})

        self.assertTrue(res["overall_ok"])
        self.assertEqual(res["overall_status"], "operational")
        self.assertNotIn("public_ip", res)
        self.assertEqual(res["services"]["phenikaa"]["status"], "operational")
        self.assertEqual(res["services"]["google"]["status"], "operational")
        self.assertEqual(res["system"]["db"], "ok")

    def test_collector_caches_results_and_honors_force_refresh(self):
        calls = {"p": 0, "g": 0}

        def mock_p(timeout):
            calls["p"] += 1
            return {"name": "Phenikaa", "ok": True, "status": "operational", "latency_ms": 10}

        def mock_g(timeout):
            calls["g"] += 1
            return {"name": "Google", "ok": True, "status": "operational", "latency_ms": 10}

        collector = StatusCollector(cache_ttl=60.0, probe_phenikaa=mock_p, probe_google=mock_g)

        # First call probes
        res1 = collector.get_status()
        self.assertEqual(calls["p"], 1)
        self.assertEqual(calls["g"], 1)

        # Second call within TTL hits cache
        res2 = collector.get_status()
        self.assertEqual(calls["p"], 1)
        self.assertEqual(calls["g"], 1)
        self.assertEqual(res1["checked_at"], res2["checked_at"])

        # Force refresh triggers new probe
        res3 = collector.get_status(force_refresh=True)
        self.assertEqual(calls["p"], 2)
        self.assertEqual(calls["g"], 2)

    def test_collector_identifies_degraded_and_unreachable_states(self):
        mock_p_fail = lambda timeout: {
            "name": "Phenikaa",
            "ok": False,
            "status": "unreachable",
            "latency_ms": 4000,
            "error": "timed out",
        }
        mock_g_ok = lambda timeout: {
            "name": "Google",
            "ok": True,
            "status": "operational",
            "latency_ms": 100,
        }

        collector = StatusCollector(probe_phenikaa=mock_p_fail, probe_google=mock_g_ok)
        res = collector.get_status()

        self.assertFalse(res["overall_ok"])
        self.assertEqual(res["overall_status"], "degraded")
        self.assertNotIn("public_ip", res)
        self.assertEqual(res["services"]["phenikaa"]["status"], "unreachable")
        self.assertEqual(res["services"]["google"]["status"], "operational")

        # Both fail -> major_outage
        mock_g_fail = lambda timeout: {
            "name": "Google",
            "ok": False,
            "status": "unreachable",
            "latency_ms": 4000,
            "error": "failed",
        }
        collector2 = StatusCollector(probe_phenikaa=mock_p_fail, probe_google=mock_g_fail)
        res2 = collector2.get_status()
        self.assertFalse(res2["overall_ok"])
        self.assertEqual(res2["overall_status"], "major_outage")


if __name__ == "__main__":
    unittest.main()
