"""Fully offline security tests for the opt-in protected-preview smoke runner."""

from __future__ import annotations

from contextlib import redirect_stdout
from email.message import Message
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import preview_smoke


ORIGIN = "https://aeonith-preview-example.vercel.app"
HOST = "aeonith-preview-example.vercel.app"


def _headers(content_type="application/json; charset=utf-8", cache="no-store"):
    headers = Message()
    headers["Content-Type"] = content_type
    headers["Cache-Control"] = cache
    return headers


def _reply(path: str):
    if path in {"/healthz", "/api/health"}:
        return 200, {
            "schema_version": "aeonith.health.v1", "service": "aeonith",
            "status": "ok", "review_configured": False,
        }
    if path == "/api/review":
        return 503, {
            "schema_version": "aeonith.review.v1", "status": "provider_unavailable",
            "error": {"code": "service_unconfigured", "message": "Review service is not configured"},
        }
    if path == "/api?aeonith_route=bogus":
        return 404, {
            "schema_version": "aeonith.review.v1", "status": "invalid_request",
            "error": {"code": "not_found", "message": "Unknown service route"},
        }
    raise AssertionError("unexpected test path")


class FakeResponse:
    def __init__(self, status, content, headers=None):
        self.status = status
        self.headers = headers or _headers()
        self.raw = io.BytesIO(content)

    def read(self, size=-1):
        return self.raw.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.raw.close()


class FakeOpener:
    def __init__(self):
        self.calls = []
        self.overrides = {}

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        path = request.full_url.removeprefix(ORIGIN)
        if path == "/healthz" and request.get_method() == "POST":
            status, body = 405, {
                "schema_version": "aeonith.review.v1", "status": "invalid_request",
                "error": {"code": "method_not_allowed", "message": "Method is not allowed for this route"},
            }
        elif path == "/api/review" and request.get_method() == "GET":
            status, body = 405, {
                "schema_version": "aeonith.review.v1", "status": "invalid_request",
                "error": {"code": "method_not_allowed", "message": "Method is not allowed for this route"},
            }
        else:
            status, body = _reply(path)
        status, body, headers = self.overrides.get((request.get_method(), path), (status, body, _headers()))
        raw = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
        if status >= 400:
            raise HTTPError(request.full_url, status, "synthetic error", headers, io.BytesIO(raw))
        return FakeResponse(status, raw, headers)


