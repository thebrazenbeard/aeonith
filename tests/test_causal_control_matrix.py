"""Synthetic-only accounting tests; these are not generated model evidence."""

from __future__ import annotations

from copy import deepcopy
import unittest

from evaluation.causal_control_matrix import ControlMatrixError, inspect_control_matrix


def fixture() -> dict:
    arms = {
        "frozen_base": {"artifact_id": "frozen", "sha256": "a" * 64},
        "trained_adapter": {"artifact_id": "trained", "sha256": "b" * 64},
        "shuffled_feedback_adapter": {"artifact_id": "shuffled", "sha256": "c" * 64},
    }
    runs = []
    for source in ("h1", "h2"):
        for seed in (11, 29):
            for arm, score in (("frozen_base", 0.2), ("trained_adapter", 0.8),
                               ("shuffled_feedback_adapter", 0.3)):
                runs.append({"source_id": source, "seed": seed, "arm": arm,
                             "request_sha256": ("d" if source == "h1" else "e") * 64,
                             "status": "observed", "outcome": score})
    return {
        "schema_version": "aeonith.causal_control_matrix.v1",
        "experiment_id": "synthetic-control-test",
        "outcome_origin": "synthetic",
        "outcome_metric": "bounded_synthetic_score",
        "split_inventory": {
            "train": [{"source_id": "train", "work_sha256": "1" * 64}],
            "validation": [{"source_id": "dev", "work_sha256": "2" * 64}],
            "holdout": [
                {"source_id": "h1", "work_sha256": "3" * 64},
                {"source_id": "h2", "work_sha256": "4" * 64},
            ],
        },
        "arms": arms,
        "seeds": [11, 29],
        "runs": runs,
    }


class CausalMatrixTests(unittest.TestCase):
    def test_complete_multiseed_heldout_grid_is_only_descriptive(self):
        receipt = inspect_control_matrix(fixture())
        self.assertEqual(receipt["status"], "complete_declared_descriptive_not_causal")
        self.assertEqual(receipt["attempted_cells"], 12)
        self.assertEqual(receipt["complete_paired_work_seed_cells"], 4)
        self.assertAlmostEqual(receipt["trained_minus_control_mean"]["frozen_base"], 0.6)
        self.assertAlmostEqual(receipt["trained_minus_control_mean"]["shuffled_feedback_adapter"], 0.5)
        self.assertFalse(receipt["causal_effect_qualified"])
        self.assertFalse(receipt["human_literary_quality_qualified"])
        self.assertFalse(receipt["model_execution_verified"])

    def test_unavailable_run_is_in_denominator_not_scored_as_zero(self):
        bundle = fixture()
        bundle["runs"][0]["status"] = "unavailable"
        bundle["runs"][0]["outcome"] = None
        receipt = inspect_control_matrix(bundle)
        self.assertEqual(receipt["attempted_cells"], 12)
        self.assertEqual(receipt["unavailable_cells"], 1)
        self.assertEqual(receipt["complete_paired_work_seed_cells"], 3)
        self.assertEqual(receipt["status"], "incomplete_declared_descriptive_not_causal")

    def test_missing_or_duplicate_cells_are_rejected(self):
        b = fixture()
        b["runs"].pop()
        with self.assertRaises(ControlMatrixError):
            inspect_control_matrix(b)
        b = fixture()
        b["runs"][-1] = deepcopy(b["runs"][0])
        with self.assertRaisesRegex(ControlMatrixError, "duplicate"):
            inspect_control_matrix(b)

    def test_same_seed_request_is_required_for_all_arms(self):
        b = fixture()
        b["runs"][1]["request_sha256"] = "f" * 64
        with self.assertRaisesRegex(ControlMatrixError, "identical"):
            inspect_control_matrix(b)

    def test_train_holdout_exact_hash_leakage_is_rejected(self):
        b = fixture()
        b["split_inventory"]["train"][0]["work_sha256"] = "3" * 64
        with self.assertRaisesRegex(ControlMatrixError, "split overlap"):
            inspect_control_matrix(b)

    def test_requires_multiple_seeds_and_holdout_works(self):
        b = fixture()
        b["seeds"] = [11]
        with self.assertRaisesRegex(ControlMatrixError, "seeds"):
            inspect_control_matrix(b)
        b = fixture()
        b["split_inventory"]["holdout"].pop()
        with self.assertRaisesRegex(ControlMatrixError, "two distinct"):
            inspect_control_matrix(b)

    def test_rejects_same_artifact_hash_or_id_for_controls(self):
        for field in ("sha256", "artifact_id"):
            b = fixture()
            b["arms"]["shuffled_feedback_adapter"][field] = b["arms"]["trained_adapter"][field]
            with self.assertRaisesRegex(ControlMatrixError, "identities"):
                inspect_control_matrix(b)

    def test_rejects_bad_outcome_numbers_and_fake_unavailable_score(self):
        for bad in (float("nan"), float("inf"), -0.1, 1.01, True, "0.8"):
            b = fixture()
            b["runs"][0]["outcome"] = bad
            with self.assertRaises(ControlMatrixError):
                inspect_control_matrix(b)
        b = fixture()
        b["runs"][0]["status"] = "unavailable"
        with self.assertRaisesRegex(ControlMatrixError, "invented"):
            inspect_control_matrix(b)

    def test_optional_disabled_head_requires_a_real_declared_arm_grid(self):
        b = fixture()
        b["arms"]["disabled_head_adapter"] = {"artifact_id": "disabled", "sha256": "f" * 64}
        for source in ("h1", "h2"):
            for seed in (11, 29):
                b["runs"].append({"source_id": source, "seed": seed,
                                  "arm": "disabled_head_adapter",
                                  "request_sha256": ("d" if source == "h1" else "e") * 64,
                                  "status": "observed", "outcome": 0.4})
        receipt = inspect_control_matrix(b)
        self.assertEqual(receipt["attempted_cells"], 16)
        self.assertAlmostEqual(receipt["trained_minus_control_mean"]["disabled_head_adapter"], 0.4)

    def test_never_calls_models_or_reads_user_files(self):
        # The pure inspection API consumes only in-memory records; no IO parameters.
        receipt = inspect_control_matrix(fixture())
        self.assertEqual(receipt["outcome_origin"], "synthetic")
        self.assertEqual(len(receipt["input_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
