"""Synthetic consent fixtures for a fail-closed private candidate admission CLI."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.admit_candidates import AdmissionError, admit


def example(i: int, split: str) -> dict:
    passage = f"On day {i}, Ada closed the blue gate. She kept the key."
    return {
        "id": f"candidate-{i:03d}", "source_id": f"test-work-{i:03d}",
        "split": split, "genre": "test fixture", "lens": "symbolic",
        "passage": passage,
        "target": {
            "lens_reviews": [{"lens": "symbolic", "analysis": "The gate could mark a transition.",
                "basis": "textual", "support": [{"source": "work", "quote": "blue gate"}],
                "limitations": ["The author's intention is not established."]}],
            "synthesis": "The image supports a tentative reading.",
            "challenges": [{"text": "The gate may simply be a gate.",
                            "support": [{"source": "work", "quote": "blue gate"}]}],
            "uncertainties": ["The key's use is unknown."], "assessment": None,
        },
        "draft_status": "REVIEW_PENDING",
    }


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate_path = self.root / "candidates.json"
        self.approval_path = self.root / "approval.json"
        self.output = self.root / "private-output"
        self.candidates = {
            "schema_version": "aeonith.candidate_corpus.v1",
            "status": "REVIEW_PENDING_NOT_TRAINABLE",
            "examples": [example(1, "train"), example(2, "validation"), example(3, "holdout")],
        }
        self.write_candidate()
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        self.approval = {
            "schema_version": "aeonith.candidate_admission.v1",
            "candidate_sha256": digest,
            "approval_status": "APPROVED_FOR_PRIVATE_LOCAL_TRAINING",
            "permission_to_train": True,
            "rights_holder_decision": self.attestation("Fixture Holder", "approve_local_training", digest),
            "independent_data_steward_decision": self.attestation("Fixture Steward", "approve_local_training", digest),
            "editorial_decision": self.attestation("Fixture Editor", "approve_editorial_targets", digest),
            "records": [
                {"id": obj["id"], "source_id": obj["source_id"],
                 "rights_basis": "self_authored", "permission_to_train": True,
                 "permission_to_publish_adapter": False, "editorial_accepted": True}
                for obj in self.candidates["examples"]
            ],
        }
        self.write_approval()

    @staticmethod
    def attestation(name: str, decision: str, digest: str) -> dict:
        return {"identity": name, "decision": decision,
                "attested_at_utc": "2026-11-02T12:00:00Z", "candidate_sha256": digest}

    def write_candidate(self) -> None:
        self.candidate_path.write_text(json.dumps(self.candidates), encoding="utf-8")

    def write_approval(self) -> None:
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")

    def run_admission(self) -> dict:
        return admit(self.candidate_path, self.approval_path, self.output)

    @unittest.skipUnless(os.name == "posix", "private candidate output requires POSIX custody")
    def test_explicit_private_attestations_export_three_trainer_compatible_splits(self) -> None:
        receipt = self.run_admission()
        self.assertEqual(receipt["status"], "admitted_private_only_not_trained")
        self.assertFalse(receipt["adapter_publication_record_permissions_complete"])
        self.assertFalse(receipt["blind_holdout_qualified"])
        self.assertEqual(receipt["split_counts"], {"train": 1, "validation": 1, "holdout": 1})
        self.assertEqual(receipt["lenses_by_split"], {
            "train": ["symbolic"], "validation": ["symbolic"], "holdout": ["symbolic"]
        })
        self.assertIn("linguistic", receipt["train_lenses_missing"])
        self.assertNotIn("symbolic", receipt["train_lenses_missing"])
        self.assertNotIn("Ada closed the blue gate", json.dumps(receipt))
        for split in ("train", "validation", "holdout"):
            self.assertTrue((self.output / f"{split}.jsonl").exists())
            row = json.loads((self.output / f"{split}.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["source_id"], f"test-work-{['train','validation','holdout'].index(split)+1:03d}")
            self.assertTrue(row["permission_to_train"])
            self.assertIs(row["permission_to_publish_adapter"], False)
            self.assertIn("blue gate", row["prompt"])
            self.assertEqual(json.loads(row["completion"]), self.candidates["examples"][['train','validation','holdout'].index(split)]["target"])
        self.assertTrue((self.output / "admission_receipt.json").is_file())

    def test_pending_or_missing_global_decisions_fail_before_any_output(self) -> None:
        for field in ("rights_holder_decision", "independent_data_steward_decision", "editorial_decision", "permission_to_train"):
            with self.subTest(field=field):
                prior = self.approval[field]
                self.approval[field] = None if field != "permission_to_train" else False
                self.write_approval()
                with self.assertRaises(AdmissionError):
                    self.run_admission()
                self.assertFalse(self.output.exists())
                self.approval[field] = prior

    def test_distinct_attestors_required(self) -> None:
        self.approval["independent_data_steward_decision"]["identity"] = "fixture holder"
        self.write_approval()
        with self.assertRaisesRegex(AdmissionError, "distinct"):
            self.run_admission()
        self.assertFalse(self.output.exists())

    def test_attestor_has_to_approve_exact_hash_and_role(self) -> None:
        self.approval["editorial_decision"]["decision"] = "approve_local_training"
        self.write_approval()
        with self.assertRaisesRegex(AdmissionError, "attestation"):
            self.run_admission()
        self.assertFalse(self.output.exists())

    def test_source_digest_mismatch_rejected(self) -> None:
        self.candidates["examples"][0]["passage"] += " Additional text."
        self.write_candidate()
        with self.assertRaisesRegex(AdmissionError, "SHA-256"):
            self.run_admission()
        self.assertFalse(self.output.exists())

    def test_per_record_editorial_and_training_rights_gate(self) -> None:
        for field in ("editorial_accepted", "permission_to_train"):
            with self.subTest(field=field):
                self.approval["records"][0][field] = False
                self.write_approval()
                with self.assertRaises(AdmissionError):
                    self.run_admission()
                self.assertFalse(self.output.exists())
                self.approval["records"][0][field] = True

    def test_missing_record_or_approval_mismatch_rejected(self) -> None:
        self.approval["records"].pop()
        self.write_approval()
        with self.assertRaisesRegex(AdmissionError, "record"):
            self.run_admission()
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.name == "posix", "private candidate output requires POSIX custody")
    def test_publication_defaults_to_false_in_every_exported_record(self) -> None:
        for item in self.approval["records"]:
            item.pop("permission_to_publish_adapter")
        self.write_approval()
        self.run_admission()
        for split in ("train", "validation", "holdout"):
            line = (self.output / f"{split}.jsonl").read_text(encoding="utf-8")
            self.assertFalse(json.loads(line)["permission_to_publish_adapter"])

    def test_tampered_literal_quote_fails_even_with_matching_digest_attestation(self) -> None:
        self.candidates["examples"][0]["target"]["lens_reviews"][0]["support"][0]["quote"] = "a fabricated quote"
        self.write_candidate()
        new_digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        self.approval["candidate_sha256"] = new_digest
        for role in ("rights_holder_decision", "independent_data_steward_decision", "editorial_decision"):
            self.approval[role]["candidate_sha256"] = new_digest
        self.write_approval()
        with self.assertRaisesRegex(AdmissionError, "structural quote"):
            self.run_admission()
        self.assertFalse(self.output.exists())

    def test_rejects_input_and_output_inside_git_checkout(self) -> None:
        with self.assertRaisesRegex(AdmissionError, "outside the Git checkout"):
            admit(Path(__file__).resolve().parents[1] / "training" / "README.md",
                  self.approval_path, self.output)
        with self.assertRaisesRegex(AdmissionError, "outside the Git checkout"):
            admit(self.candidate_path, self.approval_path,
                  Path(__file__).resolve().parents[1] / "training" / "scratch-export")
        self.assertFalse(self.output.exists())

    def test_rejects_source_and_destination_inside_unrelated_checkout(self) -> None:
        checkout = self.root / "an-unrelated-repository"
        (checkout / ".git").mkdir(parents=True)
        (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        copy = checkout / "candidate-private-copy.json"
        copy.write_bytes(self.candidate_path.read_bytes())
        with self.assertRaisesRegex(AdmissionError, "Git checkout"):
            admit(copy, self.approval_path, self.output)
        with self.assertRaisesRegex(AdmissionError, "Git checkout"):
            admit(self.candidate_path, self.approval_path, checkout / "published-output")
        self.assertFalse(self.output.exists())
        self.assertFalse((checkout / "published-output").exists())

    def test_rejects_linked_git_worktree_markers_as_input_and_output(self) -> None:
        checkout = self.root / "linked-worktree"
        checkout.mkdir()
        (checkout / ".git").write_text("gitdir: /example/.git/worktrees/linked\n", encoding="utf-8")
        copy = checkout / "source.json"
        copy.write_bytes(self.candidate_path.read_bytes())
        with self.assertRaisesRegex(AdmissionError, "Git checkout"):
            admit(copy, self.approval_path, self.output)
        with self.assertRaisesRegex(AdmissionError, "Git checkout"):
            admit(self.candidate_path, self.approval_path, checkout / "source-rich-output")
        self.assertFalse(self.output.exists())
        self.assertFalse((checkout / "source-rich-output").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX symlink fixture")
    def test_rejects_symlinked_parent_for_private_inputs_and_output(self) -> None:
        indirect = self.root / "indirect"
        indirect.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(AdmissionError, "indirect"):
            admit(indirect / "candidates.json", self.approval_path, self.output)
        with self.assertRaisesRegex(AdmissionError, "indirect"):
            admit(self.candidate_path, self.approval_path, indirect / "export")
        self.assertFalse(self.output.exists())

    def test_windows_private_output_fails_closed_without_acl_verification(self) -> None:
        with patch("aeonith.private_output._is_windows", return_value=True):
            with self.assertRaisesRegex(AdmissionError, "Windows private output ACL"):
                self.run_admission()
        self.assertFalse(self.output.exists())

    def test_rejects_unc_and_device_style_paths(self) -> None:
        for value in ("//server/share/private", r"\\server\share\private", r"\\?\C:\private"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(AdmissionError, "UNC or device"):
                    admit(self.candidate_path, self.approval_path, value)

    def test_no_overwrite_even_when_approval_is_valid(self) -> None:
        self.output.mkdir()
        marker = self.output / "leave-me-alone.txt"
        marker.write_text("original", encoding="utf-8")
        with self.assertRaisesRegex(AdmissionError, "already exists"):
            self.run_admission()
        self.assertEqual(marker.read_text(encoding="utf-8"), "original")

    def test_cli_pending_manifest_fails_closed_with_no_source_text_in_error(self) -> None:
        self.approval["approval_status"] = "REVIEW_PENDING_NOT_TRAINABLE"
        self.write_approval()
        result = subprocess.run([sys.executable, "-m", "training.admit_candidates",
            "--candidates", str(self.candidate_path), "--approval", str(self.approval_path),
            "--output", str(self.output)], capture_output=True, text=True, check=False,
            cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn("Ada closed the blue gate", result.stderr)


if __name__ == "__main__":
    unittest.main()
