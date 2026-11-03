"""Synthetic-only admission binding across the audit, approval and training plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from training.corpus import CorpusError
from training.corpus_admission import inspect, verify_admission
from training.train_lora import inspect_admitted_plan


PASSAGES = (
    "a keeper walks beyond a windmill toward the north ridge.",
    "a gardener maps unmarked constellations while the winter harbor freezes.",
    "a sailor listens beside a quiet fireplace after the last ferry leaves.",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AdmissionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "config.json").write_text('{"model_type":"qwen3_5"}')
        (self.base / "weights.safetensors").write_bytes(b"synthetic model fixture")
        (self.base / "tokenizer.json").write_text('{"version":"1.0"}')
        self.splits: dict[str, Path] = {}
        self.sources: list[dict] = []
        for index, split in enumerate(("train", "validation", "holdout")):
            passage = PASSAGES[index]
            path = self.root / f"{split}.jsonl"
            path.write_text(json.dumps({
                "id": f"record-{index}", "source_id": f"source-{index}",
                "prompt": f"Study this invented scene {index}: {passage}",
                "completion": f"Interpret scene {index} without claiming access to other passages.",
                "rights_basis": "self_authored", "permission_to_train": True,
                "permission_to_publish_adapter": False,
            }) + "\n")
            self.splits[split] = path
            self.sources.append({
                "source_id": f"source-{index}", "source_text": passage,
                "rights_basis": "self_authored", "provenance_reference": f"synthetic-fixture-{index}",
                "rights_claimant": "Synthetic Rights Holder", "permission_to_train": True,
                "editorial_accepted": True,
            })
        self.plan = self.root / "plan.json"
        self.plan.write_text(json.dumps({
            "schema_version": "aeonith.training_plan.v1",
            "base_model": {"id": "Qwen/Qwen3.5-0.8B", "revision": "a" * 40,
                           "local_dir": str(self.base)},
            "corpus": {split: path.name for split, path in self.splits.items()},
            "training": {"max_steps": 1, "max_length": 128, "seed": 7},
        }))
        self.exclusions = self.root / "exclusions.json"
        self.exclusions.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["withheld-source"],
            "excluded_text_sha256": [], "excluded_5gram_sha256": [],
        }))
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": "aeonith.corpus_audit_manifest.v1",
            "splits": {split: {"path": path.name, "sha256": _sha(path)}
                       for split, path in self.splits.items()},
            "exclusions": {"path": self.exclusions.name, "sha256": _sha(self.exclusions)},
            "sources": self.sources,
        }))
        self.approval = self.root / "approval.json"
        fingerprint = inspect(self.manifest)["corpus_fingerprint_sha256"]
        record = {"schema_version": "aeonith.corpus_audit_approval.v1",
                  "corpus_fingerprint_sha256": fingerprint,
                  "status": "APPROVED_PRIVATE_LOCAL_TRAINING", "permission_to_train": True}
        for role, decision, identity in (
            ("rights_holder", "approve_rights", "Rights Holder Fixture"),
            ("corpus_owner", "approve_corpus", "Rights Holder Fixture"),
            ("data_steward", "approve_data_use", "Separate Steward Fixture"),
            ("editorial_reviewer", "approve_editorial_quality", "Separate Editor Fixture"),
        ):
            record[role] = {"identity": identity, "decision": decision,
                            "attested_at_utc": "2026-11-02T18:00:00Z",
                            "corpus_fingerprint_sha256": fingerprint}
        self.approval.write_text(json.dumps(record))
        self.receipt = self.root / "receipt.json"

    def write_valid_receipt(self) -> None:
        from training.corpus_admission import check_approvals
        self.receipt.write_text(json.dumps(check_approvals(self.manifest, self.approval)))

    def test_exact_bundle_can_be_verified_read_only(self):
        self.write_valid_receipt()
        result = verify_admission(self.manifest, self.approval, self.receipt)
        preflight, dataset, admission = inspect_admitted_plan(
            self.plan, self.manifest, self.approval, self.receipt)
        self.assertEqual(result["corpus_fingerprint_sha256"], admission["corpus_fingerprint_sha256"])
        self.assertEqual(preflight["split_counts"], admission["split_counts"])
        self.assertEqual(set(dataset), {"train", "validation", "holdout"})
        self.assertNotIn("windmill", json.dumps(admission))

        cli = subprocess.run([
            sys.executable, "-m", "training.train_lora", "inspect-admission",
            "--plan", str(self.plan), "--audit-manifest", str(self.manifest),
            "--approval", str(self.approval), "--admission-receipt", str(self.receipt),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["admission"]["status"],
                         "operator_attested_private_training_only_not_trained")
        self.assertNotIn("windmill", cli.stdout + cli.stderr)

        verify_cli = subprocess.run([
            sys.executable, "-m", "training.corpus_admission", "verify",
            "--manifest", str(self.manifest), "--approval", str(self.approval),
            "--receipt", str(self.receipt),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(verify_cli.returncode, 0, verify_cli.stderr)
        self.assertNotIn("windmill", verify_cli.stdout + verify_cli.stderr)

    def test_refuses_receipt_tampering_and_changed_approval(self):
        self.write_valid_receipt()
        tampered = json.loads(self.receipt.read_text())
        tampered["status"] = "trained_and_approved"
        self.receipt.write_text(json.dumps(tampered))
        with self.assertRaisesRegex(ValueError, "receipt"):
            verify_admission(self.manifest, self.approval, self.receipt)
        self.write_valid_receipt()
        approval = json.loads(self.approval.read_text())
        approval["data_steward"]["decision"] = "reject"
        self.approval.write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "attestation"):
            verify_admission(self.manifest, self.approval, self.receipt)

    def test_refuses_train_plan_with_other_corpus_bytes(self):
        self.write_valid_receipt()
        alternate = self.root / "different-train.jsonl"
        alternate.write_text(self.splits["train"].read_text().replace("windmill", "watermill"))
        plan = json.loads(self.plan.read_text())
        plan["corpus"]["train"] = alternate.name
        self.plan.write_text(json.dumps(plan))
        with self.assertRaisesRegex(CorpusError, "admitted corpus"):
            inspect_admitted_plan(self.plan, self.manifest, self.approval, self.receipt)

    def test_execute_refuses_unqualified_training_output_before_optimizer(self):
        self.write_valid_receipt()
        dest = self.root / "adapter"
        run = subprocess.run([
            sys.executable, "-m", "training.train_lora", "train",
            "--plan", str(self.plan), "--audit-manifest", str(self.manifest),
            "--approval", str(self.approval), "--admission-receipt", str(self.receipt),
            "--output", str(dest), "--device", "cpu", "--execute",
        ], capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 2)
        self.assertIn("output custody broker", run.stderr)
        self.assertFalse(dest.exists())
        self.assertNotIn("windmill", run.stderr + run.stdout)


if __name__ == "__main__":
    unittest.main()
