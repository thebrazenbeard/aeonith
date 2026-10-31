"""Contract tests for opt-in strict JSON-Schema provider requests.

These use a captured in-memory HTTPS response, never a live model.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from aeonith.core import critique
from aeonith.providers import OpenAICompatibleProvider, OpenAIResponsesProvider


class FakeResponse:
    def __init__(self, value: dict):
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.raw


class Capture:
    def __init__(self, value: dict):
        self.value = value
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((json.loads(request.data), timeout))
        return FakeResponse(self.value)


TASK = {
    "schema_version": "aeonith.review.v1",
    "work": {"text": "The bell rang twice."},
    "lenses": ["linguistic", "symbolic"],
}
PAYLOAD = {"instructions": "Return JSON", "task": TASK}
CANDIDATE = {
    "lens_reviews": [
        {"lens": lens, "analysis": "Specific words repeat.", "basis": "textual",
         "support": [{"source": "work", "quote": "bell"}], "limitations": []}
        for lens in TASK["lenses"]
    ],
    "synthesis": "The bell's repetition gives it patterned emphasis.",
    "challenges": [], "uncertainties": [], "assessment": None,
}


def chat_response(candidate=CANDIDATE):
    return {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(candidate),
    }}]}


def responses_response(candidate=CANDIDATE):
    return {"status": "completed", "error": None,
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(candidate)}]}]}


def assert_strict_schema(test: unittest.TestCase, schema: dict):
    test.assertEqual(schema["type"], "object")
    test.assertEqual(schema["additionalProperties"], False)
    test.assertEqual(set(schema["properties"]), set(schema["required"]))
    test.assertNotIn("anyOf", schema)
    lenses = schema["properties"]["lens_reviews"]
    row = lenses["items"]
    test.assertEqual(row["additionalProperties"], False)
    test.assertEqual(set(row["properties"]), set(row["required"]))
    test.assertEqual(row["properties"]["lens"]["enum"], TASK["lenses"])
    support = row["properties"]["support"]["items"]
    test.assertEqual(len(support["anyOf"]), 2)
    for variant in support["anyOf"]:
        test.assertEqual(variant["type"], "object")
        test.assertEqual(set(variant["properties"]), set(variant["required"]))
        test.assertIs(variant["additionalProperties"], False)


class StructuredTransportTests(unittest.TestCase):
    def test_chat_strict_schema_uses_chat_response_format(self):
        capture = Capture(chat_response())
        provider = OpenAICompatibleProvider(url="https://api.example.test/v1/chat/completions",
                                            model="selected", structured_outputs=True)
        with patch("aeonith.providers.build_opener", return_value=capture):
            result = provider.review(PAYLOAD)
        self.assertEqual(result, CANDIDATE)
        body = capture.requests[0][0]
        response_format = body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["name"], "aeonith_review_candidate")
        self.assertIs(response_format["json_schema"]["strict"], True)
        assert_strict_schema(self, response_format["json_schema"]["schema"])

    def test_responses_strict_schema_uses_text_format(self):
        capture = Capture(responses_response())
        provider = OpenAIResponsesProvider(url="https://api.example.test/v1/responses",
                                           model="selected", structured_outputs=True)
        with patch("aeonith.providers.build_opener", return_value=capture):
            result = provider.review(PAYLOAD)
        self.assertEqual(result, CANDIDATE)
        body = capture.requests[0][0]
        self.assertNotIn("response_format", body)
        self.assertFalse(body["store"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        assert_strict_schema(self, body["text"]["format"]["schema"])

    def test_legacy_default_modes_unchanged(self):
        chat = Capture(chat_response())
        provider = OpenAICompatibleProvider(url="https://api.example.test/chat/completions",
                                            model="selected")
        with patch("aeonith.providers.build_opener", return_value=chat):
            provider.review(PAYLOAD)
        self.assertNotIn("response_format", chat.requests[0][0])
        responses = Capture(responses_response())
        provider = OpenAIResponsesProvider(url="https://api.example.test/responses", model="selected")
        with patch("aeonith.providers.build_opener", return_value=responses):
            provider.review(PAYLOAD)
        self.assertEqual(responses.requests[0][0]["text"]["format"], {"type": "json_object"})

    def test_invalid_structured_flag_is_rejected_at_constructor(self):
        for provider_class in (OpenAICompatibleProvider, OpenAIResponsesProvider):
            with self.subTest(provider=provider_class):
                with self.assertRaises(ValueError):
                    provider_class(url="https://api.example.test", model="selected", structured_outputs="yes")

    def test_bad_lens_payload_fails_before_network(self):
        for lenses in (["made_up"], ["symbolic", "symbolic"], [], "symbolic"):
            with self.subTest(lenses=lenses):
                malformed = {"instructions": "Return JSON", "task": {**TASK, "lenses": lenses}}
                provider = OpenAIResponsesProvider(url="https://api.example.test/responses",
                                                   model="selected", structured_outputs=True)
                with patch("aeonith.providers.build_opener", side_effect=AssertionError("network invoked")):
                    with self.assertRaises(ValueError):
                        provider.review(malformed)

    def test_unsupported_candidate_contract_fails_before_network(self):
        provider = OpenAIResponsesProvider(url="https://api.example.test/responses",
                                           model="selected", structured_outputs=True)
        other = {**PAYLOAD, "output_schema": "aeonith.review.v999"}
        with patch("aeonith.providers.build_opener", side_effect=AssertionError("network invoked")):
            with self.assertRaises(ValueError):
                provider.review(other)

    def test_core_still_checks_fabricated_quote_in_strict_mode(self):
        malicious = json.loads(json.dumps(CANDIDATE))
        malicious["lens_reviews"][0]["support"][0]["quote"] = "invented quotation"
        provider = OpenAIResponsesProvider(url="https://api.example.test/responses",
                                           model="selected", structured_outputs=True)
        with patch("aeonith.providers.build_opener", return_value=Capture(responses_response(malicious))):
            result = critique(TASK, provider)
        self.assertEqual(result["status"], "invalid_provider_output")

    def test_cli_offers_explicit_structured_flag(self):
        run = subprocess.run([sys.executable, "-m", "aeonith", "review", "--help"],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--structured-outputs", run.stdout)


if __name__ == "__main__":
    unittest.main()
