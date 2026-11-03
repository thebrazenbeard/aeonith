import copy
import hashlib
import unittest

from aeonith.book_review import (
    BatchReviewError,
    review_checkpoint_plan,
    review_longform_plan,
)
from aeonith.checkpoint import plan_after_checkpoint
from aeonith.longform import plan_longform


class ValidProvider:
    name = "fixture_provider"

    def __init__(self, bad_at=None):
        self.calls = []
        self.bad_at = bad_at

    def review(self, payload):
        text = payload["task"]["work"]["text"]
        self.calls.append(text)
        quote = "fabricated quote" if len(self.calls) == self.bad_at else text[:min(12, len(text))]
        return {
            "lens_reviews": [
                {
                    "lens": lens,
                    "analysis": "The scene remains unresolved.",
                    "basis": "textual",
                    "support": [{"source": "work", "quote": quote}],
                    "limitations": [],
                }
                for lens in payload["task"]["lenses"]
            ],
            "synthesis": "Only the supplied passage was examined.",
            "uncertainties": [],
        }


class BookReviewTests(unittest.TestCase):
    def setUp(self):
        self.source = (
            "# Chapter One\n" + "Mara returned. " * 12
            + "\n\n# Chapter Two\n" + "Nobody remembered her. " * 12
        )
        self.plan = plan_longform(self.source, max_chunk_chars=160)

    def test_numbered_cantos_are_distinct_source_sections(self):
        source = (
            "Canto I\nThe first choice was made.\n"
            "Canto II\nThe consequence followed.\n"
            "Canto 3\nA different witness arrived.\n"
        )
        plan = plan_longform(source, max_chunk_chars=160)
        self.assertEqual(len(plan["sections"]), 3)
        self.assertEqual(len(plan["segments"]), 3)
        self.assertEqual(
            "".join(source[segment["start"]:segment["end"]] for segment in plan["segments"]),
            source,
        )

    def test_no_provider_is_not_a_fake_review(self):
        result = review_longform_plan(self.source, self.plan)
        self.assertEqual(result["status"], "provider_unavailable")
        self.assertEqual(result["attempted_segments"], 0)
        self.assertEqual(result["completed_chars"], 0)
        self.assertEqual(result["reviews"], [])
        self.assertIsNone(result["whole_book_synthesis"])
        index = result["cross_segment_evidence_index"]
        self.assertEqual(index["status"], "not_attempted")
        self.assertEqual(index["semantic_relationships"], "UNASSESSED")
        self.assertEqual(len(index["sections"]), len(self.plan["sections"]))
        self.assertTrue(all(row["status"] == "not_attempted" for row in index["sections"]))
        self.assertEqual(index["lens_coverage"], [])

    def test_all_segments_reviewed_no_whole_book_claim(self):
        provider = ValidProvider()
        result = review_longform_plan(self.source, self.plan, provider=provider)
        self.assertEqual(result["status"], "segments_completed")
        self.assertEqual(result["completed_segments"], len(self.plan["segments"]))
        self.assertEqual(result["completed_chars"], len(self.source))
        self.assertEqual("".join(provider.calls), self.source)
        self.assertIsNone(result["whole_book_synthesis"])
        self.assertTrue(all(x["status"] == "completed" for x in result["reviews"]))
        index = result["cross_segment_evidence_index"]
        self.assertEqual(index["status"], "fully_indexed_excerpts")
        self.assertEqual(index["semantic_relationships"], "UNASSESSED")
        self.assertEqual([item["section_index"] for item in index["sections"]],
                         list(range(len(self.plan["sections"]))))
        self.assertEqual(sum(item["completed_segments"] for item in index["sections"]),
                         len(self.plan["segments"]))
        self.assertIn("symbolic", [item["lens"] for item in index["lens_coverage"]])
        self.assertEqual(len(index["lens_coverage"]),
                         len(result["reviews"][0]["review"]["lens_reviews"]))
        quote_hashes = [anchor["quote_sha256"] for section in index["sections"]
                        for row in section["evidence_rows"] for anchor in row["work_quotes"]]
        self.assertIn(hashlib.sha256(provider.calls[0][:12].encode("utf-8")).hexdigest(), quote_hashes)
        self.assertNotIn("Mara returned", str(index))

    def test_invalid_plan_fails_before_provider_calls(self):
        provider = ValidProvider()
        wrong = copy.deepcopy(self.plan)
        wrong["segments"][0]["end"] += 1
        with self.assertRaises(BatchReviewError):
            review_longform_plan(self.source, wrong, provider=provider)
        self.assertEqual(provider.calls, [])

    def test_limit_preflight_fails_before_calls(self):
        provider = ValidProvider()
        with self.assertRaises(BatchReviewError):
            review_longform_plan(self.source, self.plan, provider=provider, max_segments=1)
        self.assertEqual(provider.calls, [])
        for value in (0, -1, True, "20", 513):
            with self.subTest(value=value), self.assertRaises(BatchReviewError):
                review_longform_plan(self.source, self.plan, provider=provider, max_segments=value)

    def test_explicit_one_lens_applies_to_every_segment(self):
        provider = ValidProvider()
        result = review_longform_plan(
            self.source, self.plan, provider=provider, lenses=["symbolic"]
        )
        self.assertEqual(result["status"], "segments_completed")
        self.assertTrue(result["reviews"])
        for entry in result["reviews"]:
            self.assertEqual([item["lens"] for item in entry["review"]["lens_reviews"]], ["symbolic"])

    def test_invalid_lenses_preflight_never_calls_provider(self):
        for value in ([], ["invalid"], ["symbolic", "symbolic"], "symbolic", [True]):
            with self.subTest(value=value):
                provider = ValidProvider()
                with self.assertRaises(BatchReviewError):
                    review_longform_plan(self.source, self.plan, provider=provider, lenses=value)
                self.assertEqual(provider.calls, [])

    def test_invalid_provider_output_stops_and_measures_partial(self):
        provider = ValidProvider(bad_at=2)
        result = review_longform_plan(self.source, self.plan, provider=provider)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["attempted_segments"], 2)
        self.assertEqual(result["completed_segments"], 1)
        self.assertLess(result["completed_chars"], len(self.source))
        self.assertEqual(result["reviews"][1]["status"], "invalid_provider_output")
        self.assertEqual(len(provider.calls), 2)
        index = result["cross_segment_evidence_index"]
        self.assertEqual(index["status"], "partially_indexed_excerpts")
        self.assertEqual(sum(section["completed_segments"] for section in index["sections"]), 1)
        self.assertEqual(sum(len(section["evidence_rows"]) for section in index["sections"]),
                         len(result["reviews"][0]["review"]["lens_reviews"]))

    def test_first_failed_excerpt_does_not_invent_grounded_cross_section_evidence(self):
        provider = ValidProvider(bad_at=1)
        result = review_longform_plan(self.source, self.plan, provider=provider,
                                      lenses=["symbolic"])
        index = result["cross_segment_evidence_index"]
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(index["status"], "failed_without_completed_excerpt")
        self.assertEqual(index["lens_coverage"], [])
        self.assertEqual(sum(len(row["evidence_rows"]) for row in index["sections"]), 0)
        self.assertIsNone(index["whole_book_interpretation"])

    def test_evidence_index_is_deterministic_and_never_repeats_model_prose(self):
        a = review_longform_plan(self.source, self.plan, provider=ValidProvider(),
                                 lenses=["symbolic"])
        b = review_longform_plan(self.source, self.plan, provider=ValidProvider(),
                                 lenses=["symbolic"])
        self.assertEqual(a["cross_segment_evidence_index"], b["cross_segment_evidence_index"])
        self.assertNotIn("The scene remains unresolved", str(a["cross_segment_evidence_index"]))
        self.assertNotIn("Nobody remembered her", str(a["cross_segment_evidence_index"]))

    def test_checkpoint_runner_never_sends_prefix_or_marker(self):
        source = "SECRET_NAME and old scenes.\\n[ps]" + self.source
        plan = plan_after_checkpoint(source, max_chunk_chars=160)
        provider = ValidProvider()
        result = review_checkpoint_plan(source, plan, provider=provider)
        self.assertEqual(result["status"], "segments_completed")
        self.assertEqual(result["scope"], "after_checkpoint_exclusive")
        self.assertEqual(result["completed_chars"], len(self.source))
        self.assertEqual("".join(provider.calls), self.source)
        self.assertNotIn("SECRET_NAME", str(result))
        self.assertNotIn("[ps]", "".join(provider.calls))
        self.assertNotIn("SECRET_NAME", str(result["cross_segment_evidence_index"]))
        self.assertEqual(result["cross_segment_evidence_index"]["offset_scope"],
                         "eligible_post_checkpoint_source")

    def test_tampered_checkpoint_fails_before_call(self):
        source = "SECRET[ps]" + self.source
        plan = plan_after_checkpoint(source, max_chunk_chars=160)
        plan["eligible_chars"] += 1
        provider = ValidProvider()
        with self.assertRaises(BatchReviewError):
            review_checkpoint_plan(source, plan, provider=provider)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
