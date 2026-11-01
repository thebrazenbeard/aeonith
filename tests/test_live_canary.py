"""Offline/live-loopback tests for the opt-in service canary."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
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

    def test_explicit_three_lens_canary_and_invalid_selection(self):
        selection = live_canary.parse_lenses("literary_thematic,stylistic,symbolic")
        self.assertEqual(selection, live_canary.PILOT_LENSES)
        self.assertEqual(live_canary.canary_request(selection)["lenses"], list(selection))
        subset = completed_review()
        subset["lens_reviews"] = [item for item in subset["lens_reviews"] if item["lens"] in selection]
        self.assertEqual(live_canary.examine_review(subset, selection)["lens_count"], 3)
        with self.assertRaisesRegex(live_canary.CanaryError, "lens_coverage_invalid"):
            live_canary.examine_review(subset)
        for bad in ("", ",stylistic", "unknown", "stylistic,stylistic"):
            with self.subTest(bad=bad), self.assertRaisesRegex(live_canary.CanaryError, "invalid_lenses"):
                live_canary.parse_lenses(bad)

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

    def test_remote_host_requires_independent_confirmation(self):
        url = "https://aeonith-verified.vercel.app/api/review"
        for expected in (None, "", "other.vercel.app", "https://aeonith-verified.vercel.app"):
            with self.subTest(expected=expected), self.assertRaisesRegex(
                live_canary.CanaryError, "remote_host_confirmation_required"
            ):
                live_canary.confirm_remote_host(url, expected)
        live_canary.confirm_remote_host(url, "AEONITH-VERIFIED.VERCEL.APP")
        live_canary.confirm_remote_host("http://127.0.0.1:8000/api/review", None)

    def test_remote_rejected_before_secret_lookup_and_network(self):
        stream = io.StringIO()
        with patch.object(live_canary, "_secret_from_env", side_effect=AssertionError("secret read")):
            with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
                with redirect_stdout(stream):
                    code = live_canary.main([
                        "--execute", "--allow-paid-inference",
                        "--url", "https://arbitrary.example/api/review",
                    ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "remote_host_confirmation_required")

    def test_direct_remote_invoke_cannot_bypass_confirmation(self):
        with self.assertRaisesRegex(live_canary.CanaryError, "remote_host_confirmation_required"):
            live_canary.invoke_canary(
                "https://arbitrary.example/api/review", token="synthetic-test-only", timeout=1
            )

    def test_protection_options_are_mutually_exclusive_before_secrets(self):
        stream = io.StringIO()
        with patch.object(live_canary, "_secret_from_env", side_effect=AssertionError("secret read")):
            with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
                with redirect_stdout(stream), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as exited:
                        live_canary.main([
                            "--execute", "--allow-paid-inference",
                            "--url", "https://aeonith-verified.vercel.app/api/review",
                            "--expected-host", "aeonith-verified.vercel.app",
                            "--vercel-bypass-env", "CANARY_TEST_BYPASS",
                            "--trusted-oidc-env", "CANARY_TEST_OIDC",
                        ])
        self.assertEqual(exited.exception.code, 2)
        self.assertEqual(stream.getvalue(), "")

    def test_invalid_trusted_oidc_rejected_before_service_secret(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {"CANARY_TEST_OIDC": "malformed-oauth-secret"}, clear=True):
            with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
                with redirect_stdout(stream):
                    code = live_canary.main([
                        "--execute", "--allow-paid-inference",
                        "--url", "https://aeonith-verified.vercel.app/api/review",
                        "--expected-host", "aeonith-verified.vercel.app",
                        "--trusted-oidc-env", "CANARY_TEST_OIDC",
                        "--auth-env", "SHOULD_NOT_BE_READ",
                    ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "trusted_oidc_token_missing_or_invalid")
        self.assertNotIn("malformed-oauth-secret", stream.getvalue())

    def test_remote_host_mismatch_rejected_before_trusted_oidc_lookup(self):
        stream = io.StringIO()
        with patch.object(live_canary, "_trusted_oidc_from_env", side_effect=AssertionError("OIDC secret read")):
            with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
                with redirect_stdout(stream):
                    code = live_canary.main([
                        "--execute", "--allow-paid-inference",
                        "--url", "https://untrusted.vercel.app/api/review",
                        "--expected-host", "trusted.vercel.app",
                        "--trusted-oidc-env", "CANARY_TEST_OIDC",
                    ])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "remote_host_confirmation_required")

    def test_trusted_oidc_rejects_non_vercel_target_before_secret_lookup(self):
        for url, host in (
            ("https://arbitrary.example/api/review", "arbitrary.example"),
            ("http://127.0.0.1:8123/api/review", "127.0.0.1"),
        ):
            stream = io.StringIO()
            with self.subTest(url=url):
                with patch.object(live_canary, "_trusted_oidc_from_env", side_effect=AssertionError("OIDC secret read")):
                    with patch.object(live_canary, "invoke_canary", side_effect=AssertionError("network called")):
                        with redirect_stdout(stream):
                            code = live_canary.main([
                                "--execute", "--allow-paid-inference", "--url", url,
                                "--expected-host", host, "--trusted-oidc-env", "CANARY_TEST_OIDC",
                            ])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stream.getvalue())["reason"], "trusted_oidc_requires_vercel_preview")

    def test_direct_invocation_rejects_two_protection_methods(self):
        with self.assertRaisesRegex(live_canary.CanaryError, "protection_auth_methods_mutually_exclusive"):
            live_canary.invoke_canary(
                "http://127.0.0.1:8123/api/review", token="synthetic-only", timeout=1,
                bypass_token="test-bypass", trusted_oidc_token="e30.e30.c2ln",
            )

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
            "trusted_oidc": self.headers.get("x-vercel-trusted-oidc-idp-token"),
            "request_id": self.headers.get("X-Aeonith-Request-Id"),
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
        self.assertRegex(observed["request_id"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertEqual(observed["path"], "/api/review")
        self.assertEqual(json.loads(observed["body"]), live_canary.canary_request())

    def test_small_pilot_canary_hits_only_requested_lenses(self):
        subset = completed_review()
        subset["lens_reviews"] = [row for row in subset["lens_reviews"] if row["lens"] in live_canary.PILOT_LENSES]
        _FakeService.response_body = json.dumps(subset).encode("utf-8")
        stream = io.StringIO()
        with patch.dict(os.environ, {"CANARY_TEST_AUTH": "test-only-secret"}), redirect_stdout(stream):
            code = live_canary.main([
                "--url", self.url, "--execute", "--allow-paid-inference",
                "--auth-env", "CANARY_TEST_AUTH",
                "--lenses", ",".join(live_canary.PILOT_LENSES),
            ])
        self.assertEqual(code, 0, stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["lens_count"], 3)
        self.assertEqual(json.loads(_FakeService.requests[0]["body"])["lenses"], list(live_canary.PILOT_LENSES))

    def test_short_lived_trusted_oidc_header_without_bypass(self):
        stream = io.StringIO()
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJ0ZXN0In0.c2lnbmF0dXJl"
        expected_origin = "https://aeonith-approved-preview.vercel.app/api/review"
        captured: dict = {}

        class SyntheticResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _maximum):
                return json.dumps(completed_review()).encode("utf-8")

        class SyntheticOpener:
            def open(self, request, timeout):
                captured["request"] = request
                captured["timeout"] = timeout
                return SyntheticResponse()

        with patch.dict(os.environ, {
            "CANARY_TEST_AUTH": "synthetic-service-secret",
            "CANARY_TEST_OIDC": jwt,
        }), redirect_stdout(stream):
            with patch.object(live_canary, "build_opener", return_value=SyntheticOpener()):
                code = live_canary.main([
                    "--url", expected_origin, "--expected-host", "aeonith-approved-preview.vercel.app",
                    "--execute", "--allow-paid-inference", "--auth-env", "CANARY_TEST_AUTH",
                    "--trusted-oidc-env", "CANARY_TEST_OIDC",
                ])
        self.assertEqual(code, 0, stream.getvalue())
        request = captured["request"]
        self.assertEqual(request.full_url, expected_origin)
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(headers["x-vercel-trusted-oidc-idp-token"], jwt)
        self.assertEqual(headers["authorization"], "Bearer synthetic-service-secret")
        self.assertNotIn("x-vercel-protection-bypass", headers)
        self.assertNotIn(jwt, stream.getvalue())

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
