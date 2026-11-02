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

    def test_known_false_negative_does_not_become_a_semantic_pass(self):
        # 'Every night' supports the bell's recurrence, but not a blue kite.
        # This intentional fixture records a blind spot in source-wide cues.
        request = _request("Every night the bell rang. A blue kite appeared once.")
        review = _review("The recurring motif of the blue kite dominates the work.")
        report = subject.audit_semantic_risks(request, review)
        self.assertEqual(_codes(report), [])  # A missed warning, not a pass.
        self.assertEqual(report["semantic_quality"], "UNASSESSED")
        self.assertEqual(report["classification"], "HEURISTIC_HUMAN_REVIEW_ONLY")

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
