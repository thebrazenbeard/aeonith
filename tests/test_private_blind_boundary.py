"""Adversarial private-literary-study export tests; offline fixture data only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from evaluation.paired_model_bench import prepare
from evaluation.quality_eval import (
    DIMENSIONS, bind_annotation_to_display, summarize_study,
)
from tests.test_paired_model_bench import payload


@unittest.skipUnless(os.name == "posix", "POSIX handle-pinned privacy boundary")
class PairedBlindBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root / "private-bundle.json"
        self.bundle.write_text(json.dumps(payload()), encoding="utf-8")

    def test_bare_git_destination_is_rejected_before_any_manifest_export(self) -> None:
        bare = self.root / "another-project.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, text=True)
        target = bare / "private-rater-packets"
        with self.assertRaises((OSError, ValueError)):
            prepare(self.bundle, target)
        self.assertFalse(target.exists())

    def test_symlinked_parent_is_rejected_even_when_not_git(self) -> None:
        actual = self.root / "actual"
        actual.mkdir()
        link = self.root / "linked"
        link.symlink_to(actual, target_is_directory=True)
        target = link / "private-rater-packets"
        with self.assertRaises((OSError, ValueError)):
            prepare(self.bundle, target)
        self.assertFalse((actual / target.name).exists())

    def test_windows_acl_is_not_falsely_qualified(self) -> None:
        target = self.root / "windows-output"
        with patch("aeonith.private_output._is_windows", return_value=True):
            with self.assertRaisesRegex(ValueError, "Windows private output ACL"):
                prepare(self.bundle, target)
        self.assertFalse(target.exists())

    def test_generated_packets_are_private_and_quality_unassessed(self) -> None:
        target = self.root / "private-rater-packets"
        receipt = prepare(self.bundle, target)
        self.assertEqual(receipt["semantic_quality"], "UNASSESSED")
        self.assertEqual(receipt["run_count"], 4)
        self.assertEqual(receipt["blinded_pair_count"], 4)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
        for directory in (target / "pairs", target / "keys"):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for file in directory.iterdir():
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((target / "bench_receipt.json").stat().st_mode), 0o600)

    def test_synthetic_blinded_human_bundle_does_not_claim_candidate_victory(self) -> None:
        """Exercise real offline orientation binding, never simulate human merit."""
        target = self.root / "private-rater-packets"
        prepare(self.bundle, target)
        pair_path = next((target / "pairs").glob("*.json"))
        pair = json.loads(pair_path.read_text(encoding="utf-8"))
        def fake_rubric(reviewer: str, preference: str) -> dict:
            return {
                "schema_version": "aeonith.human_annotation.v1",
                "pair_id": pair["pair_id"],
                "reviewer_pseudonym": reviewer,
                "dimensions": {dimension: {"A": 1, "B": 1} for dimension in DIMENSIONS},
                "preference": preference,
                "rationale": "Synthetic test annotation; no actual literary judgment was made.",
            }
        annotated = [
            bind_annotation_to_display(fake_rubric("fixture-rater-1", "A"), pair),
            bind_annotation_to_display(fake_rubric("fixture-rater-2", "B"), pair),
        ]
        study = {"schema_version": "aeonith.human_study_bundle.v1",
                 "records": [{"pair": pair, "annotations": annotated}]}
        summary = summarize_study(study)
        self.assertEqual(summary["semantic_quality"], "UNASSESSED")
        self.assertEqual(summary["total_annotations"], 2)
        self.assertTrue(summary["pair_summaries"][0]["rater_disagreement"])
        self.assertIn("NOT_COMPUTED", summary["model_ranking"])
        self.assertNotIn("Ada stood", json.dumps(summary))
        self.assertNotIn("Synthetic test annotation", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
