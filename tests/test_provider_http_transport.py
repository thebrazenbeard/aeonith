"""Black-box provider transport checks for the isolated Aeonith candidate.

These tests never contact a hosted model or use an API key. They exercise a
loopback fake provider and a mocked opener only for the HTTPS header boundary.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from aeonith.core import critique
from aeonith.providers import OpenAICompatibleProvider


WORK = {
    "schema_version": "aeonith.review.v1",
    "work": {"text": "A red kite crossed the rain."},
    "lenses": ["symbolic"],
}


def valid_content():
    return {
        "lens_reviews": [
            {
                "lens": "symbolic",
                "analysis": "The kite may invite symbolic interpretation.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "red kite"}],
                "limitations": [],
            }
        ],
        "synthesis": "One sentence cannot establish a stable symbolic system.",
        "uncertainties": ["The color's significance is unclear."],
    }


class FakeHandler(BaseHTTPRequestHandler):
    status = 200
    body = b"{}"
    seen = []
    location = None
    delay_seconds = 0

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).seen.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": self.rfile.read(length),
        })
        if type(self).delay_seconds:
            time.sleep(type(self).delay_seconds)
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        if type(self).location:
            self.send_header("Location", type(self).location)
        self.end_headers()
        try:
            self.wfile.write(type(self).body)
        except BrokenPipeError:
            pass

    def log_message(self, format, *args):
        return


class ProviderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/v1/chat/completions"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        FakeHandler.status = 200
        FakeHandler.body = json.dumps({
            "choices": [{"message": {"content": json.dumps(valid_content())}}]
        }).encode()
        FakeHandler.seen = []
        FakeHandler.location = None
        FakeHandler.delay_seconds = 0

    def test_real_http_roundtrip_and_request_shape(self):
        result = critique(WORK, OpenAICompatibleProvider(url=self.endpoint, model="mock-1"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(FakeHandler.seen), 1)
        item = FakeHandler.seen[0]
        self.assertEqual(item["path"], "/v1/chat/completions")
        self.assertEqual(
            {k.lower(): v for k, v in item["headers"].items()}["content-type"],
            "application/json",
        )
        self.assertNotIn("Authorization", item["headers"])
        sent = json.loads(item["body"])
        self.assertEqual(sent["model"], "mock-1")
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertEqual(sent["messages"][1]["role"], "user")
        task_work = json.loads(sent["messages"][1]["content"])["work"]
        self.assertEqual(task_work["text"], WORK["work"]["text"])
        self.assertEqual(task_work["title"], "")

    def test_http_500_does_not_leak_body(self):
        FakeHandler.status = 500
        FakeHandler.body = b"private upstream debug token secret"
        result = critique(WORK, OpenAICompatibleProvider(url=self.endpoint, model="mock-1"))
        self.assertEqual(result["status"], "provider_error")
        self.assertNotIn("private", json.dumps(result))

    def test_invalid_json_response_is_sanitized(self):
        FakeHandler.body = b"not json"
        result = critique(WORK, OpenAICompatibleProvider(url=self.endpoint, model="mock-1"))
        self.assertEqual(result["status"], "provider_error")

    def test_no_choices_or_text_content_is_sanitized(self):
        for payload in [{}, {"choices": []}, {"choices": [{"message": {"content": []}}]}]:
            with self.subTest(payload=payload):
                FakeHandler.body = json.dumps(payload).encode()
                result = critique(WORK, OpenAICompatibleProvider(url=self.endpoint, model="mock-1"))
                self.assertEqual(result["status"], "provider_error")

    def test_oversized_response_refused(self):
        FakeHandler.body = b"x" * 4_000_001
        result = critique(WORK, OpenAICompatibleProvider(url=self.endpoint, model="mock-1"))
        self.assertEqual(result["status"], "provider_error")

    def test_redirect_refused(self):
        FakeHandler.status = 302
        FakeHandler.body = b""
        FakeHandler.location = "http://evil.example/receive"
        result = critique(WORK, OpenAICompatibleProvider(url=self.endpoint, model="mock-1"))
        self.assertEqual(result["status"], "provider_error")

    def test_timeout_is_sanitized(self):
        FakeHandler.delay_seconds = 0.2
        result = critique(WORK, OpenAICompatibleProvider(
            url=self.endpoint, model="mock-1", timeout=0.05,
        ))
        self.assertEqual(result["status"], "provider_error")

    def test_localhost_plaintext_credential_blocked(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider(url=self.endpoint, model="mock-1", api_key="sensitive")

    def test_https_bearer_only_in_request_header(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, n):
                return json.dumps({"choices": [{"message": {"content": json.dumps(valid_content())}}]}).encode()

        seen = {}

        class FakeOpener:
            def open(self, req, timeout):
                seen["req"] = req
                seen["timeout"] = timeout
                return FakeResponse()

        with patch("aeonith.providers.build_opener", return_value=FakeOpener()):
            result = critique(WORK, OpenAICompatibleProvider(
                url="https://provider.example/v1/chat/completions",
                model="m", api_key="sensitive", timeout=4,
            ))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(seen["req"].get_header("Authorization"), "Bearer sensitive")
        self.assertEqual(seen["timeout"], 4)

    def test_untrusted_redirect_destination_not_accepted_as_endpoint(self):
        for url in ["http://example.com", "https://user:secret@example.com", "file:///etc/passwd"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                OpenAICompatibleProvider(url=url, model="mock")


if __name__ == "__main__":
    unittest.main()