class PreviewSmokeTests(unittest.TestCase):
    def test_default_is_noop_even_without_origin_or_credentials(self):
        stream = io.StringIO()
        with patch.object(preview_smoke, "build_opener", side_effect=AssertionError("network")):
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(stream):
                self.assertEqual(preview_smoke.main([]), 2)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "explicit_execution_required")

    def test_exact_https_preview_origin_and_host_required(self):
        preview_smoke.confirm_origin(ORIGIN, HOST)
        preview_smoke.confirm_origin(ORIGIN, HOST.upper())
        bad_origins = (
            "", "http://" + HOST, ORIGIN + "/", ORIGIN + "/api/review",
            ORIGIN + "?token=x", ORIGIN + "#section", ORIGIN.replace(".vercel.app", ".example"),
            "https://user:pass@" + HOST, "https://" + HOST + ":8443",
            "https://vercel.app", "https://evil.vercel.app.evil.net",
            "https://" + HOST + "\n.evil.net",
        )
        for origin in bad_origins:
            with self.subTest(origin=origin), self.assertRaises(preview_smoke.PreviewSmokeError):
                preview_smoke.confirm_origin(origin, HOST)
        for expected in (None, "", "different.vercel.app", "https://" + HOST):
            with self.subTest(expected=expected), self.assertRaisesRegex(
                preview_smoke.PreviewSmokeError, "remote_host_confirmation_required"):
                preview_smoke.confirm_origin(ORIGIN, expected)

    def test_host_confirmed_before_token_read_or_network(self):
        stream = io.StringIO()
        with patch.object(preview_smoke, "_oidc_header", side_effect=AssertionError("token read")):
            with patch.object(preview_smoke, "build_opener", side_effect=AssertionError("network")):
                with redirect_stdout(stream):
                    status = preview_smoke.main([
                        "--execute", "--origin", ORIGIN, "--trusted-oidc-env", "SECRET_ENV",
                    ])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stream.getvalue())["reason"], "remote_host_confirmation_required")

    def test_bad_token_env_fails_before_network(self):
        for name in ("BAD-NAME", "MISSING_TOKEN"):
            with self.subTest(name=name):
                with patch.dict(os.environ, {}, clear=True):
                    with patch.object(preview_smoke, "build_opener", side_effect=AssertionError("network")):
                        with self.assertRaises(preview_smoke.PreviewSmokeError):
                            preview_smoke.run_smoke(ORIGIN, expected_host=HOST, trusted_oidc_env=name)
        with patch.dict(os.environ, {"TEST_OIDC": "has\nnewline"}):
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "trusted_oidc_token_missing_or_invalid"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST, trusted_oidc_env="TEST_OIDC")
        with patch.dict(os.environ, {"AEONITH_SERVICE_TOKEN": "app-service-token-not-oidc"}):
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "trusted_oidc_token_missing_or_invalid"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST, trusted_oidc_env="AEONITH_SERVICE_TOKEN")

    def test_six_nonbillable_checks_success_without_app_bearer(self):
        opener = FakeOpener()
        with patch.object(preview_smoke, "build_opener", return_value=opener) as builder:
            count = preview_smoke.run_smoke(ORIGIN, expected_host=HOST)
        self.assertEqual(count, 6)
        self.assertEqual(len(opener.calls), 6)
        self.assertEqual(builder.call_count, 6)
        for request, timeout in opener.calls:
            headers = dict((key.lower(), value) for key, value in request.header_items())
            self.assertNotIn("authorization", headers)
            self.assertNotIn("x-aeonith-disclosure", headers)
            self.assertEqual(timeout, 8.0)
            self.assertTrue(request.full_url.startswith(ORIGIN + "/"))
            if request.get_method() == "POST":
                self.assertEqual(request.data, b"")
        self.assertEqual([r.get_method() for r, _ in opener.calls].count("POST"), 2)

    def test_token_only_to_exact_confirmed_origin_and_not_printed(self):
        opener = FakeOpener()
        stream = io.StringIO()
        token = "synthetic.header.signature"
        with patch.dict(os.environ, {"TEST_TRUSTED_OIDC": token}):
            with patch.object(preview_smoke, "build_opener", return_value=opener):
                with redirect_stdout(stream):
                    exit_code = preview_smoke.main([
                        "--execute", "--origin", ORIGIN,
                        "--expected-host", HOST,
                        "--trusted-oidc-env", "TEST_TRUSTED_OIDC",
                    ])
        self.assertEqual(exit_code, 0)
        report = json.loads(stream.getvalue())
        self.assertEqual(report, {"checks": 6, "paid_inference_calls": 0, "status": "passed"})
        self.assertNotIn(token, stream.getvalue())
        for request, _ in opener.calls:
            self.assertEqual(request.get_header("X-vercel-trusted-oidc-idp-token"), token)
            self.assertNotIn("authorization", {k.lower() for k, v in request.header_items()})

    def test_service_rejects_unexpected_review_success(self):
        opener = FakeOpener()
        opener.overrides[("POST", "/api/review")] = (
            200, {"schema_version": "aeonith.review.v1", "status": "completed", "error": None}, _headers(),
        )
        with patch.object(preview_smoke, "build_opener", return_value=opener):
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "review_unauthorized_contract_failed"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST)

    def test_configured_review_rejection_401_is_accepted(self):
        opener = FakeOpener()
        opener.overrides[("POST", "/api/review")] = (
            401, {"schema_version": "aeonith.review.v1", "error": {"code": "unauthorized"}}, _headers(),
        )
        with patch.object(preview_smoke, "build_opener", return_value=opener):
            self.assertEqual(preview_smoke.run_smoke(ORIGIN, expected_host=HOST), 6)

    def test_protection_login_and_non_json_never_count_as_success(self):
        opener = FakeOpener()
        opener.overrides[("GET", "/healthz")] = (200, b"<html>login</html>", _headers("text/html"))
        with patch.object(preview_smoke, "build_opener", return_value=opener):
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "health:non_json_response"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST)

    def test_wrong_error_contract_rejected(self):
        opener = FakeOpener()
        opener.overrides[("GET", "/api?aeonith_route=bogus")] = (
            404, {"schema_version": "aeonith.review.v1", "error": {"code": "wrong"}}, _headers(),
        )
        with patch.object(preview_smoke, "build_opener", return_value=opener):
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "unknown_route:error_contract_failed"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST)

    def test_proxy_disabled_and_redirects_never_followed(self):
        opener = FakeOpener()
        with patch.object(preview_smoke, "build_opener", return_value=opener) as builder:
            preview_smoke.run_smoke(ORIGIN, expected_host=HOST)
        for invocation in builder.call_args_list:
            self.assertIsInstance(invocation.args[0], preview_smoke.ProxyHandler)
            self.assertEqual(invocation.args[0].proxies, {})
            redirect = invocation.args[1]
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "redirect_refused"):
                redirect.redirect_request(None, None, 302, "synthetic", None, "https://attacker.example")

    def test_boundaries_and_response_limit(self):
        for timeout in (0, -1, 16, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(
                preview_smoke.PreviewSmokeError, "timeout_out_of_bounds"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST, timeout=timeout)
        opener = FakeOpener()
        opener.overrides[("GET", "/healthz")] = (200, b"z" * 70_000, _headers())
        with patch.object(preview_smoke, "build_opener", return_value=opener):
            with self.assertRaisesRegex(preview_smoke.PreviewSmokeError, "health:response_too_large"):
                preview_smoke.run_smoke(ORIGIN, expected_host=HOST)


if __name__ == "__main__":
    unittest.main()
