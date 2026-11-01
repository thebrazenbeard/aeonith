"""A local-only chat transport must never send manuscript text to the Internet."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from aeonith.providers import LocalOpenAICompatibleProvider


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": '{"lens_reviews": []}'}}]}).encode()


class _CaptureOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _FakeResponse()


class ZeroCostLocalProviderTests(unittest.TestCase):
    def test_defaults_use_uncredentialed_loopback(self):
        provider = LocalOpenAICompatibleProvider()
        self.assertEqual(provider.url, "http://127.0.0.1:5001/v1/chat/completions")
        self.assertEqual(provider.model, "local")
        self.assertIsNone(provider.api_key)

    def test_remote_and_ambiguous_destinations_rejected_before_transport(self):
        endpoints = (
            "https://api.openai.com/v1/chat/completions",
            "https://127.0.0.1:5001/v1/chat/completions",
            "http://localhost:5001/v1/chat/completions",  # DNS / hosts indirection
            "http://0.0.0.0:5001/v1/chat/completions",
            "http://127.0.0.2:5001/v1/chat/completions",
            "http://127.0.0.1.evil.test:5001/v1/chat/completions",
            "http://127.0.0.1:5001/v1/chat/completions?redirect=https://evil.test",
            "http://127.0.0.1:5001/v1/chat/completions#remote",
            " http://127.0.0.1:5001/v1/chat/completions",
            "http://127.0.0.1:05001/v1/chat/completions",
            "http://127.0.0.1:5001/v1/chat/completions\r\n",
            "http://user:pass@127.0.0.1:5001/v1/chat/completions",
            "http://127.0.0.1:5001/v1/completions",
            "http://127.0.0.1:99999/v1/chat/completions",
            "http://[fe80::1]:5001/v1/chat/completions",
            "file:///private/data",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                LocalOpenAICompatibleProvider(url=endpoint)

    def test_credentials_are_never_accepted(self):
        for credential in ("secret", "Bearer secret", " "):
            with self.subTest(credential=credential), self.assertRaises(ValueError):
                LocalOpenAICompatibleProvider(api_key=credential)

    def test_ipv6_loopback_supported(self):
        provider = LocalOpenAICompatibleProvider(url="http://[::1]:5001/v1/chat/completions")
        self.assertEqual(provider.url, "http://[::1]:5001/v1/chat/completions")

    def test_review_uses_existing_contract_without_auth_or_tools(self):
        provider = LocalOpenAICompatibleProvider(model="koboldcpp", max_tokens=1024)
        fake = _CaptureOpener()
        task = {"work": {"text": "A red kite drifted."}, "lenses": ["symbolic"]}
        with patch("aeonith.providers.build_opener", return_value=fake):
            candidate = provider.review({"instructions": "Return validated JSON", "task": task})
        self.assertEqual(candidate, {"lens_reviews": []})
        request, timeout = fake.requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:5001/v1/chat/completions")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(timeout, 45)
        sent = json.loads(request.data)
        self.assertEqual(sent["model"], "koboldcpp")
        self.assertEqual(sent["max_tokens"], 1024)
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertEqual(sent["messages"][0]["role"], "system")
        self.assertEqual(json.loads(sent["messages"][1]["content"]), task)
        self.assertNotIn("tools", sent)


if __name__ == "__main__":
    unittest.main()
