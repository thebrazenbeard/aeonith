"""Local-only simulation of Tailscale Funnel's public HTTPS HTTP headers.

No Tailscale network, cloud service, or real model is contacted by these tests.
The application still listens exclusively on a loopback socket.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from aeonith.funnel_limits import LocalAdmission
from aeonith.local_server import _LocalHandler, _funnel_host, create_server


_ORIGIN = "https://aeonith.home-lab.ts.net"
_HOST = "aeonith.home-lab.ts.net"
_TOKEN = "safe-local-test-token-" + "A" * 32
_ENV = {
    "AEONITH_SERVICE_TOKEN": _TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "local-openai-compatible",
    "AEONITH_PROVIDER_URL": "http://127.0.0.1:5001/v1/chat/completions",
    "AEONITH_PROVIDER_MODEL": "local",
}
_WORK = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Lantern", "text": "The lantern went dark."},
    "lenses": ["symbolic"],
}


class _FakeModel:
    name = "local_funnel_fixture"

    def review(self, _payload):
        return {
            "lens_reviews": [{
                "lens": "symbolic",
                "analysis": "The extinguished lantern may imply loss without proving it.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "The lantern went dark."}],
                "limitations": ["Context is too short to establish the intention."],
            }],
            "synthesis": "The image invites provisional interpretations.",
            "uncertainties": ["The cause of darkness is unstated."],
            "challenges": [],
            "assessment": None,
        }


class FunnelOriginValidationTests(unittest.TestCase):
    def test_exact_tailscale_public_origin_only(self):
        self.assertEqual(_funnel_host(_ORIGIN), _HOST)
        self.assertIsNone(_funnel_host(None))
        self.assertIsNone(_funnel_host(""))
        for value in (
            "https://aeonith.ts.net", "https://ts.net",
            "https://extra.a.b.ts.net",
            "http://aeonith.home-lab.ts.net", "https://evil.example",
            "https://aeonith.home-lab.ts.net.evil.test",
            "https://a..home-lab.ts.net", "https://-bad.home-lab.ts.net",
            "https://aeonith.home-lab.ts.net/",
            "https://aeonith.home-lab.ts.net:443",
            "https://aeonith.home-lab.ts.net?next=evil",
            "https://aeonith.home-lab.ts.net#token",
            "https://user:pass@aeonith.home-lab.ts.net",
            "https://*.home-lab.ts.net",
            "HTTPS://aeonith.home-lab.ts.net",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _funnel_host(value)

    def test_public_mode_keeps_loopback_only_bind(self):
        for bind in ("0.0.0.0", "192.168.1.55", "::1"):
            with self.subTest(bind=bind), self.assertRaises(ValueError):
                create_server(host=bind, port=0, funnel_origin=_ORIGIN)

    def test_invalid_funnel_env_fails_closed_during_server_startup(self):
        with patch.dict(os.environ, {"AEONITH_FUNNEL_ORIGIN": "https://evil.example"}):
            with self.assertRaises(ValueError):
                create_server(port=0)


class FunnelHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=0, funnel_origin=_ORIGIN)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _request(self, path, *, method="GET", body=None, headers=None):
        req = Request(self.endpoint + path, method=method, data=body, headers=headers or {})
        client = build_opener(ProxyHandler({}))
        try:
            with client.open(req, timeout=4) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_public_host_serves_ui_with_security_headers(self):
        status, headers, data = self._request("/", headers={"Host": _HOST})
        self.assertEqual(status, 200)
        self.assertIn(b"review-form", data)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_wrong_host_and_origin_are_rejected_regardless_of_proxy_claims(self):
        cases = (
            {"Host": "attacker.example", "X-Forwarded-Host": _HOST,
             "X-Forwarded-Proto": "https"},
            {"Host": _HOST, "Origin": "https://attacker.example"},
            {"Host": _HOST, "Origin": "http://" + _HOST},
            {"Host": _HOST, "Origin": "null"},
            {"Host": "localhost", "Origin": _ORIGIN},
            {"Host": _HOST + ".evil.test", "Origin": _ORIGIN},
        )
        for request_headers in cases:
            with self.subTest(headers=request_headers):
                code, _headers, data = self._request("/app.js", headers=request_headers)
                self.assertEqual(code, 403)
                self.assertEqual(json.loads(data)["error"]["code"], "forbidden_origin")

    def test_host_pin_cannot_be_changed_by_later_environment_mutation(self):
        with patch.dict(os.environ, {"AEONITH_FUNNEL_ORIGIN": "https://attacker.evil.ts.net"}):
            code, _headers, _body = self._request("/", headers={"Host": _HOST})
            self.assertEqual(code, 200)
            code, _headers, _body = self._request("/", headers={"Host": "attacker.evil.ts.net"})
            self.assertEqual(code, 403)

    def test_localhost_remains_usable_with_funnel_configured(self):
        code, _headers, _body = self._request("/healthz")
        self.assertEqual(code, 200)

    def test_public_post_requires_bearer_before_body(self):
        with patch.dict(os.environ, _ENV, clear=True), \
             patch("api.review.process_review", side_effect=AssertionError("body read")):
            code, _headers, data = self._request(
                "/api/review", method="POST", body=b"private manuscript",
                headers={"Host": _HOST, "Origin": _ORIGIN,
                         "Content-Type": "application/json"},
            )
        self.assertEqual(code, 401)
        self.assertNotIn(b"manuscript", data)

    def test_authorized_public_post_uses_local_model_without_external_request(self):
        with patch.dict(os.environ, _ENV, clear=True), \
             patch("aeonith.service._construct_provider", return_value=_FakeModel()):
            code, headers, data = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode(),
                headers={"Host": _HOST, "Origin": _ORIGIN,
                         "Content-Type": "application/json",
                         "Authorization": "Bearer " + _TOKEN},
            )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["status"], "completed")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_second_review_route_uses_same_authorization_boundary(self):
        with patch.dict(os.environ, _ENV, clear=True), \
             patch("aeonith.service._construct_provider", return_value=_FakeModel()):
            code, _headers, data = self._request(
                "/v1/critique", method="POST", body=json.dumps(_WORK).encode(),
                headers={"Host": _HOST, "Origin": _ORIGIN,
                         "Content-Type": "application/json",
                         "Authorization": "Bearer " + _TOKEN},
            )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["status"], "completed")

    def test_bad_token_throttle_before_manuscript_read(self):
        tiny = LocalAdmission(max_auth_failures_per_minute=1)
        with patch.object(self.server, "public_limiter", tiny), \
             patch.dict(os.environ, _ENV, clear=True), \
             patch("api.review.process_review", side_effect=AssertionError("body read")):
            request_headers = {
                "Host": _HOST, "Origin": _ORIGIN,
                "Content-Type": "application/json",
                "Authorization": "Bearer wrong-token",
            }
            first, _headers, _data = self._request(
                "/api/review", method="POST", body=b"private data", headers=request_headers,
            )
            second, headers, data = self._request(
                "/api/review", method="POST", body=b"private data", headers=request_headers,
            )
        self.assertEqual(first, 401)
        self.assertEqual(second, 429)
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        self.assertNotIn(b"private", data)

    def test_failed_auth_flood_does_not_lock_out_valid_owner(self):
        tiny = LocalAdmission(max_auth_failures_per_minute=1, max_reviews_per_hour=2)
        with patch.object(self.server, "public_limiter", tiny), \
             patch.dict(os.environ, _ENV, clear=True), \
             patch("aeonith.service._construct_provider", return_value=_FakeModel()):
            base_headers = {"Host": _HOST, "Origin": _ORIGIN,
                            "Content-Type": "application/json"}
            wrong = {**base_headers, "Authorization": "Bearer invalid"}
            good = {**base_headers, "Authorization": "Bearer " + _TOKEN}
            self.assertEqual(self._request(
                "/api/review", method="POST", body=b"private", headers=wrong,
            )[0], 401)
            self.assertEqual(self._request(
                "/api/review", method="POST", body=b"private", headers=wrong,
            )[0], 429)
            status, _headers, response = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode(),
                headers=good,
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "completed")

    def test_empty_query_and_fragment_suffixes_are_not_routes(self):
        # A normal HTTP client strips URI fragments before transmission. Test
        # raw parser input directly so the forbidden '#' suffix is exercised.
        instance = _LocalHandler.__new__(_LocalHandler)
        for path in ("/api/review?", "/api/review#"):
            with self.subTest(path=path):
                instance.path = path
                self.assertIsNone(instance._route())
        with patch.dict(os.environ, _ENV, clear=True):
            status, _headers, _response = self._request(
                "/api/review?", method="POST", body=b"private",
                headers={"Host": _HOST, "Origin": _ORIGIN},
            )
        self.assertEqual(status, 404)

    def test_public_quota_cannot_be_bypassed_with_local_host_header(self):
        tiny = LocalAdmission(max_reviews_per_hour=1)
        with patch.object(self.server, "public_limiter", tiny), \
             patch.dict(os.environ, _ENV, clear=True), \
             patch("aeonith.service._construct_provider", return_value=_FakeModel()) as factory:
            body = json.dumps(_WORK).encode()
            first, _h1, _d1 = self._request(
                "/api/review", method="POST", body=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + _TOKEN},
            )
            second, h2, d2 = self._request(
                "/api/review", method="POST", body=body,
                headers={"Host": _HOST, "Origin": _ORIGIN,
                         "Content-Type": "application/json", "Authorization": "Bearer " + _TOKEN},
            )
        self.assertEqual(first, 200)
        self.assertEqual(second, 429)
        self.assertEqual(json.loads(d2)["error"]["code"], "review_rate_limited")
        self.assertGreaterEqual(int(h2["Retry-After"]), 1)
        # The successful path checks readiness and then constructs its model;
        # the denied path must not construct either instance.
        self.assertEqual(factory.call_count, 2)

    def test_malicious_cross_origin_post_never_calls_model(self):
        with patch.dict(os.environ, _ENV, clear=True), \
             patch("aeonith.service._construct_provider", side_effect=AssertionError("model call")):
            code, _headers, data = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode(),
                headers={"Host": _HOST, "Origin": "https://attacker.example",
                         "Content-Type": "application/json",
                         "Authorization": "Bearer " + _TOKEN},
            )
        self.assertEqual(code, 403)
        self.assertNotIn(b"lantern", data.lower())

    def test_public_post_without_origin_fails_closed(self):
        with patch.dict(os.environ, _ENV, clear=True):
            code, _headers, data = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode(),
                headers={"Host": _HOST, "Content-Type": "application/json",
                         "Authorization": "Bearer " + _TOKEN},
            )
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(data)["error"]["code"], "forbidden_origin")


if __name__ == "__main__":
    unittest.main()
