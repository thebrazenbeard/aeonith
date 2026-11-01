"""Offline transport and CLI contract checks for explicit provider modes."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from aeonith.core import critique
from aeonith.providers import OpenAICompatibleProvider, OpenAIResponsesProvider


class FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, _limit):
        return self.payload


class CaptureOpener:
    def __init__(self, payload: dict | str):
        self.response_bytes = (json.dumps(payload) if isinstance(payload, dict) else payload).encode()
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeHTTPResponse(self.response_bytes)


def request():
    return {"schema_version": "aeonith.review.v1", "work": {"text": "The bell rang twice."}, "lenses": ["linguistic"]}


def candidate():
    return {
        "lens_reviews": [{
            "lens": "linguistic",
            "analysis": "The adverb marks repetition, creating a rhythmic echo.",
            "basis": "textual",
            "support": [{"source": "work", "quote": "twice"}],
            "limitations": [],
        }],
        "synthesis": "The compressed sentence creates rhythm through repetition but reveals little context.",
        "challenges": [],
        "uncertainties": ["Longer context is unavailable."],
        "assessment": None,
    }


def chat_response(content: str | None = None):
    return {"choices": [{"message": {"content": content if content is not None else json.dumps(candidate())}}]}


def responses_response(content: str | None = None):
    return {
        "status": "completed", "error": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content if content is not None else json.dumps(candidate())}]},
        ],
    }


class ExplicitProviderTransportTests(unittest.TestCase):
    def test_legacy_chat_request_is_backward_compatible(self):
        opener = CaptureOpener(chat_response())
        provider = OpenAICompatibleProvider(url="https://example.test/v1/chat/completions", model="legacy")
        with patch("aeonith.providers.build_opener", return_value=opener):
            actual = provider.review({"instructions": "Return JSON", "task": request()})
        self.assertEqual(actual, candidate())
        req, timeout = opener.requests[0]
        body = json.loads(req.data)
        self.assertEqual(body["max_tokens"], 8_192)
        self.assertEqual(body["temperature"], 0.2)
        self.assertNotIn("max_completion_tokens", body)
        self.assertNotIn("response_format", body)
        self.assertEqual(req.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(timeout, 90)

    def test_chat_reasoning_parameter_mode_is_explicit(self):
        opener = CaptureOpener(chat_response())
        provider = OpenAICompatibleProvider(
            url="https://example.test/v1/chat/completions", model="compatible-model",
            token_field="max_completion_tokens", temperature=None, json_mode=True, max_tokens=2_000,
        )
        with patch("aeonith.providers.build_opener", return_value=opener):
            provider.review({"instructions": "Return JSON", "task": request()})
        body = json.loads(opener.requests[0][0].data)
        self.assertEqual(body["max_completion_tokens"], 2_000)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("temperature", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_chat_can_omit_both_sampling_and_token_fields(self):
        opener = CaptureOpener(chat_response())
        provider = OpenAICompatibleProvider(
            url="https://example.test/v1/chat/completions", model="compatible-model",
            token_field="none", temperature=None,
        )
        with patch("aeonith.providers.build_opener", return_value=opener):
            provider.review({"instructions": "Return JSON", "task": request()})
        body = json.loads(opener.requests[0][0].data)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("max_completion_tokens", body)
        self.assertNotIn("temperature", body)

    def test_invalid_chat_modes_fail_before_network(self):
        config = {"url": "https://example.test/v1/chat/completions", "model": "m"}
        for option in [{"token_field": "auto"}, {"temperature": float("nan")}, {"temperature": True}, {"temperature": 3}, {"json_mode": "yes"}, {"max_tokens": True}, {"timeout": True}]:
            with self.subTest(option=option), self.assertRaises(ValueError):
                OpenAICompatibleProvider(**config, **option)

    def test_chat_refusal_truncation_and_malformed_message_fail_closed(self):
        variants = [
            {"choices": [{"message": {"content": json.dumps(candidate()), "refusal": "No"}}]},
            {"choices": [{"finish_reason": "length", "message": {"content": json.dumps(candidate())}}]},
            {"choices": [{"finish_reason": "content_filter", "message": {"content": json.dumps(candidate())}}]},
            {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": json.dumps(candidate())}}]},
            {"choices": [{"finish_reason": "function_call", "message": {"role": "assistant", "content": json.dumps(candidate())}}]},
            {"choices": [{"finish_reason": "stop", "message": {"role": "user", "content": json.dumps(candidate())}}]},
            {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(candidate()), "tool_calls": [{"id": "tool"}]}}]},
            {"choices": [{"message": []}]},
            {"choices": [{}]},
        ]
        provider = OpenAICompatibleProvider(url="https://api.example.test/v1/chat/completions", model="selected")
        for variant in variants:
            with self.subTest(variant=variant):
                opener = CaptureOpener(variant)
                with patch("aeonith.providers.build_opener", return_value=opener):
                    result = critique(request(), provider)
                self.assertEqual(result["status"], "provider_error")
                self.assertIsNone(result["synthesis"])

    def test_responses_request_contains_separate_instructions_and_no_tools(self):
        opener = CaptureOpener(responses_response())
        provider = OpenAIResponsesProvider(url="https://api.example.test/v1/responses", model="selected")
        with patch("aeonith.providers.build_opener", return_value=opener):
            actual = provider.review({"instructions": "Return JSON", "task": request()})
        self.assertEqual(actual, candidate())
        body = json.loads(opener.requests[0][0].data)
        self.assertEqual(body["model"], "selected")
        self.assertEqual(body["instructions"], "Return JSON")
        self.assertEqual(body["max_output_tokens"], 8_192)
        self.assertIs(body["store"], False)
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertNotIn("tools", body)
        self.assertEqual(json.loads(body["input"][0]["content"][0]["text"]), request())

    def test_responses_mixed_tool_call_and_text_is_rejected(self):
        invalid = responses_response()
        invalid["output"].insert(1, {"type": "function_call", "name": "ungranted-tool",
                                      "arguments": "{}"})
        opener = CaptureOpener(invalid)
        provider = OpenAIResponsesProvider(url="https://api.example.test/v1/responses", model="selected")
        with patch("aeonith.providers.build_opener", return_value=opener):
            result = critique(request(), provider)
        self.assertEqual(result["status"], "provider_error")
        self.assertIsNone(result["synthesis"])

    def test_responses_core_round_trip_is_literary_contract_valid(self):
        opener = CaptureOpener(responses_response())
        provider = OpenAIResponsesProvider(url="https://api.example.test/v1/responses", model="selected")
        with patch("aeonith.providers.build_opener", return_value=opener):
            actual = critique(request(), provider)
        self.assertEqual(actual["status"], "completed", actual.get("error"))
        self.assertEqual(actual["lens_reviews"][0]["lens"], "linguistic")
        self.assertEqual(actual["provenance"]["provider_name"], "openai_responses")

    def test_responses_refusal_and_incomplete_fail_closed(self):
        variants = [
            {"status": "incomplete", "output": [], "incomplete_details": {"reason": "max_output_tokens"}},
            {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "No"}]}]},
            {"status": "completed", "output": []},
            {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "not json"}]}]},
        ]
        provider = OpenAIResponsesProvider(url="https://api.example.test/v1/responses", model="selected")
        for variant in variants:
            with self.subTest(status=variant.get("status"), value=variant):
                opener = CaptureOpener(variant)
                with patch("aeonith.providers.build_opener", return_value=opener):
                    result = critique(request(), provider)
                self.assertEqual(result["status"], "provider_error")
                self.assertIsNone(result["synthesis"])

    def test_nonfinite_json_is_rejected_at_transport_boundary(self):
        provider = OpenAIResponsesProvider(url="https://api.example.test/v1/responses", model="selected")
        for content in ['{"x":NaN}', '{"x":1e309}']:
            opener = CaptureOpener(responses_response(content))
            with patch("aeonith.providers.build_opener", return_value=opener):
                result = critique(request(), provider)
            self.assertEqual(result["status"], "provider_error")

    def test_responses_plain_http_with_credentials_blocked(self):
        with self.assertRaises(ValueError):
            OpenAIResponsesProvider(url="http://localhost:9999/v1/responses", model="m", api_key="secret")

    def test_responses_constructor_does_not_connect(self):
        with patch("aeonith.providers.build_opener", side_effect=AssertionError("unexpected network")):
            OpenAIResponsesProvider(url="https://api.example.test/v1/responses", model="m")

    def test_cli_exposes_only_free_local_mode_without_credentials(self):
        completed = subprocess.run([sys.executable, "-m", "aeonith", "review", "--help"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("local-openai-compatible", completed.stdout)
        self.assertNotIn("openai-responses", completed.stdout)
        self.assertNotIn("--api-key-env", completed.stdout)


if __name__ == "__main__":
    unittest.main()
