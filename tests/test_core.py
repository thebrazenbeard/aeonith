import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from aeonith.core import CANONICAL_LENSES, critique
from aeonith.providers import OpenAICompatibleProvider


WORK = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Sample", "text": "The lamp went out. Nobody reached for a match."},
}


class GroundedProvider:
    name = "grounded_test_double"

    def review(self, payload):
        return {
            "lens_reviews": [
                {
                    "lens": lens,
                    "analysis": "The absence of action leaves causation uncertain.",
                    "basis": "textual",
                    "support": [{"source": "work", "quote": "Nobody reached for a match."}],
                    "limitations": [],
                }
                for lens in payload["task"]["lenses"]
            ],
            "synthesis": "The story is suggestive, but too short to establish the characters' motives.",
            "uncertainties": ["The text does not establish why nobody acts."],
        }


class BadProvider:
    def review(self, payload):
        result = GroundedProvider().review(payload)
        result["lens_reviews"][0]["support"][0]["quote"] = "invented quotation"
        return result


class FailingProvider:
    def review(self, payload):
        raise RuntimeError("sensitive provider internals should not leak")


class CoreTests(unittest.TestCase):
    def test_all_fourteen_lenses_have_distinct_grounded_outputs(self):
        result = critique(WORK, GroundedProvider())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(tuple(x["lens"] for x in result["lens_reviews"]), CANONICAL_LENSES)
        self.assertIsNone(result["assessment"])
        self.assertEqual(result["provenance"]["review_source"], "injected_provider")

    def test_no_provider_never_fabricates_critique(self):
        result = critique(WORK)
        self.assertEqual(result["status"], "provider_unavailable")
        self.assertIsNone(result["synthesis"])
        self.assertFalse(result["lens_reviews"])
        self.assertFalse(result["challenges"])

    def test_missing_text_is_polite_invalid_input(self):
        result = critique({"schema_version": "aeonith.review.v1", "work": {"text": ""}})
        self.assertEqual(result["status"], "invalid_request")
        self.assertIn("written material", result["error"]["message"])

    def test_unverifiable_input_evidence_not_elevated(self):
        request = {
            **WORK,
            "claims": [
                {"id": "c1", "text": "A stated interpretation", "evidence": [{"kind": "DOC", "ref": "document:1"}]},
                {"id": "c2", "text": "An unsupported claim"},
            ],
        }
        result = critique(request)
        self.assertEqual(result["status"], "provider_unavailable")
        self.assertEqual([x["status"] for x in result["evidence_audit"]], ["provided_unverified", "unsupported"])

    def test_unhashable_json_type_in_evidence_is_controlled(self):
        request = {**WORK, "claims": [{
            "id": "c1", "text": "A claim", "evidence": [{"kind": ["DOC"], "ref": "r1"}]
        }]}
        self.assertEqual(critique(request)["status"], "invalid_request")

    def test_unhashable_provider_assessment_is_controlled(self):
        class MalformedAssessment:
            def review(self, payload):
                result = GroundedProvider().review(payload)
                result["assessment"] = ["FAILS"]
                return result

        result = critique(WORK, MalformedAssessment())
        self.assertEqual(result["status"], "invalid_provider_output")

    def test_provider_cannot_launder_verification_through_valid_quote(self):
        for extra in ({"verified": True}, {"epistemic_support": "FORMAL_VERIFY"}, {"confidence": float("nan")}):
            class LaunderingProvider:
                def review(self, payload):
                    result = GroundedProvider().review(payload)
                    result["lens_reviews"][0]["support"][0].update(extra)
                    return result
            with self.subTest(extra=extra):
                result = critique(WORK, LaunderingProvider())
                self.assertEqual(result["status"], "invalid_provider_output")

    def test_provider_support_and_lists_have_strict_budgets(self):
        class OversizedProvider:
            def __init__(self, key):
                self.key = key

            def review(self, payload):
                result = GroundedProvider().review(payload)
                if self.key == "uncertainties":
                    result["uncertainties"] = ["maybe"] * 10_000
                elif self.key == "limitations":
                    result["lens_reviews"][0]["limitations"] = ["caveat"] * 100
                elif self.key == "support":
                    result["lens_reviews"][0]["support"] *= 100
                return result

        for key in ("uncertainties", "limitations", "support"):
            with self.subTest(key=key):
                self.assertEqual(critique(WORK, OversizedProvider(key))["status"], "invalid_provider_output")

    def test_completed_result_contains_only_normalized_support_fields(self):
        result = critique(WORK, GroundedProvider())
        self.assertEqual(result["status"], "completed")
        for lens in result["lens_reviews"]:
            for support in lens["support"]:
                self.assertEqual(set(support), {"source", "quote"})
        json.dumps(result, allow_nan=False)

    def test_unanchored_provider_quote_rejected(self):
        result = critique(WORK, BadProvider())
        self.assertEqual(result["status"], "invalid_provider_output")
        self.assertFalse(result["lens_reviews"])

    def test_provider_exception_is_fail_closed_and_sanitized(self):
        result = critique(WORK, FailingProvider())
        self.assertEqual(result["status"], "provider_error")
        self.assertNotIn("sensitive", json.dumps(result))

    def test_proposition_verdict_not_forced(self):
        proposition_request = {
            "schema_version": "aeonith.review.v1",
            "proposition": "All stories have precisely one meaning.",
            "lenses": ["philosophical"],
        }
        class PropositionProvider:
            def review(self, payload):
                result = GroundedProvider().review(payload)
                result["lens_reviews"][0]["support"] = [
                    {"source": "work", "quote": "precisely one meaning"}
                ]
                result["assessment"] = "FAILS"
                return result
        result = critique(proposition_request, PropositionProvider())
        self.assertEqual(result["assessment"], "FAILS")

    def test_cli_unavailable_exit_and_json(self):
        process = subprocess.run(
            [sys.executable, "-m", "aeonith", "review", "--input", "-"],
            input=json.dumps(WORK), text=True, capture_output=True, check=False,
        )
        self.assertEqual(process.returncode, 3)
        self.assertEqual(json.loads(process.stdout)["status"], "provider_unavailable")

    def test_http_adapter_prevents_insecure_key_transport(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider(
                url="http://example.com/v1/chat/completions", model="model", api_key="secret"
            )
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider(
                url="http://localhost/v1/chat/completions", model="model", api_key="secret"
            )

    def test_http_adapter_sends_explicit_task_and_parses_json_without_network(self):
        candidate = GroundedProvider().review({"task": {"lenses": ["philosophical"]}})
        transport_response = {"choices": [{"message": {"content": json.dumps(candidate)}}]}
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, size):
                self.requested_read_limit = size
                return json.dumps(transport_response).encode("utf-8")

        class FakeOpener:
            def open(self, request, timeout):
                captured["url"] = request.full_url
                captured["payload"] = json.loads(request.data)
                captured["timeout"] = timeout
                return FakeResponse()

        provider = OpenAICompatibleProvider(
            url="https://models.example/v1/chat/completions", model="mock-model", api_key="fake-for-test"
        )
        with patch("aeonith.providers.build_opener", return_value=FakeOpener()):
            parsed = provider.review({
                "instructions": "Only output JSON.",
                "task": {"lenses": ["philosophical"], "work": {"text": "A line."}},
            })
        self.assertEqual(parsed, candidate)
        self.assertEqual(captured["url"], "https://models.example/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "mock-model")
        self.assertEqual(captured["payload"]["messages"][0]["role"], "system")
        self.assertIn("A line.", captured["payload"]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
