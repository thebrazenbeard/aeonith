"""Source-local HTTP boundary checks; never uses a paid model provider."""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from aeonith.service import authorize, is_ready, process_review
from api.health import handler as HealthHandler
from api.review import handler as ReviewHandler


TOKEN = "A" * 48
CONFIG = {
    "AEONITH_SERVICE_TOKEN": TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "openai-responses",
    "AEONITH_PROVIDER_URL": "https://provider.example.test/v1/responses",
    "AEONITH_PROVIDER_MODEL": "test-model",
    "AEONITH_PROVIDER_API_KEY": "example-not-a-real-key",
}
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Content-Type": "application/json",
    "X-Aeonith-Disclosure": "accepted",
}
WORK = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "A small story", "text": "The lantern went dark. Nobody lit it."},
    "lenses": ["symbolic"],
}


class FakeProvider:
    name = "test_fake_provider"

    def __init__(self):
        self.calls = 0

    def review(self, payload):
        self.calls += 1
        return {
            "lens_reviews": [{
                "lens": "symbolic",
                "analysis": "The darkened lantern permits several readings, not a settled allegory.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "The lantern went dark."}],
                "limitations": ["An isolated image does not prove a universal symbol code."],
            }],
            "synthesis": "The brief image supports a possible symbolic interpretation.",
            "uncertainties": ["The story does not state why the lantern darkens."],
            "challenges": [],
            "assessment": None,
        }


class ServicePureTests(unittest.TestCase):
    def _run(self, request=None, headers=None, env=None, provider=None):
        return process_review(
            json.dumps(WORK if request is None else request).encode(),
            HEADERS if headers is None else headers,
            CONFIG if env is None else env,
            provider=provider,
        )

    def test_ready_is_a_configuration_check_only(self):
        self.assertTrue(is_ready(CONFIG))
        self.assertFalse(is_ready({**CONFIG, "AEONITH_ENABLE_LIVE_REVIEWS": "false"}))
        self.assertFalse(is_ready({**CONFIG, "AEONITH_PROVIDER_API_KEY": ""}))

    def test_authentication_denies_absent_token_and_missing_service_secret(self):
        status, _ = authorize({}, CONFIG)
        self.assertEqual(status, 401)
        status, _ = authorize(HEADERS, {**CONFIG, "AEONITH_SERVICE_TOKEN": ""})
        self.assertEqual(status, 503)
        status, _ = authorize(HEADERS, {**CONFIG, "AEONITH_SERVICE_TOKEN": "é" * 48})
        self.assertEqual(status, 503)
        self.assertFalse(is_ready({**CONFIG, "AEONITH_SERVICE_TOKEN": "é" * 48}))
        status, _ = authorize({"Authorization": "Bearer " + "é" * 48}, CONFIG)
        self.assertEqual(status, 401)

    def test_successful_critique_uses_only_the_injected_test_provider(self):
        provider = FakeProvider()
        status, result = self._run(provider=provider)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["provenance"]["provider_name"], "test_fake_provider")

    def test_malformed_request_never_invokes_provider(self):
        provider = FakeProvider()
        status, result = self._run({"schema_version": "aeonith.review.v1",
                                    "work": {"title": "Sample", "text": ""}},
                                   provider=provider)
        self.assertEqual(status, 400)
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(provider.calls, 0)

    def test_caller_cannot_choose_provider_or_model(self):
        provider = FakeProvider()
        status, result = self._run({**WORK, "url": "http://127.0.0.1:9999",
                                     "api_key": "client-attacker-key"},
                                   provider=provider)
        self.assertEqual(status, 400)
        self.assertEqual(result["error"]["code"], "invalid_request")
        self.assertEqual(provider.calls, 0)

    def test_remote_disclosure_required_before_model_call(self):
        provider = FakeProvider()
        headers = dict(HEADERS)
        del headers["X-Aeonith-Disclosure"]
        status, result = self._run(headers=headers, provider=provider)
        self.assertEqual(status, 403)
        self.assertEqual(result["error"]["code"], "disclosure_required")
        self.assertEqual(provider.calls, 0)

    def test_disabled_reviews_never_call_provider(self):
        provider = FakeProvider()
        status, _ = self._run(env={**CONFIG, "AEONITH_ENABLE_LIVE_REVIEWS": "false"},
                              provider=provider)
        self.assertEqual(status, 503)
        self.assertEqual(provider.calls, 0)

    def test_rejects_nonfinite_scientific_notation_and_duplicate_keys(self):
        for raw in (
            b'{"schema_version":"aeonith.review.v1","schema_version":"invalid"}',
            b'{"schema_version":"aeonith.review.v1","work":{"text":"ok","weight":1e999}}',
        ):
            status, result = process_review(raw, HEADERS, CONFIG, provider=FakeProvider())
            self.assertEqual(status, 400)
            self.assertEqual(result["error"]["code"], "invalid_json")

    def test_upstream_exception_never_exposes_secret(self):
        class ExplodingProvider:
            def review(self, _payload):
                raise RuntimeError("provider secret should not be visible")
        status, result = self._run(provider=ExplodingProvider())
        self.assertEqual(status, 502)
        self.assertNotIn("secret", json.dumps(result))

    def test_wrong_media_type_or_huge_body_denied(self):
        status, _ = self._run(headers={**HEADERS, "Content-Type": "text/plain"},
                              provider=FakeProvider())
        self.assertEqual(status, 415)
        status, _ = process_review(b"x" * 1_000_001, HEADERS, CONFIG,
                                   provider=FakeProvider())
        self.assertEqual(status, 413)

    def test_unexpected_core_failure_is_sanitized(self):
        with patch("aeonith.service.critique", side_effect=RuntimeError("private manuscript panic")):
            status, result = self._run(provider=FakeProvider())
        self.assertEqual(status, 502)
        self.assertEqual(result["error"]["code"], "review_failed")
        self.assertNotIn("manuscript panic", json.dumps(result))


class ServiceHTTPTests(unittest.TestCase):
    def _serve(self, handler_class, request, *, method="GET", data=None, headers=None):
        server = HTTPServer(("127.0.0.1", 0), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, CONFIG, clear=True):
                url = f"http://127.0.0.1:{server.server_port}{request}"
                opener = build_opener(ProxyHandler({}))
                outgoing = Request(url, data=data, headers=headers or {}, method=method)
                try:
                    with opener.open(outgoing, timeout=4) as response:
                        return response.status, dict(response.headers), response.read()
                except HTTPError as exc:
                    return exc.code, dict(exc.headers), exc.read()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=4)

    def test_liveness_is_a_real_http_json_endpoint(self):
        status, headers, raw = self._serve(HealthHandler, "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(raw)["service"], "aeonith")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_review_is_not_public_get_endpoint(self):
        status, headers, raw = self._serve(ReviewHandler, "/api/review")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(raw)["error"]["code"], "method_not_allowed")

    def test_authenticated_post_is_a_real_http_json_endpoint(self):
        with patch("aeonith.service._construct_provider", return_value=FakeProvider()):
            status, headers, raw = self._serve(
                ReviewHandler, "/api/review", method="POST",
                data=json.dumps(WORK).encode("utf-8"), headers=HEADERS,
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(json.loads(raw)["status"], "completed")

    def test_unauthorized_post_does_not_return_private_body(self):
        status, _, raw = self._serve(
            ReviewHandler, "/api/review", method="POST",
            data=json.dumps(WORK).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(raw)["error"]["code"], "unauthorized")
        self.assertNotIn("lantern", raw.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
