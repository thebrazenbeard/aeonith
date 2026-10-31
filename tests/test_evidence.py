"""Tests for exact textual location, not interpretive truth."""

import hashlib
import random
import unittest
from unittest.mock import patch

from aeonith.core import critique
from aeonith.evidence import audit_review_spans, locate_quote


class LocationTests(unittest.TestCase):
    def test_unique_unicode_codepoint_span(self):
        located = locate_quote("A🌊B", "🌊B")
        self.assertEqual(located["status"], "located")
        self.assertEqual(located["unit"], "unicode_code_points")
        self.assertEqual(located["match_count"], 1)
        self.assertFalse(located["ambiguous"])
        self.assertEqual(located["spans"], [{"start": 1, "end": 3}])

    def test_overlapping_quote_matches_are_ambiguous(self):
        located = locate_quote("aaaa", "aa")
        self.assertEqual(located["match_count"], 3)
        self.assertEqual(located["spans"], [
            {"start": 0, "end": 2}, {"start": 1, "end": 3}, {"start": 2, "end": 4},
        ])
        self.assertTrue(located["ambiguous"])
        self.assertFalse(located["truncated"])

    def test_bounded_spans_preserve_true_count(self):
        located = locate_quote("a" * 100, "a", max_spans=3)
        self.assertEqual(located["match_count"], 100)
        self.assertEqual(len(located["spans"]), 3)
        self.assertTrue(located["truncated"])
        self.assertTrue(located["ambiguous"])

    def test_no_normalization_or_casefolding(self):
        self.assertEqual(locate_quote("Mara", "mara")["status"], "not_found")

    def test_invalid_and_oversized_inputs_are_rejected(self):
        for text, quote in (("hello", ""), ("hello", 3), ("x" * 200_001, "x"), ("x", "q" * 501)):
            with self.subTest(text_type=type(text).__name__, quote_type=type(quote).__name__):
                with self.assertRaises(ValueError):
                    locate_quote(text, quote)
        with self.assertRaises(ValueError):
            locate_quote("hello", "h", max_spans=0)

    def test_lone_surrogate_location_uses_python_string_positions(self):
        located = locate_quote("a\ud800b", "\ud800")
        self.assertEqual(located["spans"], [{"start": 1, "end": 2}])

    def test_randomized_short_text_matches_independent_slice_oracle(self):
        rng = random.Random(20261031)
        alphabet = "aé🌊b"
        for _ in range(200):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 30)))
            quote = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 5)))
            expected = [
                {"start": i, "end": i + len(quote)}
                for i in range(len(text) - len(quote) + 1)
                if text[i:i + len(quote)] == quote
            ]
            observed = locate_quote(text, quote)
            self.assertEqual(observed["spans"], expected)
            self.assertEqual(observed["match_count"], len(expected))


class AuditTests(unittest.TestCase):
    def test_repeated_quotes_are_scanned_once_and_locations_are_independent(self):
        review = {
            "status": "completed",
            "lens_reviews": [
                {"lens": "stylistic", "support": [{"source": "work", "quote": "sea"}]},
                {"lens": "symbolic", "support": [{"source": "work", "quote": "sea"}]},
            ],
        }
        with patch("aeonith.evidence.locate_quote", wraps=locate_quote) as scan:
            result = audit_review_spans("sea and sea", review)
        self.assertEqual(scan.call_count, 1)
        first, second = [x["location"] for x in result["textual_anchors"]]
        first["spans"][0]["start"] = -1
        self.assertEqual(second["spans"][0]["start"], 0)

    def test_sidecar_keeps_ambiguous_quote_unselected(self):
        work = "Mara saw the sea. The sea saw Mara."
        review = {
            "status": "completed",
            "lens_reviews": [
                {"lens": "symbolic", "support": [{"source": "work", "quote": "sea"}]},
                {"lens": "comparative", "support": [{"source": "provided_evidence", "ref": "book:2"}]},
            ],
        }
        audit = audit_review_spans(work, review)
        self.assertEqual(audit["schema_version"], "aeonith.quote_locations.v1")
        self.assertEqual(audit["source_text_sha256"], hashlib.sha256(work.encode("utf-8")).hexdigest())
        self.assertEqual(audit["textual_anchors"][0]["location"]["match_count"], 2)
        self.assertTrue(audit["textual_anchors"][0]["location"]["ambiguous"])
        self.assertEqual(audit["external_refs"], [{"lens": "comparative", "support_index": 0, "ref": "book:2", "status": "provided_unverified"}])
        self.assertNotIn("work_text", audit)

    def test_rejects_noncompleted_or_unsupported_evidence(self):
        with self.assertRaises(ValueError):
            audit_review_spans("story", {"status": "provider_unavailable", "lens_reviews": []})
        with self.assertRaises(ValueError):
            audit_review_spans("story", {"status": "completed", "lens_reviews": [{"lens": "stylistic", "support": [{"source": "work", "quote": "invented"}]}]})
        with self.assertRaises(ValueError):
            audit_review_spans("story", {"status": "completed", "lens_reviews": [{"lens": "stylistic", "support": [{"source": "web", "url": "unverified"}]}]})
        with self.assertRaises(ValueError):
            audit_review_spans(" ", {"status": "completed", "lens_reviews": [{"lens": "stylistic", "support": []}]})

    def test_works_with_core_completed_result_without_mutating_it(self):
        request = {"schema_version": "aeonith.review.v1", "work": {"text": "The sea waited."}, "lenses": ["symbolic"]}

        class Provider:
            def review(self, payload):
                return {
                    "lens_reviews": [{"lens": "symbolic", "analysis": "The sea is personified.", "basis": "textual", "support": [{"source": "work", "quote": "sea"}], "limitations": []}],
                    "synthesis": "The brief phrase suggests agency without establishing a character.",
                }

        review = critique(request, Provider())
        self.assertEqual(review["status"], "completed")
        before = review["lens_reviews"][0]["support"][0].copy()
        audit = audit_review_spans(request["work"]["text"], review)
        self.assertEqual(audit["textual_anchors"][0]["location"]["spans"], [{"start": 4, "end": 7}])
        self.assertEqual(review["lens_reviews"][0]["support"][0], before)


if __name__ == "__main__":
    unittest.main()
