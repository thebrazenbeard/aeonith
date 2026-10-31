"""Offline adversarial checks for the Aeonith literary-evaluation bench."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation.quality_eval import (
    ANNOTATION_SCHEMA,
    AUDIT_SCHEMA,
    CANONICAL_LENSES,
    DIMENSIONS,
    PAIR_SCHEMA,
    audit_review,
    build_blind_pair,
    digest,
    make_manifest,
    validate_annotation,
)


WORK = "At dawn, Mara put the broken compass on the table. 'North,' she said, but the needle pointed home."
ANALYSES = {
    "psychological": "Her use of 'North' invites speculation about longing, though no inner thoughts are given.",
    "literary_thematic": "Orientation and belonging are set in tension, without a declared resolution.",
    "narrative_structure": "A mundane morning setup pivots at the final homeward motion of the needle.",
    "character_development": "Mara's speech is direct, but the fragment cannot establish a changing character arc.",
    "historical_cultural": "The excerpt gives no date or locale, so historical claims would be fabricated.",
    "philosophical": "The apparent contrast between measurable bearing and felt place tests what counts as direction.",
    "genre_specific": "The compression resembles a miniature fable rather than a fully developed quest.",
    "stylistic": "The juxtaposition of a blunt directional noun and domestic destination creates a turn.",
    "sociological": "No institution or social hierarchy is specified; imposing one would overread the scene.",
    "moral_ethical": "There is no clear agent harmed or duty violated in the supplied line.",
    "symbolic": "The damaged instrument can plausibly represent competing senses of orientation.",
    "reader_response": "A reader might hear comfort or entrapment in the unexpected homeward pointing.",
    "linguistic": "The deictic movement from north to home trades a coordinate for a relationship.",
    "comparative": "The work may recall quest motifs, but no particular influence is established.",
}


def request(lenses=None):
    return {
        "schema_version": "aeonith.review.v1",
        "work": {"title": "The Compass", "text": WORK},
        "lenses": list(CANONICAL_LENSES if lenses is None else lenses),
        "claims": [{"id": "c1", "text": "The compass is damaged",
                    "evidence": [{"kind": "USER", "ref": "user:note-1", "excerpt": "Invented note"}]}],
    }


def completed(lenses=None):
    lenses = list(CANONICAL_LENSES if lenses is None else lenses)
    return {
        "schema_version": "aeonith.review.v1",
        "status": "completed",
        "assessment": None,
        "lens_reviews": [{
            "lens": lens,
            "analysis": ANALYSES[lens],
            "basis": "textual",
            "support": [{"source": "work", "quote": "the needle pointed home"}],
            "limitations": [],
        } for lens in lenses],
        "synthesis": "The bent directional metaphor puts physical position in tension with belonging.",
        "challenges": [], "uncertainties": [],
        "provenance": {"provider_name": "DO_NOT_SHOW_TO_REVIEWERS", "token": "DO_NOT_SHOW"},
    }


def valid_annotation(pair):
    return {
        "schema_version": ANNOTATION_SCHEMA, "pair_id": pair["pair_id"],
        "reviewer_pseudonym": "reviewer-01",
        "dimensions": {dim: {"A": 1, "B": 2} for dim in DIMENSIONS},
        "preference": "B",
        "rationale": "B distinguishes metaphor from narrator assertion and explains its interpretive limitations.",
    }


class AuditTests(unittest.TestCase):
    def test_complete_fourteen_lens_grounded_output_passes_without_truth_claim(self):
        audit = audit_review(request(), completed())
        self.assertEqual(audit["schema_version"], AUDIT_SCHEMA)
        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["semantic_quality"], "UNASSESSED")
        self.assertEqual(audit["metrics"]["anchored_lenses"], 14)

    def test_subset_request_does_not_require_all_fourteen(self):
        selected = ["stylistic", "symbolic"]
        self.assertEqual(audit_review(request(selected), completed(selected))["structural_status"], "pass")

    def test_repeated_lens_id_is_a_failing_error(self):
        result = completed()
        result["lens_reviews"][1]["lens"] = "psychological"
        audit = audit_review(request(), result)
        self.assertEqual(audit["structural_status"], "fail")
        self.assertIn("missing_lens", {x["code"] for x in audit["violations"]})
        self.assertIn("duplicate_lens", {x["code"] for x in audit["violations"]})

    def test_missing_lens_fails(self):
        result = completed()
        result["lens_reviews"].pop()
        self.assertEqual(audit_review(request(), result)["structural_status"], "fail")

    def test_fabricated_quote_fails_even_with_valid_lens_count(self):
        result = completed()
        result["lens_reviews"][0]["support"] = [{"source": "work", "quote": "the moon exploded"}]
        audit = audit_review(request(), result)
        self.assertEqual(audit["structural_status"], "fail")
        self.assertIn("unsupported_quote_or_ref", {x["code"] for x in audit["violations"]})

    def test_reference_not_in_caller_evidence_fails(self):
        result = completed()
        result["lens_reviews"][0]["support"] = [{"source": "provided_evidence", "ref": "unknown"}]
        self.assertEqual(audit_review(request(), result)["structural_status"], "fail")

    def test_exact_input_reference_passes_but_is_not_verified(self):
        result = completed()
        result["lens_reviews"][0]["support"] = [{"source": "provided_evidence", "ref": "user:note-1"}]
        audit = audit_review(request(), result)
        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["semantic_quality"], "UNASSESSED")

    def test_extra_fake_verification_metadata_is_not_laundered(self):
        result = completed()
        result["lens_reviews"][0]["support"][0]["verified"] = True
        self.assertEqual(audit_review(request(), result)["structural_status"], "fail")

    def test_fourteen_identical_lens_paragraphs_raise_filler_warning(self):
        result = completed()
        for row in result["lens_reviews"]:
            row["analysis"] = "The characters have many emotions and themes that matter to readers."
        audit = audit_review(request(), result)
        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["metrics"]["exact_duplicate_analysis_pairs"], 91)
        self.assertIn("repeated_analysis_heuristic", {x["code"] for x in audit["warnings"]})
        self.assertEqual(audit["semantic_quality"], "UNASSESSED")

    def test_lens_name_swapped_boilerplate_is_flagged(self):
        result = completed()
        for row in result["lens_reviews"]:
            row["analysis"] = f"The {row['lens']} lens asks a specific question about this carefully small work."
        audit = audit_review(request(), result)
        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["metrics"]["exact_duplicate_analysis_pairs"], 0)
        self.assertEqual(audit["metrics"]["lens_template_duplicate_pairs"], 91)
        self.assertIn("repeated_lens_template_heuristic", {x["code"] for x in audit["warnings"]})

    def test_challenge_anchor_is_audited_too(self):
        result = completed()
        result["challenges"] = [{"text": "One could question the orientation metaphor.",
                                 "support": [{"source": "work", "quote": "There were seven moons"}]}]
        audit = audit_review(request(), result)
        self.assertEqual(audit["structural_status"], "fail")
        self.assertIn("unsupported_quote_or_ref", {x["code"] for x in audit["violations"]})

    def test_challenge_text_over_limit_is_rejected(self):
        result = completed()
        result["challenges"] = [{"text": "A" * 2001, "support": []}]
        self.assertEqual(audit_review(request(), result)["structural_status"], "fail")

    def test_insufficient_text_requires_explanation_not_fabrication(self):
        result = completed()
        row = result["lens_reviews"][0]
        row.update(basis="insufficient_text", support=[], limitations=["The excerpt is too short for a reliable inference."])
        self.assertEqual(audit_review(request(), result)["structural_status"], "pass")
        row["limitations"] = []
        self.assertEqual(audit_review(request(), result)["structural_status"], "fail")

    def test_provider_failure_is_not_semantic_failure(self):
        audit = audit_review(request(), {"status": "provider_unavailable"})
        self.assertEqual(audit["structural_status"], "not_evaluable")
        self.assertEqual(audit["semantic_quality"], "UNASSESSED")

    def test_invalid_request_rejected(self):
        with self.assertRaises(ValueError):
            audit_review({"lenses": ["made_up"], "work": WORK}, completed())

    def test_forged_assessment_is_structurally_invalid(self):
        result = completed()
        result["assessment"] = {"verified_by": "imaginary-authority"}
        self.assertEqual(audit_review(request(), result)["structural_status"], "fail")


class BlindAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.req = request()
        self.first = completed()
        self.second = copy.deepcopy(self.first)
        self.second["synthesis"] = "A second critique has a different synthesis."

    def test_seeded_assignment_is_reproducible_and_reversible(self):
        self.first["lens_reviews"][0]["provider_id"] = "DO_NOT_SHOW_TO_REVIEWERS"
        display, key = build_blind_pair(self.req, self.first, self.second, "engine-1", "engine-2", seed="run1")
        again, again_key = build_blind_pair(self.req, self.first, self.second, "engine-1", "engine-2", seed="run1")
        self.assertEqual(display, again)
        self.assertEqual(key, again_key)
        self.assertEqual(display["schema_version"], PAIR_SCHEMA)
        self.assertEqual(set(key["assignment"].values()), {"engine-1", "engine-2"})
        self.assertNotIn("engine-1", json.dumps(display))
        self.assertNotIn("engine-2", json.dumps(display))
        self.assertNotIn("DO_NOT_SHOW", json.dumps(display))

    def test_rejects_nested_identity_metadata_and_unvalidated_critique(self):
        self.first["lens_reviews"][0]["limitations"] = [{"provider_name": "LEAKED_MODEL_ID"}]
        with self.assertRaises(ValueError):
            build_blind_pair(self.req, self.first, self.second, "engine-1", "engine-2")
        self.first = completed()
        self.first["lens_reviews"][0]["support"][0]["provider_id"] = "LEAKED_MODEL_ID"
        with self.assertRaises(ValueError):
            build_blind_pair(self.req, self.first, self.second, "engine-1", "engine-2")

    def test_request_only_shares_work_text_and_title_not_extra_metadata(self):
        self.req["work"]["private_provider_metadata"] = {"model": "DO_NOT_SHOW"}
        display, _ = build_blind_pair(self.req, self.first, self.second, "one", "two")
        self.assertNotIn("DO_NOT_SHOW", json.dumps(display))
        self.assertEqual(display["request"]["work"]["text"], WORK)

    def test_swapped_order_is_supported_over_seeds(self):
        assignments = [
            build_blind_pair(self.req, self.first, self.second,
                             "engine-1", "engine-2", seed=f"seed-{i}")[1]["assignment"]["A"]
            for i in range(20)
        ]
        self.assertEqual(set(assignments), {"engine-1", "engine-2"})

    def test_input_order_does_not_reverse_identity_assignment_for_same_pair(self):
        display_a, key_a = build_blind_pair(self.req, self.first, self.second,
                                             "alpha", "beta", seed="fixed")
        display_b, key_b = build_blind_pair(self.req, self.second, self.first,
                                             "beta", "alpha", seed="fixed")
        self.assertEqual(display_a, display_b)
        self.assertEqual(key_a, key_b)

    def test_complete_human_annotation_accepts_rubric(self):
        display, _ = build_blind_pair(self.req, self.first, self.second, "x", "y")
        self.assertIsNone(validate_annotation(valid_annotation(display), display))

    def test_incomplete_rubric_and_booleans_are_rejected(self):
        display, _ = build_blind_pair(self.req, self.first, self.second, "x", "y")
        note = valid_annotation(display)
        del note["dimensions"]["critical_depth"]
        with self.assertRaises(ValueError):
            validate_annotation(note, display)
        note = valid_annotation(display)
        note["dimensions"]["critical_depth"]["B"] = True
        with self.assertRaises(ValueError):
            validate_annotation(note, display)

    def test_identity_is_never_embedded_in_manifest(self):
        manifest = make_manifest(self.req, self.first, provider_id="local-fixture",
                                 model_id="mock-v1", code_revision="abc123",
                                 prompt_revision="v2", parameters={"temperature": 0})
        self.assertEqual(manifest["input_sha256"], digest(self.req))
        self.assertEqual(manifest["output_sha256"], digest(self.first))
        self.assertEqual(manifest["semantic_quality"], "UNASSESSED")
        self.assertEqual(manifest["provenance_status"], "CALLER_DECLARED_UNVERIFIED")
        self.assertNotIn(WORK, json.dumps(manifest))
        manifest = make_manifest(self.req, self.first, provider_id="local-fixture",
                                 model_id="mock-v1", code_revision="abc123",
                                 prompt_revision="v2", parameters={"max_output_tokens": 4096})
        self.assertEqual(manifest["parameters"]["max_output_tokens"], 4096)
        with self.assertRaises(ValueError):
            make_manifest(self.req, self.first, provider_id="local-fixture",
                          model_id="mock-v1", code_revision="abc123",
                          prompt_revision="v2", parameters={"api_key": "NOT_A_REAL_KEY"})
        with self.assertRaises(ValueError):
            make_manifest(self.req, self.first, provider_id="local-fixture",
                          model_id="mock-v1", code_revision="abc123",
                          prompt_revision="v2",
                          parameters={"authorization_header": "Bearer SYNTHETIC_VALUE"})


class CommandLineTests(unittest.TestCase):
    def test_cli_audit_and_separate_blind_files_are_executable(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            for name, content in (("request.json", request()),
                                  ("first.json", completed()),
                                  ("second.json", completed())):
                (root / name).write_text(json.dumps(content), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "evaluation" / "quality_eval.py"
            cmd = [sys.executable, str(script)]
            result = subprocess.run(cmd + ["audit", "--request", str(root / "request.json"),
                                           "--review", str(root / "first.json")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["structural_status"], "pass")
            blind = cmd + ["blind", "--request", str(root / "request.json"),
                           "--first", str(root / "first.json"),
                           "--second", str(root / "second.json"),
                           "--first-id", "first", "--second-id", "second",
                           "--display-out", str(root / "display.json"),
                           "--key-out", str(root / "private_key.json")]
            result = subprocess.run(blind, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            display = json.loads((root / "display.json").read_text(encoding="utf-8"))
            if os.name == "posix":
                self.assertEqual((root / "private_key.json").stat().st_mode & 0o777, 0o600)
                self.assertEqual((root / "display.json").stat().st_mode & 0o777, 0o600)
            note = valid_annotation(display)
            (root / "annotation.json").write_text(json.dumps(note), encoding="utf-8")
            result = subprocess.run(cmd + ["validate-annotation", "--pair", str(root / "display.json"),
                                           "--annotation", str(root / "annotation.json")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            # An existing pair must not be silently overwritten.
            result = subprocess.run(blind, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)
            manifest = cmd + ["manifest", "--request", str(root / "request.json"),
                              "--review", str(root / "first.json"),
                              "--provider-id", "local-fixture", "--model-id", "mock-v1",
                              "--code-revision", "abc123", "--prompt-revision", "v1",
                              "--out", str(root / "run_manifest.json")]
            result = subprocess.run(manifest, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(written["input_sha256"], digest(request()))
            self.assertNotIn(WORK, json.dumps(written))

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / "bad.json").write_text('{"work":{},"work":{"text":"duplicate"}}', encoding="utf-8")
            (root / "review.json").write_text(json.dumps(completed()), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "evaluation" / "quality_eval.py"
            result = subprocess.run([sys.executable, str(script), "audit",
                                     "--request", str(root / "bad.json"),
                                     "--review", str(root / "review.json")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
