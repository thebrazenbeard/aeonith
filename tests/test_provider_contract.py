"""Negative provider-boundary tests independent of a live model service."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from aeonith.core import CANONICAL_LENSES, critique


FIXTURES = Path(__file__).parent / "fixtures"


def _case(identifier: str) -> dict:
    for filename in ("literary_cases.json", "adversarial_cases.json"):
        manifest = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
        for candidate in manifest["cases"]:
            if candidate["id"] == identifier:
                return candidate["request"]
    raise AssertionError(f"fixture not found: {identifier}")


def _candidate(payload: dict, *, assessment: str | None = None) -> dict:
    work = payload["task"]["work"]["text"]
    quote = work.split()[0]
    return {
        "lens_reviews": [
            {
                "lens": lens,
                "analysis": f"A bounded observation for {lens}, grounded in supplied text.",
                "basis": "textual",
                "support": [{"source": "work", "quote": quote}],
                "limitations": ["This is a short excerpt, so broader claims remain uncertain."],
            }
            for lens in payload["task"]["lenses"]
        ],
        "synthesis": "A bounded synthesis tied to the supplied work; not a verified judgment of a whole novel.",
        "challenges": [{"text": "Could the stated motivation have a different interpretation?", "support": []}],
        "uncertainties": ["Unavailable context limits historical/comparative interpretation."],
        "assessment": assessment,
    }


class ProviderStub:
    name = "fixture-provider"

    def __init__(self, transform=None):
        self.payload = None
        self.transform = transform

    def review(self, payload: dict) -> dict:
        self.payload = payload
        result = _candidate(payload)
        return self.transform(result, payload) if self.transform else result


class ExplodingProvider:
    def review(self, payload: dict) -> dict:
        raise RuntimeError("SECRET_API_TOKEN_SHOULD_NOT_LEAK")


class ProviderContractTests(unittest.TestCase):
    def test_every_required_lens_preserved_distinctly(self) -> None:
        provider = ProviderStub()
        result = critique(_case("microfiction_ambiguous_choice"), provider)
        self.assertEqual("completed", result["status"], result.get("error"))
        lens_ids = [item["lens"] for item in result["lens_reviews"]]
        self.assertEqual(14, len(lens_ids))
        self.assertEqual(set(CANONICAL_LENSES), set(lens_ids))
        self.assertEqual(14, len(set(lens_ids)))
        self.assertNotEqual("stylistic", "linguistic")
        self.assertTrue(result["synthesis"])
        self.assertIsNone(result["assessment"], "Literary success is not a binary pass/fail verdict")

    def test_text_and_context_are_untrusted_task_data(self) -> None:
        request = _case("injected_instruction_inside_work")
        provider = ProviderStub()
        result = critique(request, provider)
        self.assertEqual("completed", result["status"])
        self.assertEqual(request["work"]["text"], provider.payload["task"]["work"]["text"])
        self.assertIn("untrusted data", provider.payload["instructions"])
        self.assertFalse(result["provenance"]["knowledge_files_attached_by_core"])
        self.assertEqual("UNKNOWN", result["provenance"]["provider_external_knowledge"])

    def test_one_missing_lens_rejected(self) -> None:
        provider = ProviderStub(lambda result, _: {**result, "lens_reviews": result["lens_reviews"][:-1]})
        result = critique(_case("microfiction_ambiguous_choice"), provider)
        self.assertEqual("invalid_provider_output", result["status"])
        self.assertFalse(result["lens_reviews"])
        self.assertFalse(result["synthesis"])

    def test_duplicate_lens_rejected(self) -> None:
        def duplicate(result: dict, _: dict) -> dict:
            result["lens_reviews"][13]["lens"] = result["lens_reviews"][12]["lens"]
            return result

        result = critique(_case("microfiction_ambiguous_choice"), ProviderStub(duplicate))
        self.assertEqual("invalid_provider_output", result["status"])

    def test_fabricated_quote_rejected(self) -> None:
        def invent(result: dict, _: dict) -> dict:
            result["lens_reviews"][0]["support"] = [{"source": "work", "quote": "[invented quotation not in source]"}]
            return result

        result = critique(_case("microfiction_ambiguous_choice"), ProviderStub(invent))
        self.assertEqual("invalid_provider_output", result["status"])

    def test_fabricated_reference_rejected(self) -> None:
        def invent(result: dict, _: dict) -> dict:
            result["challenges"][0]["support"] = [{"source": "provided_evidence", "ref": "fake-offsite-study"}]
            return result

        result = critique(_case("universal_safety_claim"), ProviderStub(invent))
        self.assertEqual("invalid_provider_output", result["status"])

    def test_proposition_verdict_does_not_convert_to_formal_verification(self) -> None:
        def verdict(result: dict, _: dict) -> dict:
            result["assessment"] = "SURVIVES"
            return result

        result = critique(_case("model_consensus_laundering"), ProviderStub(verdict))
        self.assertEqual("completed", result["status"], result.get("error"))
        self.assertEqual("SURVIVES", result["assessment"])
        self.assertFalse(result["provenance"].get("input_evidence_verified", True))
        self.assertEqual("provided_unverified", result["evidence_audit"][0]["status"])

    def test_provider_error_does_not_leak_exception_message(self) -> None:
        result = critique(_case("microfiction_ambiguous_choice"), ExplodingProvider())
        self.assertEqual("provider_error", result["status"])
        self.assertNotIn("SECRET_API_TOKEN_SHOULD_NOT_LEAK", json.dumps(result))
        self.assertFalse(result["lens_reviews"])


if __name__ == "__main__":
    unittest.main()
