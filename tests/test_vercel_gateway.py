"""Offline contract for explicitly selected Vercel AI Gateway Responses routing.

Vercel documents its OpenAI-compatible Responses path and either an
``AI_GATEWAY_API_KEY`` or a Vercel-provided ``VERCEL_OIDC_TOKEN`` as the
authentication credential.  Aeonith's existing Responses transport needs
no gateway-specific SDK or implicit endpoint rewrite.  Credential selection
belongs at the trusted service configuration seam, never in this transport.

https://vercel.com/docs/ai-gateway/sdks-and-apis/python
https://vercel.com/docs/ai-gateway/authentication-and-byok
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from aeonith.providers import OpenAIResponsesProvider


GATEWAY_RESPONSES_URL = "https://ai-gateway.vercel.sh/v1/responses"
PAYLOAD = {
    "instructions": "Respond with JSON and ground your critique in the passage.",
    "task": {
        "schema_version": "aeonith.review.v1",
        "work": {"text": "The clock argued with the sun."},
        "lenses": ["symbolic"],
    },
}
CANDIDATE = {
    "lens_reviews": [{
        "lens": "symbolic",
        "analysis": "The clock and sun suggest competing measures of time.",
        "basis": "textual",
        "support": [{"source": "work", "quote": "clock"}],
        "limitations": [],
    }],
    "synthesis": "The disagreement makes time a contested symbol.",
    "challenges": [],
    "uncertainties": [],
    "assessment": None,
}


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps({
            "status": "completed", "error": None,
            "output": [{"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": json.dumps(CANDIDATE)},
            ]}],
        }).encode("utf-8")


class _Capture:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _Response()


class VercelGatewayContractTests(unittest.TestCase):
    def test_explicit_gateway_oidc_bearer_uses_existing_responses_schema(self):
        """A trusted caller may explicitly supply an OIDC token as API key."""
        capture = _Capture()
        provider = OpenAIResponsesProvider(
            url=GATEWAY_RESPONSES_URL,
            model="openai/gpt-6-luna",
            api_key="nonsecret-offline-oidc-fixture",
            timeout=19,
            max_tokens=2_048,
            structured_outputs=True,
        )
        with patch("aeonith.providers.build_opener", return_value=capture):
            result = provider.review(PAYLOAD)
        self.assertEqual(result, CANDIDATE)
        self.assertEqual(len(capture.requests), 1)
        request, timeout = capture.requests[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, GATEWAY_RESPONSES_URL)
        self.assertEqual(request.get_header("Authorization"),
                         "Bearer nonsecret-offline-oidc-fixture")
        self.assertEqual(timeout, 19)
        self.assertEqual(body["model"], "openai/gpt-6-luna")
        self.assertEqual(body["max_output_tokens"], 2_048)
        self.assertEqual(body["instructions"], PAYLOAD["instructions"])
        self.assertEqual(json.loads(body["input"][0]["content"][0]["text"]),
                         PAYLOAD["task"])
        self.assertIs(body["store"], False)
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertIs(body["text"]["format"]["strict"], True)
        self.assertNotIn("tools", body)

    def test_ambient_vercel_oidc_never_leaks_to_unrelated_https_endpoint(self):
        """Transport does not guess an endpoint or read ambient credentials."""
        capture = _Capture()
        with patch.dict(os.environ, {"VERCEL_OIDC_TOKEN": "must-not-be-used"}):
            provider = OpenAIResponsesProvider(
                url="https://independent-provider.example/v1/responses",
                model="explicit-model",
            )
            with patch("aeonith.providers.build_opener", return_value=capture):
                provider.review(PAYLOAD)
        request, _timeout = capture.requests[0]
        self.assertEqual(request.full_url,
                         "https://independent-provider.example/v1/responses")
        self.assertIsNone(request.get_header("Authorization"))

    def test_gateway_never_allows_downgraded_http_or_embedded_credentials(self):
        for url in (
            "http://ai-gateway.vercel.sh/v1/responses",
            "https://user:pass@ai-gateway.vercel.sh/v1/responses",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OpenAIResponsesProvider(
                    url=url, model="openai/gpt-6-luna", api_key="fixture",
                )


if __name__ == "__main__":
    unittest.main()
