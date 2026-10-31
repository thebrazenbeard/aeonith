"""Provider objects are untrusted even when they run in-process."""

import unittest

from aeonith.core import critique


def candidate(lens="stylistic", quote="sea"):
    return {
        "lens_reviews": [{
            "lens": lens, "analysis": "Short words create an understated cadence.",
            "basis": "textual", "support": [{"source": "work", "quote": quote}],
            "limitations": ["The excerpt is brief."],
        }],
        "synthesis": "One cautious observation about the excerpt.",
        "uncertainties": ["Broader context is unavailable."],
    }


class MutabilityBoundaryTests(unittest.TestCase):
    def test_python_api_rejects_oversized_aggregate_evidence_before_provider(self):
        evidence = [
            {"kind": "USER", "ref": f"ref-{i}-{j}", "excerpt": "x" * 5000}
            for i in range(20) for j in range(30)
        ]
        request = {
            "schema_version": "aeonith.review.v1",
            "work": {"text": "The sea was quiet."},
            "claims": [{"id": f"claim-{i}", "text": "Context note",
                        "evidence": evidence[i * 30:(i + 1) * 30]}
                       for i in range(20)],
            "lenses": ["stylistic"],
        }

        class Provider:
            calls = 0

            def review(self, _payload):
                self.calls += 1
                return candidate()

        provider = Provider()
        result = critique(request, provider)
        self.assertEqual(result["status"], "invalid_request")
        self.assertEqual(provider.calls, 0)

    def test_mutating_provider_work_cannot_fabricate_citation(self):
        original = {"schema_version": "aeonith.review.v1",
                    "work": {"text": "The sea was quiet."}, "lenses": ["stylistic"]}

        class Provider:
            def review(self, payload):
                payload["task"]["work"]["text"] = "Martians invaded."
                return candidate(quote="Martians invaded.")

        result = critique(original, Provider())
        self.assertEqual(result["status"], "invalid_provider_output")
        self.assertEqual(original["work"]["text"], "The sea was quiet.")

    def test_mutating_provider_lenses_cannot_change_caller_or_coverage(self):
        original = {"schema_version": "aeonith.review.v1",
                    "work": {"text": "The sea was quiet."}, "lenses": ["stylistic"]}

        class Provider:
            def review(self, payload):
                payload["task"]["lenses"][:] = ["linguistic"]
                return candidate(lens="linguistic")

        result = critique(original, Provider())
        self.assertEqual(result["status"], "invalid_provider_output")
        self.assertEqual(original["lenses"], ["stylistic"])

    def test_provider_cannot_mutate_completed_result_after_validation(self):
        original = {"schema_version": "aeonith.review.v1",
                    "work": {"text": "The sea was quiet."}, "lenses": ["stylistic"]}

        class Provider:
            def __init__(self):
                self.raw = candidate()

            def review(self, _payload):
                return self.raw

        provider = Provider()
        result = critique(original, provider)
        self.assertEqual(result["status"], "completed")
        provider.raw["lens_reviews"][0]["limitations"].append("Poisoned after the call")
        provider.raw["uncertainties"].append("Poisoned after the call")
        self.assertEqual(result["lens_reviews"][0]["limitations"], ["The excerpt is brief."])
        self.assertEqual(result["uncertainties"], ["Broader context is unavailable."])

    def test_provider_name_property_cannot_raise_or_leak(self):
        original = {"schema_version": "aeonith.review.v1",
                    "work": {"text": "The sea was quiet."}, "lenses": ["stylistic"]}

        class Provider:
            @property
            def name(self):
                raise RuntimeError("credential_secret_must_not_escape")

            def review(self, _payload):
                return candidate()

        result = critique(original, Provider())
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("credential_secret_must_not_escape", str(result))


if __name__ == "__main__":
    unittest.main()
