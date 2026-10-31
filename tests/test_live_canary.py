"""Offline/live-loopback tests for the opt-in service canary."""

from __future__ import annotations

from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import threading
import unittest
from unittest.mock import patch

from aeonith.core import CANONICAL_LENSES, SCHEMA
from scripts import live_canary


def completed_review() -> dict:
    return {
        "schema_version": SCHEMA,
        "status": "completed",
        "assessment": None,
        "lens_reviews": [
            {
                "lens": lens,
                "analysis": "The bell's mistake and the tide's indifference establish competing scales of consequence.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "the tide did not"}],
                "limitations": [],
            }
            for lens in CANONICAL_LENSES
        ],
        "synthesis": "The small town treats a mechanical error as comic; nature remains indifferent.",
        "challenges": [],
        "uncertainties": [],
        "evidence_audit": [],
        "provenance": {"review_source": "injected_provider", "provider_name": "test"},
        "error": None,
    }


class CanaryContractTests(unittest.TestCase):
    def test_canary_source_is_original_synthetic_and_contract_valid(self):
        request = live_canary.canary_request()
        self.assertEqual(request["schema_version"], SCHEMA)
        self.assertEqual(request["lenses"], list(CANONICAL_LENSES))
        self.assertNotIn("claims", request)
        self.assertIn("harbor bell", request["work"]["text"])
        self.assertEqual(live_canary.examine_review(completed_review())["lens_count"], 14)

    def test_default_has_no_network_and_no_secret_requirement(self):
        stream = io.StringIO()
        with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(stream):
                self.assertEqual(live_canary.main([]), 2)
        self.assertEqual(json.loads(stream.getvalue())["status"], "not_run")

    def test_paid_consent_required_before_env_and_network(self):
        stream = io.StringIO()
        with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(stream):
                self.assertEqual(live_canary.main(["--execute", "--url", "https://example.com/api/review"]), 2)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "paid_inference_consent_required")

    def test_explicit_url_and_env_required_before_network(self):
        stream = io.StringIO()
        with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(stream):
                self.assertEqual(live_canary.main(["--execute", "--allow-paid-inference"]), 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "url_required")

    def test_url_security_rules(self):
        valid = ["https://aeonith.example/api/review", "http://127.0.0.1:3210/api/review"]
        for url in valid:
            with self.subTest(url=url):
                live_canary.validate_url(url)
        for url in [
            "http://not-local.example/api/critique",
            "https://user:pass@example.com/api/critique",
            "https://example.com/api/critique?token=secret",
            "https://example.com/api/critique#fragment",
            "file:///etc/passwd",
            "https://example.com:bogus/api/critique",
        ]:
            with self.subTest(url=url), self.assertRaises(live_canary.CanaryError):
                live_canary.validate_url(url)

    def test_lens_mutation_rejected(self):
        result = completed_review()
        result["lens_reviews"][0]["lens"] = result["lens_reviews"][1]["lens"]
        with self.assertRaisesRegex(live_canary.CanaryError, "lens_coverage_invalid"):
            live_canary.examine_review(result)

    def test_unanchored_or_fabricated_evidence_rejected(self):
        result = completed_review()
        result["lens_reviews"][0]["support"] = [{"source": "work", "quote": "an invented line"}]
        with self.assertRaisesRegex(live_canary.CanaryError, "support_invalid"):
            live_canary.examine_review(result)
        result = completed_review()
        result["lens_reviews"][0]["support"] = []
        with self.assertRaisesRegex(live_canary.CanaryError, "textual_lens_unanchored"):
            live_canary.examine_review(result)

    def test_no_work_quote_anchor_rejected(self):
        result = completed_review()
        for row in result["lens_reviews"]:
            row["basis"] = "insufficient_text"
            row["support"] = []
            row["limitations"] = ["This excerpt is too short to judge this axis."]
        with self.assertRaisesRegex(live_canary.CanaryError, "no_textual_evidence_anchor"):
            live_canary.examine_review(result)

    def test_incomplete_or_provenance_free_rejected(self):
        result = completed_review()
        result["status"] = "provider_error"
        with self.assertRaisesRegex(live_canary.CanaryError, "response_not_completed"):
            live_canary.examine_review(result)
        result = completed_review()
        result["provenance"] = {"review_source": "none"}
        with self.assertRaisesRegex(live_canary.CanaryError, "provider_provenance_missing"):
            live_canary.examine_review(result)

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        with self.assertRaisesRegex(live_canary.CanaryError, "duplicate_json_field"):
            live_canary._strict_json(b'{"status":"completed","status":"completed"}')
        with self.assertRaisesRegex(live_canary.CanaryError, "non_finite_json"):
            live_canary._strict_json(b'{"x":NaN}')


