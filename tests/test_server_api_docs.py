import json
import unittest
from pathlib import Path

from server.api_v1 import openapi_document

DOCS = Path(__file__).resolve().parent.parent / "docs"


class ApiDocsTests(unittest.TestCase):
    def test_openapi_file_matches_the_code(self):
        generated = json.dumps(openapi_document(), indent=2, ensure_ascii=False).strip()
        current = (DOCS / "openapi-v1.yaml").read_text(encoding="utf-8").strip()
        self.assertEqual(
            generated, current,
            "docs/openapi-v1.yaml is out of date; regenerate it from server.api_v1.openapi_document()",
        )

    def test_sync_documents_the_new_errors(self):
        responses = openapi_document()["paths"]["/api/v1/sessions/{sessionId}/sync"]["post"]["responses"]
        for status in ("202", "409", "429", "503"):
            self.assertIn(status, responses)

    def test_delete_documents_the_calendar_option(self):
        operation = openapi_document()["paths"]["/api/v1/sessions/{sessionId}"]["delete"]
        parameters = {item["name"]: item for item in operation["parameters"]}
        self.assertEqual(set(parameters), {"sessionId", "calendar"})
        self.assertEqual(parameters["calendar"]["schema"]["enum"], ["keep", "hide", "delete"])
        self.assertEqual(parameters["calendar"]["schema"]["default"], "keep")
        for status in ("400", "409"):
            self.assertIn(status, operation["responses"])

    def test_public_api_guide_mentions_the_key_behaviour(self):
        guide = (DOCS / "PUBLIC_API.md").read_text(encoding="utf-8")
        for phrase in ("conflict_running", "Retry-After", "calendar=keep", "PHENIKAA_SERVER_TRUSTED_PROXIES"):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
