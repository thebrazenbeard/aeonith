"""Independent contract checks for the Aeonith review engine.

Run from repository root after making the ``aeonith`` package importable:
    python -m unittest discover -s aeonith_worker/evaluation -v

The assertions distinguish deterministic engine guarantees from later,
necessarily model-assisted semantic/literary evaluation. No LLM is required.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from aeonith.core import critique


FIXTURES = Path(__file__).parent / "fixtures"


def cases(filename: str) -> list[dict]:
    return json.loads((FIXTURES / filename).read_text(encoding="utf-8"))["cases"]


class CriticContractTests(unittest.TestCase):
    def assert_unavailable_without_fabrication(self, request: dict) -> dict:
        result = critique(request)
        self.assertIsInstance(result, dict)
        self.assertEqual("aeonith.review.v1", result.get("schema_version"))
        self.assertEqual("provider_unavailable", result.get("status"))
        self.assertIsNone(result.get("assessment"))
        self.assertEqual([], result.get("challenges"))
        self.assertFalse(result.get("lens_reviews"), "No provider may invent lens critiques")
        self.assertFalse(result.get("synthesis"), "No provider may invent a synthesis")
        self.assertIsInstance(result.get("evidence_audit"), list)
        self.assertIsInstance(result.get("provenance"), dict)
        return result

    def test_every_literary_fixture_fails_closed_without_provider(self) -> None:
        for fixture in cases("literary_cases.json"):
            with self.subTest(fixture=fixture["id"]):
                self.assert_unavailable_without_fabrication(fixture["request"])

    def test_every_proposition_fixture_fails_closed_without_provider(self) -> None:
        for fixture in cases("adversarial_cases.json"):
            with self.subTest(fixture=fixture["id"]):
                self.assert_unavailable_without_fabrication(fixture["request"])

    def test_untrusted_text_does_not_create_provider_capability(self) -> None:
        fixture = next(c for c in cases("literary_cases.json") if c["id"] == "injected_instruction_inside_work")
        result = self.assert_unavailable_without_fabrication(fixture["request"])
        self.assertNotIn("100/100", json.dumps(result))

    def test_invalid_version_rejected_before_provider(self) -> None:
        result = critique({"schema_version": "aeonith.review.v0", "work": {"text": "A valid fragment."}})
        self.assertEqual("invalid_request", result.get("status"))
        self.assertIsNone(result.get("assessment"))

    def test_empty_request_is_invalid_not_imagined_critique(self) -> None:
        for invalid in ({}, {"schema_version": "aeonith.review.v1"},
                        {"schema_version": "aeonith.review.v1", "work": {"text": "   "}}):
            with self.subTest(invalid=invalid):
                result = critique(invalid)
                self.assertEqual("invalid_request", result.get("status"))
                self.assertIsNone(result.get("assessment"))

    def test_audit_is_deterministic_without_provider(self) -> None:
        request = cases("adversarial_cases.json")[0]["request"]
        first, second = critique(request), critique(request)
        self.assertEqual(first.get("evidence_audit"), second.get("evidence_audit"))


class FixtureIntegrityTests(unittest.TestCase):
    def test_exactly_fourteen_distinct_named_lenses(self) -> None:
        manifest = json.loads((FIXTURES / "literary_cases.json").read_text(encoding="utf-8"))
        lenses = manifest["required_lenses"]
        self.assertEqual(14, len(lenses))
        self.assertEqual(14, len(set(lenses)))
        self.assertIn("Stylistic (including Alliteration)", lenses)

    def test_all_cases_are_named_and_contain_actual_material(self) -> None:
        for filename in ("literary_cases.json", "adversarial_cases.json"):
            seen = set()
            for fixture in cases(filename):
                with self.subTest(file=filename, fixture=fixture.get("id")):
                    identifier = fixture["id"]
                    self.assertNotIn(identifier, seen)
                    seen.add(identifier)
                    request = fixture["request"]
                    material = request.get("proposition", "") or request.get("work", {}).get("text", "")
                    self.assertTrue(material.strip())
                    self.assertTrue(fixture["manual_oracle"].strip())


if __name__ == "__main__":
    unittest.main()
