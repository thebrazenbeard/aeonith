"""Synthetic-only pairing of human blind summaries to model-run denominators."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evaluation.quality_eval import (
    ANNOTATION_SCHEMA, DIMENSIONS, PAIR_SCHEMA, STUDY_SCHEMA,
    bind_annotation_to_display, digest,
)
from evaluation.paired_model_bench import BenchError, assess_human_study_coverage


def fixture():
    ids = [f"{number:024x}" for number in range(1, 5)]
    receipt = {
        "schema_version": "aeonith.paired_model_bench_receipt.v2",
        "status": "paired_run_validated_not_quality_qualified",
        "experiment_id": "fixture-human-study",
        "run_count": 4, "seed_count": 2,
        "distinct_holdout_work_count": 2,
        "blinded_pair_count": 4,
        "runs": [
            {"run_id": f"{index + 100:024x}", "seed": (11, 29)[index % 2],
             "base_structural_status": "pass", "adapter_structural_status": "pass",
             "pair_id": pair_id, "pair_display_sha256": None}
            for index, pair_id in enumerate(ids)
        ],
    }
    records = []
    for pair_id in ids:
        pair = {"schema_version": PAIR_SCHEMA, "pair_id": pair_id,
                "request": {"work": {"text": "Secret synthetic literary scene"}},
                "A": {}, "B": {}, "directions": "Score before model identity is revealed."}
        receipt["runs"][len(records)]["pair_display_sha256"] = digest(pair)
        annotations = []
        for name in ("human-one", "human-two"):
            rubric = {"schema_version": ANNOTATION_SCHEMA, "pair_id": pair_id,
                      "reviewer_pseudonym": name,
                      "dimensions": {dim: {"A": 2, "B": 1} for dim in DIMENSIONS},
                      "preference": "A", "rationale": "The critique grounds its claims in the visible scene."}
            annotations.append(bind_annotation_to_display(rubric, pair))
        records.append({"pair": pair, "annotations": annotations})
    return receipt, {"schema_version": STUDY_SCHEMA, "records": records}


class PairedHumanCoverageTests(unittest.TestCase):
    def test_full_two_rater_coverage_remains_unverified_and_redacted(self):
        receipt, study = fixture()
        outcome = assess_human_study_coverage(receipt, study)
        self.assertEqual(outcome["coverage_status"], "TWO_RATER_COVERAGE_OPERATOR_DECLARED")
        self.assertEqual(outcome["covered_pair_count"], 4)
        self.assertEqual(outcome["eligible_pair_count"], 4)
        self.assertEqual(outcome["missing_pair_count"], 0)
        self.assertEqual(outcome["semantic_quality"], "UNASSESSED")
        self.assertFalse(outcome["human_identity_independently_verified"])
        self.assertFalse(outcome["model_execution_authenticated"])
        serialized = json.dumps(outcome)
        for secret in ("Secret synthetic literary scene", "human-one", "human-two",
                       "The critique grounds", "rationale"):
            self.assertNotIn(secret, serialized)

    def test_incomplete_and_incomparable_ratings_not_counted_as_coverage(self):
        receipt, study = fixture()
        study["records"][0]["annotations"].pop()
        study["records"][1]["annotations"][1]["annotation"]["preference"] = "incomparable"
        outcome = assess_human_study_coverage(receipt, study)
        self.assertEqual(outcome["coverage_status"], "INCOMPLETE_BLIND_HUMAN_COVERAGE")
        self.assertEqual(outcome["covered_pair_count"], 2)
        self.assertEqual(outcome["pairs_below_two_comparable_raters"], 2)

    def test_unknown_or_swapped_pair_receipt_is_rejected(self):
        receipt, study = fixture()
        bad = deepcopy(study)
        bad["records"][0]["pair"]["pair_id"] = "f" * 24
        with self.assertRaises(ValueError):
            assess_human_study_coverage(receipt, bad)
        bad = deepcopy(study)
        bad["records"][0]["pair"]["directions"] = "A changed display"
        with self.assertRaises(ValueError):
            assess_human_study_coverage(receipt, bad)

    def test_rejects_rebound_forged_display_with_valid_pair_id_and_rubrics(self):
        receipt, study = fixture()
        forged = deepcopy(study)
        record = forged["records"][0]
        record["pair"]["A"]["substitution"] = "Different critique substituted after preparation"
        for bound in record["annotations"]:
            bound["display_sha256"] = digest(record["pair"])
        # Both rubrics are internally bound to the swapped display; the v1
        # coverage implementation erroneously counted this as full coverage.
        with self.assertRaisesRegex(BenchError, "blind display differs"):
            assess_human_study_coverage(receipt, forged)

    def test_legacy_unbound_receipt_requires_regeneration(self):
        receipt, study = fixture()
        receipt["schema_version"] = "aeonith.paired_model_bench_receipt.v1"
        for row in receipt["runs"]:
            row.pop("pair_display_sha256")
        with self.assertRaisesRegex(BenchError, "legacy receipt lacks"):
            assess_human_study_coverage(receipt, study)

    def test_run_receipt_denominator_and_collisions_are_checked(self):
        receipt, study = fixture()
        for mutation in (lambda r: r.update(run_count=3),
                         lambda r: r["runs"][1].update(pair_id=r["runs"][0]["pair_id"]),
                         lambda r: r.update(distinct_holdout_work_count=3)):
            with self.subTest(mutation=mutation):
                bad = deepcopy(receipt)
                mutation(bad)
                with self.assertRaises(BenchError):
                    assess_human_study_coverage(bad, study)

    def test_missing_records_and_structural_failure_stay_in_denominator(self):
        receipt, study = fixture()
        receipt["runs"][0]["pair_id"] = None
        receipt["runs"][0]["pair_display_sha256"] = None
        receipt["runs"][0]["base_structural_status"] = "fail"
        receipt["blinded_pair_count"] = 3
        study["records"].pop(0)
        outcome = assess_human_study_coverage(receipt, study)
        self.assertEqual(outcome["eligible_pair_count"], 3)
        self.assertEqual(outcome["ineligible_run_count"], 1)
        self.assertEqual(outcome["coverage_status"], "TWO_RATER_COVERAGE_OPERATOR_DECLARED")
        study["records"].pop()
        outcome = assess_human_study_coverage(receipt, study)
        self.assertEqual(outcome["missing_pair_count"], 1)
        self.assertEqual(outcome["coverage_status"], "INCOMPLETE_BLIND_HUMAN_COVERAGE")

    def test_cli_emits_no_private_study_material(self):
        receipt, study = fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
            (root / "study.json").write_text(json.dumps(study), encoding="utf-8")
            result = subprocess.run([
                sys.executable, "-m", "evaluation.paired_model_bench", "study-coverage",
                "--receipt", str(root / "receipt.json"), "--study", str(root / "study.json")
            ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
               check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["covered_pair_count"], 4)
            self.assertNotIn("Secret synthetic literary scene", result.stdout + result.stderr)
            self.assertNotIn("human-one", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
