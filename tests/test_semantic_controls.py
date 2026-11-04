"""Original negative controls for advisory semantic-overclaim triage."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from aeonith import semantic_controls as subject


def _request(text: str) -> dict:
    return {"schema_version": "aeonith.review.v1",
            "work": {"title": "Short control", "text": text},
            "lenses": ["symbolic"]}


def _review(analysis: str, synthesis: str = "A provisional reading.") -> dict:
    return {"schema_version": "aeonith.review.v1", "status": "completed",
            "synthesis": synthesis,
            "lens_reviews": [{"lens": "symbolic", "analysis": analysis,
                              "basis": "textual", "support": [],
                              "limitations": []}],
            "challenges": [], "uncertainties": []}


def _codes(report: dict) -> list[str]:
    return [item["code"] for item in report["warnings"]]


class SemanticControlsTests(unittest.TestCase):
    def test_isolated_single_occurrence_flags_asserted_recurring_motif(self):
        request = _request("One red kite fell into the pond.")
        review = _review("The recurring motif of a red kite represents an enduring fear.")
        report = subject.audit_semantic_risks(request, review)
        self.assertEqual(_codes(report), ["possible_unfounded_recurrence"])
        self.assertEqual(report["warnings"][0]["path"], "lens_reviews[0].analysis")
        self.assertEqual(report["semantic_quality"], "UNASSESSED")
        encoded = json.dumps(report)
        self.assertNotIn("red kite", encoded.lower())
        self.assertNotIn("enduring fear", encoded.lower())
        self.assertNotIn("excerpt_sha256", report)

    def test_external_chapter_claim_flags_unseen_story_context(self):
        request = _request("The stairwell was empty.")
        review = _review("In an earlier chapter, the narrator's sister had explained why.")
        self.assertEqual(_codes(subject.audit_semantic_risks(request, review)),
                         ["possible_unseen_story_context"])

    def test_multiple_risk_codes_are_independent_and_paths_are_sanitized(self):
        request = _request("A bell rang once.")
        review = _review("The recurring motif becomes clear throughout the novel.",
                         synthesis="This pattern repeats across the story.")
        report = subject.audit_semantic_risks(request, review)
        self.assertEqual(_codes(report), [
            "possible_unfounded_recurrence", "possible_unfounded_recurrence",
            "possible_unseen_story_context",
        ])
        self.assertEqual(report["counts"]["warning_count"], 3)
        self.assertEqual(set(item["path"] for item in report["warnings"]),
                         {"synthesis", "lens_reviews[0].analysis"})

    def test_explicit_repetition_cues_prevent_false_positive(self):
        cases = (
            "Every evening, the same red kite returned.",
            "Twice the bell rang.",
            "The chorus repeated again.",
            "Day after day, the door closed.",
        )
        for text in cases:
            with self.subTest(text=text):
                report = subject.audit_semantic_risks(
                    _request(text), _review("The recurring motif may bind these occurrences."))
                self.assertNotIn("possible_unfounded_recurrence", _codes(report))
                self.assertTrue(report["counts"]["source_recurrence_cue"])

    def test_negation_or_uncertainty_is_not_reported_as_asserted_fact(self):
        cases = (
            "There is no evidence of a recurring motif in this excerpt.",
            "It would be premature to call this a recurring motif.",
            "This might become a recurring motif, but we do not know.",
            "A pattern repeats only if another instance is shown; it has not been.",
            "No earlier chapter is available to support that reading.",
        )
        for prose in cases:
            with self.subTest(prose=prose):
                self.assertEqual(_codes(subject.audit_semantic_risks(
                    _request("The lantern went out."), _review(prose))), [])

    def test_literal_source_quote_does_not_become_its_own_hallucination(self):
        text = "Mira wrote 'recurring motif' on the noticeboard, then left."
        report = subject.audit_semantic_risks(
            _request(text), _review("The phrase 'recurring motif' is presented literally."))
        self.assertEqual(_codes(report), [])

    def test_source_mentions_prior_chapter_not_fabricated_unseen_context(self):
        text = "In the previous chapter, she lost a scarf. Today it returned."
        report = subject.audit_semantic_risks(
            _request(text), _review("In the previous chapter, the scarf was lost."))
        self.assertNotIn("possible_unseen_story_context", _codes(report))

    def test_bare_book_in_source_does_not_authorize_prior_chapter_claim(self):
        request = _request("The book lay shut. An orange fell once.")
        review = _review("In an earlier chapter, the orange defined the family feud.")
        self.assertIn("possible_unseen_story_context",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_long_context_not_mislabeled_isolated(self):
        text = "The field widened into dusk. " * 15
        self.assertGreater(len(text), subject.SHORT_EXCERPT_CHARACTERS)
        report = subject.audit_semantic_risks(
            _request(text), _review("This recurring motif structures the novel."))
        self.assertFalse(report["counts"]["short_excerpt"])
        self.assertEqual(_codes(report), [])

    def test_named_once_only_image_is_not_excused_by_unrelated_recurrence(self):
        # 'Every night' supports the bell's recurrence, but not the kite's.
        request = _request("Every night the bell rang. A blue kite appeared once.")
        review = _review("The recurring motif of the blue kite dominates the work.")
        report = subject.audit_semantic_risks(request, review)
        self.assertIn("possible_unfounded_recurrence", _codes(report))
        self.assertEqual(report["semantic_quality"], "UNASSESSED")
        self.assertEqual(report["classification"], "HEURISTIC_HUMAN_REVIEW_ONLY")

    def test_named_single_word_image_is_not_excused_by_unrelated_every(self):
        request = _request("At dusk the bell rang once. Every window in the harbor was blue.")
        review = _review("The bell is a recurring motif.")
        report = subject.audit_semantic_risks(request, review)
        self.assertIn("possible_unfounded_recurrence", _codes(report))
        self.assertEqual(report["semantic_quality"], "UNASSESSED")

    def test_named_two_word_image_is_not_excused_by_unrelated_again(self):
        request = _request("She smiled again. A brass bell rang once.")
        review = _review("The brass bell is a recurring motif.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_named_subject_with_anaphoric_repeat_is_not_overflagged(self):
        request = _request("The bell rang once. It rang again every night afterward.")
        review = _review("The bell is a recurring motif.")
        self.assertNotIn("possible_unfounded_recurrence",
                         _codes(subject.audit_semantic_risks(request, review)))

    def test_possessive_anaphoric_chime_is_possible_recurrence(self):
        request = _request("The bell rang once. Its chime returned again at dusk.")
        review = _review("The bell is a recurring motif.")
        self.assertNotIn("possible_unfounded_recurrence",
                         _codes(subject.audit_semantic_risks(request, review)))

    def test_quoted_later_chapter_in_source_does_not_license_model_claim(self):
        request = _request('Mara read: "In a later chapter, this changes."')
        review = _review("As established in a later chapter, Mara is revealed to be a ghost.")
        self.assertIn("possible_unseen_story_context",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_unseen_numbered_chapter_claim_is_flagged(self):
        review = _review("In Chapter 27, Mara's ghost returns to the harbor.")
        self.assertIn("possible_unseen_story_context",
                      _codes(subject.audit_semantic_risks(_request("Mara watched the harbor."), review)))

    def test_different_numbered_chapter_does_not_license_invented_revelation(self):
        request = _request("Chapter 1. Mara stood at the harbor.")
        review = _review("In Chapter 27, Mara is revealed as a ghost.")
        self.assertIn("possible_unseen_story_context",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_numbered_chapter_does_not_license_generic_earlier_claim(self):
        request = _request("Chapter 1. Mara stood at the harbor.")
        review = _review("As established earlier, Mara is a ghost.")
        self.assertIn("possible_unseen_story_context",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_explicitly_denied_chapter_is_not_evidence_for_that_chapter(self):
        request = _request("This novel has no Chapter 27. Mara waited.")
        review = _review("In Chapter 27, Mara is revealed as a ghost.")
        self.assertIn("possible_unseen_story_context",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_same_chapter_affirmed_elsewhere_survives_one_negated_reference(self):
        request = _request("No Chapter 27 exists in that draft. In Chapter 27 of this draft, Mara waits.")
        review = _review("In Chapter 27 of this draft, Mara waits.")
        self.assertNotIn("possible_unseen_story_context",
                         _codes(subject.audit_semantic_risks(request, review)))

    def test_source_explicitly_names_numbered_chapter_without_flag(self):
        request = _request("In Chapter 27, Mara returned to the harbor.")
        review = _review("In Chapter 27, Mara returns to the harbor.")
        self.assertNotIn("possible_unseen_story_context",
                         _codes(subject.audit_semantic_risks(request, review)))

    def test_unrelated_hedge_in_prior_clause_does_not_excuse_motif_claim(self):
        request = _request("At dusk the bell rang once.")
        review = _review("The weather may improve; the bell is a recurring motif throughout the novel.")
        codes = _codes(subject.audit_semantic_risks(request, review))
        self.assertIn("possible_unfounded_recurrence", codes)
        self.assertIn("possible_unseen_story_context", codes)

    def test_unrelated_hedge_before_contrast_does_not_excuse_motif_claim(self):
        request = _request("At dusk the bell rang once.")
        review = _review("The weather might improve, but the bell is a recurring motif.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_later_hedge_after_semicolon_does_not_retroactively_excuse_claim(self):
        request = _request("At dusk the bell rang once.")
        review = _review("The bell is a recurring motif; this may be too confident.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_actual_hedged_motif_claim_is_not_overflagged(self):
        review = _review("The bell might become a recurring motif if another instance appears.")
        self.assertNotIn("possible_unfounded_recurrence",
                         _codes(subject.audit_semantic_risks(_request("One bell rang."), review)))

    def test_plausible_motif_is_a_hedged_claim(self):
        review = _review("It seems plausible that the bell is a recurring motif.")
        self.assertNotIn("possible_unfounded_recurrence",
                         _codes(subject.audit_semantic_risks(_request("The bell rang once."), review)))

    def test_perhaps_motif_is_not_asserted_recurrence(self):
        request = _request("The bell rang once. Every window was blue.")
        review = _review("Perhaps the bell is a recurring motif.")
        self.assertNotIn("possible_unfounded_recurrence",
                         _codes(subject.audit_semantic_risks(request, review)))

    def test_if_motif_in_later_drafts_is_a_conditional_suggestion(self):
        request = _request("The bell rang once. Every window was blue.")
        review = _review("If the bell is a recurring motif in later drafts, strengthen it now.")
        self.assertNotIn("possible_unfounded_recurrence",
                         _codes(subject.audit_semantic_risks(request, review)))

    def test_unrelated_if_clause_does_not_hedge_motif_as_fact(self):
        request = _request("The bell rang once. Every window was blue.")
        review = _review("If it rains, the bell is a recurring motif.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_named_image_appearing_once_then_again_is_not_overflagged(self):
        request = _request("A blue kite appeared once, then again every morning.")
        review = _review("The recurring motif of the blue kite joins these moments.")
        self.assertEqual(_codes(subject.audit_semantic_risks(request, review)), [])

    def test_named_image_appearing_in_two_sentences_is_not_overflagged(self):
        request = _request("A blue kite appeared once. A blue kite returned every morning.")
        review = _review("The recurring motif of the blue kite joins these moments.")
        self.assertEqual(_codes(subject.audit_semantic_risks(request, review)), [])

    def test_source_words_are_not_a_blanket_license_for_an_unquoted_claim(self):
        request = _request("She wrote 'recurring motif' on the board and left.")
        review = _review("The recurring motif governs this entire unseen novel.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_later_hedge_does_not_erase_earlier_strong_claim(self):
        request = _request("One bell rang.")
        review = _review("The recurring motif dominates the work, though we cannot be certain.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_240_character_excerpt_still_receives_advisory_check(self):
        request = _request("One red kite fell. " + "The empty street was silent. " * 8)
        self.assertGreater(len(request["work"]["text"]), 200)
        self.assertLess(len(request["work"]["text"]), subject.SHORT_EXCERPT_CHARACTERS)
        review = _review("The recurring motif of the kite shapes the whole work.")
        self.assertIn("possible_unfounded_recurrence",
                      _codes(subject.audit_semantic_risks(request, review)))

    def test_non_completed_output_has_no_semantic_assessment(self):
        review = {"status": "invalid_provider_output", "synthesis": "A recurring motif."}
        report = subject.audit_semantic_risks(_request("A short note."), review)
        self.assertEqual(_codes(report), [])
        self.assertEqual(report["counts"]["examined_prose_fields"], 0)
        self.assertEqual(report["semantic_quality"], "UNASSESSED")

    def test_rejects_invalid_and_oversized_inputs_without_echo(self):
        for request, review in (
            ({"schema_version": "other", "work": {"text": "x"}}, _review("x")),
            (_request("private" * 3000), _review("x")),
            (_request("x"), {"status": "completed", "lens_reviews": [{}] * 15}),
            (_request("x"), _review("secret" * 3000)),
        ):
            with self.subTest(request=str(request)[:25]):
                with self.assertRaises(ValueError):
                    subject.audit_semantic_risks(request, review)

    def _run_cli(self, data: bytes) -> tuple[int, dict]:
        stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
        stdout = io.StringIO()
        with patch.object(subject.sys, "stdin", stdin), redirect_stdout(stdout):
            code = subject.main()
        return code, json.loads(stdout.getvalue())

    def test_cli_json_round_trip_reports_only_sanitized_metadata(self):
        data = {"request": _request("A blue bird flew."),
                "review": _review("A recurring motif in the whole novel.")}
        code, report = self._run_cli(json.dumps(data).encode("utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["schema_version"], subject.REPORT_SCHEMA)
        self.assertIn("possible_unfounded_recurrence", _codes(report))
        self.assertNotIn("blue bird", json.dumps(report).lower())
        self.assertNotIn("whole novel", json.dumps(report).lower())

    def test_cli_rejects_duplicate_json_fields_and_size_bombs_without_echo(self):
        samples = (
            b'{"request":{},"request":{"secret":"PRIVATE"},"review":{}}',
            b'"PRIVATE"',
            b'{' + b'x' * subject.MAX_INPUT_BYTES + b'}',
            b'{"request":{},"review":{"status":NaN}}',
        )
        for raw in samples:
            with self.subTest(size=len(raw)):
                code, report = self._run_cli(raw)
                self.assertEqual(code, 2)
                self.assertEqual(report["status"], "invalid_input")
                self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
