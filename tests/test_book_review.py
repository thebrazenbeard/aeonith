import copy
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

    def test_no_provider_is_not_a_fake_review(self):
        result = review_longform_plan(self.source, self.plan)
        self.assertEqual(result["status"], "provider_unavailable")
        self.assertEqual(result["attempted_segments"], 0)
        self.assertEqual(result["completed_chars"], 0)
        self.assertEqual(result["reviews"], [])
        self.assertIsNone(result["whole_book_synthesis"])

    def test_all_segments_reviewed_no_whole_book_claim(self):
        provider = ValidProvider()
        result = review_longform_plan(self.source, self.plan, provider=provider)
        self.assertEqual(result["status"], "segments_completed")
        self.assertEqual(result["completed_segments"], len(self.plan["segments"]))
        self.assertEqual(result["completed_chars"], len(self.source))
        self.assertEqual("".join(provider.calls), self.source)
        self.assertIsNone(result["whole_book_synthesis"])
        self.assertTrue(all(x["status"] == "completed" for x in result["reviews"]))

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

    def test_invalid_provider_output_stops_and_measures_partial(self):
        provider = ValidProvider(bad_at=2)
        result = review_longform_plan(self.source, self.plan, provider=provider)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["attempted_segments"], 2)
        self.assertEqual(result["completed_segments"], 1)
        self.assertLess(result["completed_chars"], len(self.source))
        self.assertEqual(result["reviews"][1]["status"], "invalid_provider_output")
        self.assertEqual(len(provider.calls), 2)

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
