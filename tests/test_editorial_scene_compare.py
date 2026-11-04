"""Offline, synthetic-only tests for comparing alternative prose passages."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from aeonith.editorial_scene_compare import (
    DISPLAY_SCHEMA, FINDING_SCHEMA, SUMMARY_SCHEMA,
    SceneComparisonError, prepare_scene_pair, summarize_scene_comparison,
    validate_scene_finding,
)


SCOPE = {"work_id": "fiction", "canto_id": "C001", "scene_id": "S003"}
QUESTIONS = [
    "What observable action changes the situation?",
    "What transition is supported by the on-page events?",
]
ORIGINAL = "The door was shut. Mira knocked. The lock clicked."
REVISION = "The door was shut. Mira knocked twice. Someone slid the bolt back."


def candidate(revision_id: str, text: str, *, scope: dict | None = None) -> dict:
    source = dict(SCOPE if scope is None else scope)
    source.update({"revision_id": revision_id, "provenance": "USER"})
    return {
        "source": source, "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def pair() -> tuple[dict, dict]:
    return prepare_scene_pair(candidate("draft1", ORIGINAL),
                              candidate("draft2", REVISION), scope=SCOPE,
                              questions=QUESTIONS, seed="synthetic-test-seed")


def finding(display: dict, arm: str = "A", *, quote: str = "door was shut") -> dict:
    text = display[arm]["text"]
    start = text.index(quote)
    return {
        "schema_version": FINDING_SCHEMA, "pair_id": display["pair_id"],
        "arm": arm, "source_sha256": display[arm]["sha256"],
        "quote": quote, "start": start, "end": start + len(quote),
        "analysis": "This literal action anchors a possible causal interpretation.",
        "origin_claim": "model",
    }


class ScenePairTests(unittest.TestCase):
    def test_pure_pair_is_blinded_and_source_bound(self) -> None:
        display, key = pair()
        self.assertEqual(display["schema_version"], DISPLAY_SCHEMA)
        self.assertEqual(display["pair_id"], key["pair_id"])
        self.assertEqual({display["A"]["text"], display["B"]["text"]},
                         {ORIGINAL, REVISION})
        self.assertEqual(set(key["assignment"]), {"A", "B"})
        self.assertEqual({x["revision_id"] for x in key["assignment"].values()},
                         {"draft1", "draft2"})
        self.assertEqual(key["source_provenance"], "USER")
        self.assertNotIn("draft1", json.dumps(display))
        self.assertNotIn("draft2", json.dumps(display))
        self.assertNotIn("fiction", json.dumps(display))
        self.assertNotIn("seed", json.dumps(display))

    def test_reversing_arguments_preserves_display_and_assignment(self) -> None:
        a = candidate("draft1", ORIGINAL)
        b = candidate("draft2", REVISION)
        forward = prepare_scene_pair(a, b, scope=SCOPE, questions=QUESTIONS, seed="stable")
        reverse = prepare_scene_pair(b, a, scope=SCOPE, questions=QUESTIONS, seed="stable")
        self.assertEqual(forward, reverse)

    def test_default_seed_is_fresh_and_not_exposed(self) -> None:
        with patch("aeonith.editorial_scene_compare.secrets.token_hex",
                   side_effect=["seed1", "seed2"]):
            first, _ = prepare_scene_pair(candidate("a", ORIGINAL),
                                          candidate("b", REVISION),
                                          scope=SCOPE, questions=QUESTIONS)
            second, _ = prepare_scene_pair(candidate("a", ORIGINAL),
                                           candidate("b", REVISION),
                                           scope=SCOPE, questions=QUESTIONS)
        self.assertNotEqual(first["pair_id"], second["pair_id"])

    def test_reject_identical_passages(self) -> None:
        with self.assertRaisesRegex(SceneComparisonError, "identical passages"):
            prepare_scene_pair(candidate("a", ORIGINAL), candidate("b", ORIGINAL),
                               scope=SCOPE, questions=QUESTIONS)

    def test_reject_same_revision_id(self) -> None:
        with self.assertRaisesRegex(SceneComparisonError, "revision IDs"):
            prepare_scene_pair(candidate("a", ORIGINAL), candidate("a", REVISION),
                               scope=SCOPE, questions=QUESTIONS)

    def test_reject_scope_mismatch_canto_and_scene(self) -> None:
        for key, value in (("canto_id", "C002"), ("scene_id", "S004")):
            with self.subTest(key=key):
                scope = dict(SCOPE, **{key: value})
                with self.assertRaisesRegex(SceneComparisonError, "scope"):
                    prepare_scene_pair(candidate("a", ORIGINAL),
                                       candidate("b", REVISION, scope=scope),
                                       scope=SCOPE, questions=QUESTIONS)

    def test_reject_unverified_or_fabricated_source_metadata(self) -> None:
        forged = candidate("a", ORIGINAL)
        forged["source"]["provenance"] = "FORMAL_VERIFY"
        with self.assertRaises(SceneComparisonError):
            prepare_scene_pair(forged, candidate("b", REVISION),
                               scope=SCOPE, questions=QUESTIONS)
        forged = candidate("a", ORIGINAL)
        forged["source"]["github_committed"] = True
        with self.assertRaises(SceneComparisonError):
            prepare_scene_pair(forged, candidate("b", REVISION),
                               scope=SCOPE, questions=QUESTIONS)

    def test_reject_candidate_hash_mismatch_and_unknown_keys(self) -> None:
        forged = candidate("a", ORIGINAL)
        forged["sha256"] = "0" * 64
        with self.assertRaisesRegex(SceneComparisonError, "fingerprint"):
            prepare_scene_pair(forged, candidate("b", REVISION),
                               scope=SCOPE, questions=QUESTIONS)
        forged = candidate("a", ORIGINAL)
        forged["backend_url"] = "https://example.com"
        with self.assertRaisesRegex(SceneComparisonError, "fields"):
            prepare_scene_pair(forged, candidate("b", REVISION),
                               scope=SCOPE, questions=QUESTIONS)

    def test_reject_invalid_questions_and_surrogates(self) -> None:
        with self.assertRaises(SceneComparisonError):
            prepare_scene_pair(candidate("a", ORIGINAL), candidate("b", REVISION),
                               scope=SCOPE, questions=QUESTIONS * 2)
        invalid = candidate("bad", ORIGINAL)
        invalid["text"] = "unpaired \ud800"
        with self.assertRaises(SceneComparisonError):
            prepare_scene_pair(invalid, candidate("b", REVISION),
                               scope=SCOPE, questions=QUESTIONS)

    def test_reject_oversized_passages(self) -> None:
        with self.assertRaises(SceneComparisonError):
            prepare_scene_pair(candidate("a", "a" * 12_001),
                               candidate("b", REVISION), scope=SCOPE,
                               questions=QUESTIONS)


class FindingTests(unittest.TestCase):
    def test_exact_unicode_codepoint_quote_validation(self) -> None:
        text = "At the gate 🐸 the latch opened."
        display, key = prepare_scene_pair(candidate("a", text),
                                        candidate("b", REVISION), scope=SCOPE,
                                        questions=QUESTIONS, seed="unicode")
        arm = "A" if display["A"]["text"] == text else "B"
        model_finding = finding(display, arm, quote="🐸 the latch")
        validated = validate_scene_finding(display, model_finding,
                                           assignment_key=key)
        self.assertEqual(validated["literal_source_location"], "validated")
        self.assertEqual(validated["semantic_quality"], "UNASSESSED")
        self.assertEqual(validated["evidence_class"], "REVIEW")
        self.assertFalse(validated["human_identity_verified"])
        self.assertEqual(display[arm]["text"][validated["start"]:validated["end"]],
                         "🐸 the latch")

    def test_repeated_quote_requires_explicit_matching_span(self) -> None:
        text = "Wait. Wait. Then wait."
        display, key = prepare_scene_pair(candidate("a", text),
                                        candidate("b", REVISION), scope=SCOPE,
                                        questions=QUESTIONS, seed="repeat")
        arm = "A" if display["A"]["text"] == text else "B"
        f = finding(display, arm, quote="Wait")
        f["start"] = 6
        f["end"] = 10
        self.assertEqual(validate_scene_finding(display, f, assignment_key=key)["start"], 6)
        f["start"] = 5
        f["end"] = 9
        with self.assertRaisesRegex(SceneComparisonError, "exact Unicode span"):
            validate_scene_finding(display, f, assignment_key=key)

    def test_forged_quote_span_and_source_are_rejected(self) -> None:
        display, key = pair()
        for mutator in (
            lambda f: f.update(quote="fabricated line"),
            lambda f: f.update(start=0, end=5),
            lambda f: f.update(source_sha256="0" * 64),
            lambda f: f.update(pair_id="0" * 24),
            lambda f: f.update(start=True),
        ):
            with self.subTest(mutator=mutator):
                item = finding(display)
                mutator(item)
                with self.assertRaises(SceneComparisonError):
                    validate_scene_finding(display, item, assignment_key=key)

    def test_model_cannot_promote_its_own_authority(self) -> None:
        display, key = pair()
        for extra in ("verified", "FORMAL_VERIFY", "human_identity_verified"):
            item = finding(display)
            item[extra] = True
            with self.subTest(extra=extra), self.assertRaises(SceneComparisonError):
                validate_scene_finding(display, item, assignment_key=key)
        item = finding(display)
        item["origin_claim"] = "HUMAN_REVIEW"
        with self.assertRaises(SceneComparisonError):
            validate_scene_finding(display, item, assignment_key=key)

    def test_declared_human_origin_is_not_verified_human_review(self) -> None:
        display, key = pair()
        item = finding(display)
        item["origin_claim"] = "human"
        result = validate_scene_finding(display, item, assignment_key=key)
        self.assertEqual(result["evidence_class"], "REVIEW")
        self.assertFalse(result["human_identity_verified"])

    def test_summary_is_neutral_with_no_prose_or_winner(self) -> None:
        display, key = pair()
        checked = [validate_scene_finding(display, finding(display, "A"),
                                          assignment_key=key)]
        summary = summarize_scene_comparison(display, checked, assignment_key=key)
        self.assertEqual(summary["schema_version"], SUMMARY_SCHEMA)
        self.assertEqual(summary["semantic_quality"], "UNASSESSED")
        self.assertEqual(summary["literary_preference"], "NOT_COMPUTED")
        self.assertEqual(summary["source_provenance"], "USER")
        encoded = json.dumps(summary)
        for private_text in (ORIGINAL, REVISION, "door was shut", "draft1",
                             "draft2", "This literal action anchors"):
            self.assertNotIn(private_text, encoded)

    def test_summary_revalidates_caller_created_claims(self) -> None:
        display, key = pair()
        checked = validate_scene_finding(display, finding(display), assignment_key=key)
        for key, replacement in (("human_identity_verified", True),
                                 ("semantic_quality", "PASS"),
                                 ("source_sha256", "0" * 64)):
            corrupted = deepcopy(checked)
            corrupted[key] = replacement
            with self.subTest(key=key), self.assertRaises(SceneComparisonError):
                summarize_scene_comparison(display, [corrupted], assignment_key=key)

    def test_altered_display_cannot_rebind_to_original_private_key(self) -> None:
        """Catch display substitution even if the attacker fixes its text hash."""
        display, key = pair()
        intact_finding = finding(display)
        altered = deepcopy(display)
        altered["A"]["text"] += " Extra sentence."
        altered["A"]["sha256"] = hashlib.sha256(
            altered["A"]["text"].encode("utf-8")).hexdigest()
        rewritten = finding(altered)
        with self.assertRaisesRegex(SceneComparisonError, "private key"):
            validate_scene_finding(altered, rewritten, assignment_key=key)
        checked = validate_scene_finding(display, intact_finding, assignment_key=key)
        with self.assertRaisesRegex(SceneComparisonError, "private key"):
            summarize_scene_comparison(altered, [checked], assignment_key=key)
        # A different genuine pair cannot be used as a substitute key either.
        _other_display, other_key = prepare_scene_pair(
            candidate("draft1", ORIGINAL), candidate("draft2", REVISION),
            scope=SCOPE, questions=QUESTIONS, seed="different-secret")
        with self.assertRaises(SceneComparisonError):
            validate_scene_finding(display, intact_finding, assignment_key=other_key)

    def test_repeated_finding_cannot_inflate_source_location_counts(self) -> None:
        display, key = pair()
        checked = validate_scene_finding(display, finding(display), assignment_key=key)
        repeated = summarize_scene_comparison(
            display, [deepcopy(checked) for _ in range(64)], assignment_key=key)
        self.assertEqual(sum(repeated["distinct_literal_source_locations"].values()), 1)
        self.assertEqual(repeated["repeated_location_entries"], 63)
        self.assertEqual(repeated["semantic_quality"], "UNASSESSED")
        self.assertIn("caller_supplied_questions_may_bias_comparison",
                      repeated["comparison_warnings"])
        self.assertEqual(repeated["questions_provenance"], "USER")

    def test_length_imbalance_warning_not_quality_verdict(self) -> None:
        long_text = "A door opened. " * 30
        display, key = prepare_scene_pair(candidate("a", "A door opened."),
                                        candidate("b", long_text), scope=SCOPE,
                                        questions=QUESTIONS, seed="skew")
        result = summarize_scene_comparison(display, [], assignment_key=key)
        self.assertIn("length_imbalance", result["comparison_warnings"])
        self.assertEqual(result["semantic_quality"], "UNASSESSED")

    def test_pure_module_does_not_use_implicit_io(self) -> None:
        with patch("builtins.open", side_effect=AssertionError("unexpected file IO")), \
                patch("subprocess.run", side_effect=AssertionError("unexpected subprocess")), \
                patch("socket.socket", side_effect=AssertionError("unexpected network")):
            display, key = pair()
            result = validate_scene_finding(display, finding(display), assignment_key=key)
            self.assertEqual(summarize_scene_comparison(
                display, [result], assignment_key=key)["semantic_quality"],
                             "UNASSESSED")


if __name__ == "__main__":
    unittest.main()
