"""Regression for Vercel's single explicit Python entrypoint contract.

The first real Vercel build failed with PYTHON_ENTRYPOINT_NOT_FOUND because
it found two custom handler candidates and no selected entrypoint.
"""

from __future__ import annotations

from email.message import Message
import io
import json
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch

from api.index import handler as VercelHandler
from api.review import handler as ReviewHandler


ROOT = Path(__file__).resolve().parents[1]


def invoke(method: str, path: str = "/api?aeonith_route=health",
           *, body: bytes = b"", headers: list[tuple[str, str]] | None = None,
           environ: dict[str, str] | None = None) -> tuple[int, dict, int]:
    instance = VercelHandler.__new__(VercelHandler)
    instance.rfile = io.BytesIO(body)
    instance.wfile = io.BytesIO()
    instance.request_version = "HTTP/1.1"
    instance.requestline = f"{method} {path} HTTP/1.1"
    instance.command = method
    instance.path = path
    instance.client_address = ("127.0.0.1", 0)
    instance.headers = Message()
    for name, value in headers or []:
        instance.headers.add_header(name, value)
    with patch.dict("os.environ", environ or {}, clear=True):
        getattr(instance, f"do_{method}")()
    _, body = instance.wfile.getvalue().split(b"\r\n\r\n", 1)
    status = int(instance.wfile.getvalue().split(b"\r\n", 1)[0].split()[1])
    return status, json.loads(body), instance.rfile.tell()


class VercelEntrypointTests(unittest.TestCase):
    def test_explicit_unique_python_entrypoint_configured(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["tool"]["vercel"]["entrypoint"], "api.index:handler")
        self.assertTrue(issubclass(VercelHandler, ReviewHandler))

    def test_public_routes_rewrite_to_explicit_route_markers(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        rewrites = {rule["source"]: rule for rule in config["rewrites"]}
        for source in ("/healthz", "/api/health"):
            self.assertEqual(rewrites[source]["destination"], "/api?aeonith_route=health")
        for source in ("/v1/critique", "/api/review"):
            self.assertEqual(rewrites[source]["destination"], "/api?aeonith_route=review")
        for source, rule in rewrites.items():
            with self.subTest(source=source):
                self.assertIn({"type": "query", "key": "aeonith_route"}, rule.get("missing", []))

    def test_health_routes_get_only(self):
        for path in ("/healthz", "/api/health", "/api?aeonith_route=health"):
            with self.subTest(path=path):
                code, result, _ = invoke("GET", path)
                self.assertEqual(code, 200)
                self.assertEqual(result["status"], "ok")
                self.assertFalse(result["review_configured"])

                code, result, read_count = invoke("POST", path, body=b"private text")
                self.assertEqual(code, 405)
                self.assertEqual(result["error"]["code"], "method_not_allowed")
                self.assertEqual(read_count, 0)

    def test_review_routes_post_only(self):
        for path in ("/v1/critique", "/api/review", "/api?aeonith_route=review"):
            with self.subTest(path=path):
                code, result, _ = invoke("GET", path)
                self.assertEqual(code, 405)
                self.assertEqual(result["error"]["code"], "method_not_allowed")

                code, result, _ = invoke("POST", path)
                self.assertEqual(code, 503)
                self.assertEqual(result["error"]["code"], "service_unconfigured")

    def test_unmarked_ambiguous_and_foreign_routes_fail_closed(self):
        for path in (
            "/api", "/api?aeonith_route=health&aeonith_route=review",
            "/api?aeonith_route=bogus", "/api?aeonith_route=review&extra=1",
            "/api/unknown", "/unknown",
        ):
            with self.subTest(path=path):
                code, result, read_count = invoke("POST", path, body=b"private text")
                self.assertEqual(code, 404)
                self.assertEqual(result["error"]["code"], "not_found")
                self.assertEqual(read_count, 0)

    def test_explicit_url_path_outranks_spoofed_route_hint(self):
        code, result, read_count = invoke("POST", "/healthz?aeonith_route=review",
                                          body=b"private text")
        self.assertEqual(code, 405)
        self.assertEqual(result["error"]["code"], "method_not_allowed")
        self.assertEqual(read_count, 0)

    def test_unsupported_methods_never_read_request_bodies(self):
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS"):
            for path, expected in (("/api/review", 405), ("/healthz", 405), ("/not-a-route", 404)):
                with self.subTest(method=method, path=path):
                    code, result, read_count = invoke(method, path, body=b"private text")
                    self.assertEqual(code, expected)
                    self.assertEqual(read_count, 0)
                    self.assertEqual(result["error"]["code"],
                                     "method_not_allowed" if expected == 405 else "not_found")

    def test_paid_handler_cannot_run_on_health_alias_even_with_valid_secret(self):
        valid_service = {
            "AEONITH_SERVICE_TOKEN": "t" * 48,
            "AEONITH_ENABLE_LIVE_REVIEWS": "true",
            "AEONITH_PROVIDER_KIND": "openai-responses",
            "AEONITH_PROVIDER_URL": "https://example.test/v1/responses",
            "AEONITH_PROVIDER_MODEL": "synthetic-test-model",
            "AEONITH_PROVIDER_API_KEY": "nonsecret-test-placeholder",
        }
        headers = [
            ("Authorization", "Bearer " + valid_service["AEONITH_SERVICE_TOKEN"]),
            ("Content-Type", "application/json"),
            ("X-Aeonith-Disclosure", "accepted"),
            ("Content-Length", "12"),
        ]
        for path in ("/healthz", "/api/health", "/api?aeonith_route=health"):
            with self.subTest(path=path):
                with patch.object(ReviewHandler, "do_POST", side_effect=AssertionError("paid handler reached")):
                    code, result, read_count = invoke("POST", path, body=b"private text",
                                                      headers=headers, environ=valid_service)
                self.assertEqual(code, 405)
                self.assertEqual(result["error"]["code"], "method_not_allowed")
                self.assertEqual(read_count, 0)


if __name__ == "__main__":
    unittest.main()
