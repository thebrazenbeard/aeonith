"""Source-only adversarial tests for synthetic eval split inventory."""

from __future__ import annotations

import copy
import json
import unittest

from evaluation.paired_model_bench import _split_inventory
from evaluation.synthetic_holdout_inventory import (
    SyntheticInventoryError, inspect_synthetic_inventory,
)
from evaluation.quality_eval import digest
from training.synthetic_pilot import _serialized, build_candidate
import hashlib


class SyntheticHoldoutInventoryTests(unittest.TestCase):
    def setUp(self):
        self.candidate = build_candidate()
        self.sha = hashlib.sha256(_serialized(self.candidate)).hexdigest()

    def test_actual_candidate_hash_only_inventory_matches_bench_contract(self):
        report = inspect_synthetic_inventory(self.candidate, expected_candidate_sha256=self.sha)
        self.assertEqual(report["candidate_sha256"], self.sha)
        self.assertEqual(report["split_counts"], {"train": 28, "validation": 7, "holdout": 7})
        self.assertEqual(len(_split_inventory(report["split_inventory"])["holdout"]), 7)
        first = self.candidate["examples"][35]
        self.assertEqual(report["split_inventory"]["holdout"][0], {
            "source_id": first["source_id"], "work_sha256": digest(first["passage"]),
        })
        serialized = json.dumps(report, ensure_ascii=False)
        for row in self.candidate["examples"]:
            self.assertNotIn(row["passage"], serialized)
            self.assertNotIn(row["target"]["synthesis"], serialized)

    def test_nonqualification_remains_explicit(self):
        report = inspect_synthetic_inventory(expected_candidate_sha256=self.sha)
        self.assertTrue(report["synthetic_targets_accessible_in_source"])
        for key in ("holdout_custody_protected", "holdout_blind_qualified",
                    "independent_holdout_novelty_established", "genuine_unseen_outcome_tasks_established",
                    "model_executions_authenticated", "operator_admission_authorized", "causal_learning_qualified"):
            self.assertFalse(report[key], key)
        self.assertEqual(report["actual_optimizer_steps"], 0)

    def test_wrong_or_invalid_candidate_pin_fails_closed(self):
        for pin in ("0" * 64, "A" * 64, "bad", "", None):
            with self.subTest(pin=pin), self.assertRaises(SyntheticInventoryError):
                inspect_synthetic_inventory(expected_candidate_sha256=pin)

    def test_changed_holdout_text_or_target_refuses_even_with_pin(self):
        for field in ("passage", "target"):
            candidate = copy.deepcopy(self.candidate)
            if field == "passage":
                candidate["examples"][-1]["passage"] += " Changed in transit."
            else:
                candidate["examples"][-1]["target"]["uncertainties"][0] += " Changed."
            with self.subTest(field=field), self.assertRaises(SyntheticInventoryError):
                inspect_synthetic_inventory(candidate, expected_candidate_sha256=self.sha)

    def test_cross_split_duplicate_fails(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["examples"][-1]["passage"] = candidate["examples"][0]["passage"]
        with self.assertRaises(SyntheticInventoryError):
            inspect_synthetic_inventory(candidate, expected_candidate_sha256=self.sha)


if __name__ == "__main__":
    unittest.main()