class _FakeService(BaseHTTPRequestHandler):
    response_status = 200
    response_headers: dict[str, str] = {}
    response_body = b"{}"
    requests: list[dict] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "disclosure": self.headers.get("X-Aeonith-Disclosure"),
            "bypass": self.headers.get("x-vercel-protection-bypass"),
            "body": body,
        })
        self.send_response(type(self).response_status)
        for name, value in type(self).response_headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).response_body)

    def log_message(self, *_args):
        # Never print request headers, manuscript, or token in tests either.
        pass


class CanaryLoopbackTests(unittest.TestCase):
    def setUp(self):
        _FakeService.requests = []
        _FakeService.response_status = 200
        _FakeService.response_headers = {}
        _FakeService.response_body = json.dumps(completed_review()).encode("utf-8")
        self.server = HTTPServer(("127.0.0.1", 0), _FakeService)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/review"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_end_to_end_success_hides_credentials_and_manuscript(self):
        stream = io.StringIO()
        test_token = "local-secret-value-never-print"
        with patch.dict(os.environ, {"CANARY_TEST_AUTH": test_token, "CANARY_TEST_BYPASS": "bypass-never-print"}), redirect_stdout(stream):
            code = live_canary.main([
                "--url", self.url, "--execute", "--allow-paid-inference",
                "--auth-env", "CANARY_TEST_AUTH", "--vercel-bypass-env", "CANARY_TEST_BYPASS",
            ])
        self.assertEqual(code, 0)
        printed = stream.getvalue()
        summary = json.loads(printed)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["lens_count"], 14)
        self.assertEqual(summary["work_quote_anchors"], 14)
        self.assertNotIn(test_token, printed)
        self.assertNotIn("bypass-never-print", printed)
        self.assertNotIn(live_canary.CANARY_TEXT, printed)
        self.assertNotIn("harbor", printed)
        self.assertEqual(len(_FakeService.requests), 1)
        observed = _FakeService.requests[0]
        self.assertEqual(observed["authorization"], f"Bearer {test_token}")
        self.assertEqual(observed["disclosure"], "accepted")
        self.assertEqual(observed["bypass"], "bypass-never-print")
        self.assertEqual(observed["path"], "/api/review")
        self.assertEqual(json.loads(observed["body"]), live_canary.canary_request())

    def test_http_error_sanitized(self):
        _FakeService.response_status = 401
        _FakeService.response_body = b"upstream-private-error-and-secret"
        stream = io.StringIO()
        with patch.dict(os.environ, {"CANARY_TEST_AUTH": "hidden-secret"}), redirect_stdout(stream):
            code = live_canary.main([
                "--url", self.url, "--execute", "--allow-paid-inference", "--auth-env", "CANARY_TEST_AUTH",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "http_status_401")
        self.assertNotIn("upstream-private", stream.getvalue())
        self.assertNotIn("hidden-secret", stream.getvalue())

    def test_redirect_never_forwards_secret(self):
        _FakeService.response_status = 302
        _FakeService.response_headers = {"Location": "https://another.example/api/critique"}
        stream = io.StringIO()
        with patch.dict(os.environ, {"CANARY_TEST_AUTH": "must-not-redirect"}), redirect_stdout(stream):
            code = live_canary.main([
                "--url", self.url, "--execute", "--allow-paid-inference", "--auth-env", "CANARY_TEST_AUTH",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "redirect_refused")
        self.assertEqual(len(_FakeService.requests), 1)

    def test_no_environment_proxy_inheritance(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {
            "CANARY_TEST_AUTH": "hidden-secret",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }), redirect_stdout(stream):
            code = live_canary.main([
                "--url", self.url, "--execute", "--allow-paid-inference", "--auth-env", "CANARY_TEST_AUTH",
            ])
        self.assertEqual(code, 0, stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["status"], "passed")


if __name__ == "__main__":
    unittest.main()
