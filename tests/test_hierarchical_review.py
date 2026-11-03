"""Private, opt-in cross-section motif evidence, not a whole-book verdict."""

import copy
import hashlib
import unittest

from aeonith.book_review import review_checkpoint_plan, review_longform_plan
from aeonith.checkpoint import plan_after_checkpoint
from aeonith.hierarchical_review import (
    HierarchicalReviewError,
    derive_cross_section_motif_candidates,
)
from aeonith.longform import plan_longform


class QuoteProvider:
    name = "local_test_double"

    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at

    def review(self, payload):
        self.calls += 1
        work = payload["task"]["work"]["text"]
        quote = "not in source" if self.calls == self.fail_at else "silver bell"
        return {
            "lens_reviews": [{
                "lens": lens, "analysis": "A motif may recur within this excerpt.",
                "basis": "textual", "support": [{"source": "work", "quote": quote}],
                "limitations": [],
            } for lens in payload["task"]["lenses"]],
            "synthesis": "Only the bounded passage can be reviewed.",
            "uncertainties": [],
        }


class HierarchicalReviewTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            "# Chapter One\nA silver bell sounded in the courtyard.\n"
            "# Chapter Two\nShe heard the silver bell again.\n"
            "# Chapter Three\nThe silver bell was silent.\n"
        )
        self.plan = plan_longform(self.source, max_chunk_chars=200)

    def report(self, fail_at=None):
        provider = QuoteProvider(fail_at=fail_at)
        return review_longform_plan(
            self.source, self.plan, provider=provider, lenses=["symbolic"]
        )

    def test_literal_recurrence_gets_exact_hash_pointers_but_no_semantic_claim(self):
        result = derive_cross_section_motif_candidates(
            self.source, self.report(), ["silver bell", "courtyard"]
        )
        self.assertEqual(result["semantic_status"], "UNKNOWN")
        self.assertIsNone(result["whole_book_synthesis"])
        self.assertEqual(result["coverage"]["status"], "report_declared_coverage_unverified")
        self.assertEqual(result["coverage"]["reported_segment_status"], "complete")
        recurring, isolated = result["candidates"]
        self.assertEqual(recurring["status"], "recurring_literal_candidate")
        self.assertEqual(recurring["sections_with_anchors"], [0, 1, 2])
        self.assertEqual(len(recurring["anchors"]), 3)
        for anchor in recurring["anchors"]:
            self.assertEqual(anchor["quote_sha256"], hashlib.sha256(b"silver bell").hexdigest())
            self.assertEqual(len(anchor["segment_source_sha256"]), 64)
            self.assertIn(anchor["segment_id"], [s["segment_id"] for s in self.plan["segments"]])
        self.assertEqual(isolated["status"], "UNKNOWN_insufficient_cross_section_evidence")
        self.assertEqual(isolated["anchors"], [])
        self.assertNotIn("silver bell", str(result))
        self.assertNotIn("A motif may recur", str(result))
        self.assertNotIn("courtyard", str(result))

    def test_partial_coverage_is_explicit_and_never_extrapolated(self):
        result = derive_cross_section_motif_candidates(
            self.source, self.report(fail_at=3), ["silver bell"]
        )
        self.assertEqual(result["coverage"]["status"], "report_declared_coverage_unverified")
        self.assertEqual(result["coverage"]["reported_segment_status"], "partial")
        self.assertEqual(result["coverage"]["completed_segments"], 2)
        self.assertEqual(result["candidates"][0]["status"], "recurring_literal_candidate")
        self.assertIn("Only reviewed excerpts", " ".join(result["limitations"]))

    def test_unreviewed_source_does_not_count_as_work_quote(self):
        unavailable = review_longform_plan(self.source, self.plan)
        result = derive_cross_section_motif_candidates(self.source, unavailable, ["silver bell"])
        self.assertEqual(result["coverage"]["status"], "none")
        self.assertEqual(result["candidates"][0]["status"], "UNKNOWN_insufficient_cross_section_evidence")

    def test_checkpoint_requires_only_eligible_source_and_never_embeds_excluded_text(self):
        complete = "TOP_SECRET_PREFIX[ps]" + self.source
        checkpoint = plan_after_checkpoint(complete, max_chunk_chars=200)
        report = review_checkpoint_plan(
            complete, checkpoint, provider=QuoteProvider(), lenses=["symbolic"]
        )
        result = derive_cross_section_motif_candidates(
            self.source, report, ["silver bell"]
        )
        self.assertEqual(result["scope"], "after_checkpoint_exclusive")
        self.assertNotIn("TOP_SECRET_PREFIX", str(result))
        with self.assertRaises(HierarchicalReviewError):
            derive_cross_section_motif_candidates(complete, report, ["silver bell"])

    def test_supplied_references_without_work_quotes_never_generate_candidate(self):
        report = self.report()
        altered = copy.deepcopy(report)
        for entry in altered["reviews"]:
            for lens in entry["review"]["lens_reviews"]:
                lens["support"] = [{"source": "provided_evidence", "ref": "user-ref-1"}]
        for section in altered["cross_segment_evidence_index"]["sections"]:
            for evidence in section["evidence_rows"]:
                evidence["work_quotes"] = []
                evidence["provided_reference_count"] = 1
        result = derive_cross_section_motif_candidates(
            self.source, altered, ["silver bell"]
        )
        self.assertEqual(result["candidates"][0]["status"], "UNKNOWN_insufficient_cross_section_evidence")

    def test_tampered_source_or_forged_quote_fails_closed(self):
        report = self.report()
        with self.assertRaises(HierarchicalReviewError):
            derive_cross_section_motif_candidates(self.source + "x", report, ["silver bell"])
        tampered = copy.deepcopy(report)
        tampered["reviews"][0]["review"]["lens_reviews"][0]["support"][0]["quote"] = "fabricated phrase"
        with self.assertRaises(HierarchicalReviewError):
            derive_cross_section_motif_candidates(self.source, tampered, ["silver bell"])
        tampered = copy.deepcopy(report)
        tampered["cross_segment_evidence_index"]["sections"][0]["evidence_rows"][0]["work_quotes"][0]["quote_sha256"] = "f" * 64
        with self.assertRaises(HierarchicalReviewError):
            derive_cross_section_motif_candidates(self.source, tampered, ["silver bell"])

    def test_self_consistent_truncated_report_does_not_authenticate_coverage(self):
        forged = copy.deepcopy(self.report())
        excerpt = forged["reviews"][0]
        start = self.source.index("silver bell")
        end = start + len("silver bell")
        excerpt["start"], excerpt["end"] = start, end
        altered_sha = hashlib.sha256(self.source[start:end].encode("utf-8")).hexdigest()
        excerpt["source_sha256"] = altered_sha
        forged["cross_segment_evidence_index"]["sections"][0]["segments"][0]["source_sha256"] = altered_sha
        result = derive_cross_section_motif_candidates(self.source, forged, ["silver bell"])
        self.assertEqual(result["coverage"]["reported_segment_status"], "complete")
        self.assertEqual(result["coverage"]["status"], "report_declared_coverage_unverified")
        self.assertFalse(result["coverage"]["report_partition_authenticated"])
        self.assertEqual(result["candidates"][0]["status"], "recurring_literal_candidate")

    def test_bounded_invalid_or_ambiguous_inputs_rejected(self):
        report = self.report()
        for phrases in ([], ["a"], ["silver bell"] * 2, ["x"] * 17, "silver bell", [1]):
            with self.subTest(phrases=phrases), self.assertRaises(HierarchicalReviewError):
                derive_cross_section_motif_candidates(self.source, report, phrases)
        tampered = copy.deepcopy(report)
        tampered["whole_book_synthesis"] = "A made-up verdict"
        with self.assertRaises(HierarchicalReviewError):
            derive_cross_section_motif_candidates(self.source, tampered, ["silver bell"])


if __name__ == "__main__":
    unittest.main()
