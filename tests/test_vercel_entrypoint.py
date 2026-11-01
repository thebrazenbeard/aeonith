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


def invoke(method: str) -> tuple[int, dict]:
    instance = VercelHandler.__new__(VercelHandler)
    instance.rfile = io.BytesIO(b"")
    instance.wfile = io.BytesIO()
    instance.request_version = "HTTP/1.1"
    instance.requestline = f"{method} /api HTTP/1.1"
    instance.command = method
    instance.path = "/api"
    instance.client_address = ("127.0.0.1", 0)
    instance.headers = Message()
    with patch.dict("os.environ", {}, clear=True):
        getattr(instance, f"do_{method}")()
    _, body = instance.wfile.getvalue().split(b"\r\n\r\n", 1)
    status = int(instance.wfile.getvalue().split(b"\r\n", 1)[0].split()[1])
    return status, json.loads(body)


class VercelEntrypointTests(unittest.TestCase):
    def test_explicit_unique_python_entrypoint_configured(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["tool"]["vercel"]["entrypoint"], "api.index:handler")
        self.assertTrue(issubclass(VercelHandler, ReviewHandler))

    def test_public_routes_rewrite_to_single_python_entrypoint(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        rewrites = {rule["source"]: rule["destination"] for rule in config["rewrites"]}
        for source in ("/healthz", "/v1/critique", "/api/health", "/api/review"):
            with self.subTest(source=source):
                self.assertEqual(rewrites[source], "/api")

    def test_get_health_and_post_fail_closed_on_same_entrypoint(self):
        code, result = invoke("GET")
        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["review_configured"])

        code, result = invoke("POST")
        self.assertEqual(code, 503)
        self.assertEqual(result["error"]["code"], "service_unconfigured")


if __name__ == "__main__":
    unittest.main()
