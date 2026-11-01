"""Real-loopback tests for Aeonith's stdlib local UI and service boundary."""

from __future__ import annotations

import json
from http.client import HTTPConnection
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from aeonith import local_server
from aeonith.local_server import create_server


_TOKEN = "T" * 48
_CONFIG = {
    "AEONITH_SERVICE_TOKEN": _TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "local-openai-compatible",
    "AEONITH_PROVIDER_URL": "http://127.0.0.1:5001/v1/chat/completions",
    "AEONITH_PROVIDER_MODEL": "local-test-model",
}
_WORK = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Lantern", "text": "The lantern went dark. Nobody lit it."},
    "lenses": ["symbolic"],
}


class _FakeLocalModel:
    name = "fixture_local_model"

    def review(self, _payload):
        return {
            "lens_reviews": [{
                "lens": "symbolic",
                "analysis": "An unlit lantern may suggest fading hope, but alternative readings remain.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "The lantern went dark."}],
                "limitations": ["One isolated image cannot establish a universal meaning."],
            }],
            "synthesis": "The image invites provisional symbolic interpretation.",
            "uncertainties": ["The cause of the darkness is unknown."],
            "challenges": [],
            "assessment": None,
        }


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _request(self, path, *, method="GET", body=None, headers=None):
        outgoing = Request(self.url + path, method=method, data=body, headers=headers or {})
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(outgoing, timeout=4) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_loopback_default_and_all_nonloopback_are_rejected(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for host in ("0.0.0.0", "8.8.8.8", "example.com", "192.168.1.10"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                create_server(host=host, port=0)

    def test_ui_and_css_are_local_with_hardened_headers(self):
        for path, mime, marker in (
            ("/", "text/html", b"review-form"),
            ("/index.html", "text/html", b"review-form"),
            ("/app.js", "text/javascript", b"textContent"),
            ("/docx-import-worker.js", "text/javascript", b"inspectDocxZip"),
            ("/styles.css", "text/css", b"prefers-reduced-motion"),
        ):
            with self.subTest(path=path):
                status, headers, body = self._request(path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(mime))
                self.assertIn(marker, body)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Frame-Options"], "DENY")
                self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
                self.assertIn("worker-src 'self'", headers["Content-Security-Policy"])
                self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_chatgpt_tracking_link_redirects_to_clean_editor(self):
        # ChatGPT decorates app links. A safe redirect must strip the query
        # instead of serving the editor at the decorated URL.
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            connection.request("GET", "/?utm_source=chatgpt.com")
            response = connection.getresponse()
            self.assertEqual(response.status, 302)
            self.assertEqual(response.getheader("Location"), "/")
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(response.read(), b"")
        finally:
            connection.close()
        status, _, body = self._request("/?utm_source=chatgpt.com")
        self.assertEqual(status, 200)
        self.assertIn(b"review-form", body)
        status, _, _ = self._request("/?utm_source=chatgpt.com", method="POST", body=b"{}")
        self.assertEqual(status, 404)
        status, _, _ = self._request("/?utm_source=chatgpt.com", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)

    def test_wheel_installed_static_asset_fallback(self):
        # Simulate absence of a repository checkout beside installed package.
        public = Path(__file__).resolve().parents[1] / "public"
        with patch.object(local_server, "_SOURCE_PUBLIC", public / "missing-checkout"), \
             patch.object(local_server, "_INSTALLED_PUBLIC", public):
            status, _, body = self._request("/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"review-form", body)

    def test_public_health_is_liveness_only(self):
        with patch.dict(os.environ, {}, clear=True):
            for path in ("/healthz", "/api/health"):
                status, headers, body = self._request(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")
                payload = json.loads(body)
                self.assertEqual(payload["service"], "aeonith")
                self.assertFalse(payload["review_configured"])

    def test_rejects_unknown_methods_and_path_traversal(self):
        for path in ("/aeonith/service.py", "/%2e%2e/README.md", "/.env",
                     "/?token=private", "/?utm_source=chatgpt.com&token=private",
                     "/api/review?utm_source=chatgpt.com"):
            with self.subTest(path=path):
                status, _, body = self._request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"private", body)
        status, _, body = self._request("/healthz", method="POST", body=b"private")
        self.assertEqual(status, 405)
        self.assertNotIn(b"private", body)
        status, _, _ = self._request("/api/review", method="GET")
        self.assertEqual(status, 405)

    def test_rejects_dns_rebinding_and_cross_origin(self):
        for headers in ({"Host": "attacker.example"},
                        {"Origin": "http://attacker.example"}):
            with self.subTest(headers=headers):
                status, _, body = self._request("/app.js", headers=headers)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body)["error"]["code"], "forbidden_origin")

    def test_missing_token_denied_before_body_or_provider(self):
        with patch.dict(os.environ, _CONFIG, clear=True), \
             patch("api.review.process_review", side_effect=AssertionError("body was consumed")):
            status, _, data = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(data)["error"]["code"], "unauthorized")
        self.assertNotIn(b"lantern", data)

    def test_authorized_post_uses_local_service_with_no_real_model_call(self):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + _TOKEN,
        }
        with patch.dict(os.environ, _CONFIG, clear=True), \
             patch("aeonith.service._construct_provider", return_value=_FakeLocalModel()):
            status, _, data = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode("utf-8"),
                headers=headers,
            )
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["provenance"]["provider_name"], "fixture_local_model")


class PublicSessionTests(unittest.TestCase):
    """Real HTTP handling of a signed, host-pinned Funnel browser session."""

    _origin = "https://vn1.tail86ea75.ts.net"
    _host = "vn1.tail86ea75.ts.net"

    @classmethod
    def setUpClass(cls):
        cls.server = create_server(port=0, funnel_origin=cls._origin)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _request(self, path, *, method="GET", body=None, headers=None):
        request_headers = {"Host": self._host}
        if method == "POST":
            request_headers["Origin"] = self._origin
        request_headers.update(headers or {})
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def _login(self):
        status, headers, raw = self._request(
            "/api/session", method="POST", headers={"Authorization": "Bearer " + _TOKEN},
        )
        self.assertEqual(status, 200, raw)
        payload = json.loads(raw)
        self.assertEqual(payload, {"authenticated": True, "available": True})
        cookie_header = headers["Set-Cookie"]
        self.assertTrue(cookie_header.startswith("__Host-AeonithSession="))
        self.assertIn("; Path=/; Secure; HttpOnly; SameSite=Strict", cookie_header)
        self.assertIn("Max-Age=604800", cookie_header)
        self.assertNotIn("Domain=", cookie_header)
        self.assertEqual(headers["Cache-Control"], "no-store")
        return cookie_header.split(";", 1)[0]

    def test_login_status_review_and_logout(self):
        with patch.dict(os.environ, _CONFIG, clear=True), \
             patch("aeonith.service._construct_provider", return_value=_FakeLocalModel()):
            cookie = self._login()
            status, headers, raw = self._request("/api/session", headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["authenticated"], True)
            self.assertEqual(headers["Cache-Control"], "no-store")
            status, _, raw = self._request(
                "/api/review", method="POST", body=json.dumps(_WORK).encode("utf-8"),
                headers={"Cookie": cookie, "Content-Type": "application/json"},
            )
            self.assertEqual(status, 200, raw)
            self.assertEqual(json.loads(raw)["status"], "completed")
            status, headers, raw = self._request("/api/session/logout", method="POST", headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(raw)["authenticated"])
            self.assertTrue(headers["Set-Cookie"].startswith("__Host-AeonithSession=; Max-Age=0;"))
            self.assertNotIn("Domain=", headers["Set-Cookie"])
            # Browser discards the expired cookie. The following request has no credential.
            status, _, raw = self._request(
                "/api/review", method="POST", body=b"{}", headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 401)

    def test_cookie_tampering_expiry_duplication_and_bad_bearer_cannot_authenticate(self):
        with patch.dict(os.environ, _CONFIG, clear=True):
            cookie = self._login()
            name, value = cookie.split("=", 1)
            self.assertTrue(local_server._session_valid(value, _TOKEN, self._host))
            self.assertFalse(local_server._session_valid(value, _TOKEN, "other.tail.ts.net"))
            self.assertFalse(local_server._session_valid(value, "U" * 48, self._host))
            wrong = value[:-1] + ("A" if value[-1] != "A" else "B")
            for bad_cookie in (
                f"{name}={wrong}", f"{cookie}; {cookie}",
                f"{name}=v1.99999999999.{'N' * 32}.{'A' * 43}",
                f"{name}=v1.1.{'N' * 32}.{'A' * 43}",
            ):
                with self.subTest(cookie=bad_cookie[:40]):
                    status, _, raw = self._request("/api/session", headers={"Cookie": bad_cookie})
                    self.assertEqual(status, 200)
                    self.assertFalse(json.loads(raw)["authenticated"])
                    status, _, raw = self._request(
                        "/api/review", method="POST", body=b"private",
                        headers={"Cookie": bad_cookie, "Content-Type": "application/json"},
                    )
                    self.assertEqual(status, 401)
            status, _, raw = self._request(
                "/api/review", method="POST", body=b"private",
                headers={"Cookie": cookie, "Authorization": "Bearer incorrect"},
            )
            self.assertEqual(status, 401)

    def test_cross_origin_login_session_and_replay_are_denied(self):
        with patch.dict(os.environ, _CONFIG, clear=True):
            cookie = self._login()
            for method, path, headers in (
                ("POST", "/api/session", {"Authorization": "Bearer " + _TOKEN, "Origin": "https://evil.example"}),
                ("POST", "/api/review", {"Cookie": cookie, "Origin": "https://evil.example"}),
                ("POST", "/api/review", {"Cookie": cookie, "Origin": ""}),
                ("POST", "/api/session/logout", {"Cookie": cookie, "Origin": "https://evil.example"}),
                ("POST", "/api/review", {"Cookie": cookie, "Host": "evil.example"}),
            ):
                with self.subTest(path=path, headers=headers):
                    status, _, raw = self._request(path, method=method, body=b"private", headers=headers)
                    self.assertEqual(status, 403)
                    self.assertEqual(json.loads(raw)["error"]["code"], "forbidden_origin")

    def test_login_failures_never_issue_cookies_or_read_bodies(self):
        with patch.dict(os.environ, _CONFIG, clear=True):
            for headers, body, expected in (
                ({}, None, 401),
                ({"Authorization": "Bearer incorrect"}, None, 401),
                ({"Authorization": "Bearer " + _TOKEN}, b"manuscript", 400),
                ({"Authorization": "Bearer " + _TOKEN, "Transfer-Encoding": "chunked"}, None, 400),
            ):
                with self.subTest(headers=headers, body=body):
                    status, response_headers, raw = self._request(
                        "/api/session", method="POST", body=body, headers=headers,
                    )
                    self.assertEqual(status, expected, raw)
                    self.assertNotIn("Set-Cookie", response_headers)


if __name__ == "__main__":
    unittest.main()
