"""Synthetic fixtures for supplemental offline corpus audit and attestation."""

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

from training.corpus_admission import AdmissionError, admit, fingerprints_for_text, inspect


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(index: int) -> dict:
    return {
        "id": f"record-{index}", "source_id": f"source-{index}",
        "prompt": f"Study this original fictional scene {index}: {SOURCE_TEXTS[index]}",
        "completion": f"Scene {index} supports a tentative interpretation of distance, without claiming any unseen chapters.",
        "rights_basis": "self_authored", "permission_to_train": True,
        "permission_to_publish_adapter": False,
    }


SOURCE_TEXTS = {
    1: "a keeper walks beyond a windmill toward the north ridge.",
    2: "a gardener maps unmarked constellations while the winter harbor freezes.",
    3: "a sailor listens beside a quiet fireplace after the last ferry leaves.",
}


class CorpusAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {split: [_row(i)] for split, i in (
            ("train", 1), ("validation", 2), ("holdout", 3))}
        self.files = {split: self.root / f"{split}.jsonl" for split in self.data}
        self.exclusion = self.root / "withheld-hashes.json"
        self.excluded = {
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["withheld-999"],
            "excluded_text_sha256": [fingerprints_for_text(
                "An entirely separate unseen passage about satellites and quiet planets."
            )["text_sha256"]],
            "excluded_5gram_sha256": [],
        }
        self.manifest = self.root / "audit-manifest.json"
        self.approvals = self.root / "approvals.json"
        self.output_dir = self.root / "private-receipt"
        self.receipt_file = self.output_dir / "admission_receipt.json"
        self.write_all()
        self.approval_data = {
            "schema_version": "aeonith.corpus_audit_approval.v1",
            "status": "APPROVED_PRIVATE_LOCAL_TRAINING",
            "permission_to_train": True,
            "corpus_fingerprint_sha256": inspect(self.manifest)["corpus_fingerprint_sha256"],
        }
        for role, verb, identity in (
            ("rights_holder", "approve_rights", "Synthetic Rights Holder"),
            ("corpus_owner", "approve_corpus", "Synthetic Rights Holder"),
            ("data_steward", "approve_data_use", "Separate Data Steward"),
            ("editorial_reviewer", "approve_editorial_quality", "Separate Editor"),
        ):
            self.approval_data[role] = {
                "identity": identity, "decision": verb,
                "attested_at_utc": "2026-11-02T18:00:00Z",
                "corpus_fingerprint_sha256": self.approval_data["corpus_fingerprint_sha256"],
            }
        self.write_approvals()

    def write_all(self) -> None:
        for split, rows in self.data.items():
            self.files[split].write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
        self.exclusion.write_text(json.dumps(self.excluded), encoding="utf-8")
        self.manifest_data = {
            "schema_version": "aeonith.corpus_audit_manifest.v1",
            "splits": {split: {"path": path.name, "sha256": _sha(path)}
                       for split, path in self.files.items()},
            "exclusions": {"path": self.exclusion.name, "sha256": _sha(self.exclusion)},
            "sources": [
                {"source_id": row["source_id"], "source_text":
                 f"scene {row['id'].split('-')[1]}: {SOURCE_TEXTS[int(row['id'].split('-')[1])]}",
                 "rights_basis": "self_authored",
                 "provenance_reference": f"synthetic original test fixture-{row['id']}",
                 "rights_claimant": "Synthetic Rights Holder",
                 "permission_to_train": True, "editorial_accepted": True}
                for rows in self.data.values() for row in rows
            ],
        }
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest.write_text(json.dumps(self.manifest_data), encoding="utf-8")

    def write_approvals(self) -> None:
        self.approvals.write_text(json.dumps(self.approval_data), encoding="utf-8")

    def update_approval_fingerprint(self) -> None:
        fingerprint = inspect(self.manifest)["corpus_fingerprint_sha256"]
        self.approval_data["corpus_fingerprint_sha256"] = fingerprint
        for role in ("rights_holder", "corpus_owner", "data_steward", "editorial_reviewer"):
            self.approval_data[role]["corpus_fingerprint_sha256"] = fingerprint
        self.write_approvals()

    def test_inspect_is_text_free_and_not_an_approval(self) -> None:
        result = inspect(self.manifest)
        self.assertEqual(result["status"], "mechanically_checked_not_approved_or_trained")
        self.assertEqual(result["split_counts"], {"train": 1, "validation": 1, "holdout": 1})
        self.assertFalse(result["independent_rights_authentication"])
        self.assertFalse(result["semantic_leakage_absent_proven"])
        self.assertNotIn("windmill", json.dumps(result))
        self.assertFalse(self.receipt_file.exists())

    def test_explicit_attestations_create_new_text_free_private_receipt(self) -> None:
        if os.name == "nt":
            with self.assertRaisesRegex(AdmissionError, "qualified ACL/custody broker"):
                admit(self.manifest, self.approvals, self.output_dir)
            self.assertFalse(self.output_dir.exists())
            return
        result = admit(self.manifest, self.approvals, self.output_dir)
        self.assertEqual(result["status"], "operator_attested_private_training_only_not_trained")
        self.assertFalse(result["attestation_identities_independently_authenticated"])
        self.assertFalse(result["adapter_publication_authorized"])
        self.assertTrue(self.receipt_file.is_file())
        self.assertEqual(json.loads(self.receipt_file.read_text()), result)
        self.assertNotIn("windmill", self.receipt_file.read_text())
        with self.assertRaisesRegex(AdmissionError, "already exists"):
            admit(self.manifest, self.approvals, self.output_dir)

    @unittest.skipIf(os.name == "nt", "Windows private receipt writing is intentionally disabled")
    def test_explicit_sole_original_owner_does_not_need_fictional_third_party(self) -> None:
        fingerprint = inspect(self.manifest)["corpus_fingerprint_sha256"]
        self.approval_data = {
            "schema_version": "aeonith.corpus_audit_owner_approval.v1",
            "corpus_fingerprint_sha256": fingerprint,
            "status": "APPROVED_SELF_AUTHORED_PRIVATE_TRAINING",
            "permission_to_train": True,
            "sole_owner_decision": {
                "identity": "Synthetic Rights Holder",
                "decision": "approve_sole_owner_original_private_training",
                "attested_at_utc": "2026-11-02T18:00:00Z",
                "corpus_fingerprint_sha256": fingerprint,
            },
        }
        self.write_approvals()
        receipt = admit(self.manifest, self.approvals, self.output_dir)
        self.assertEqual(receipt["status"], "operator_attested_sole_original_owner_private_only_not_trained")
        self.assertEqual(receipt["approval_mode"], "sole_original_owner_self_authored")
        self.assertFalse(receipt["independent_rights_authentication"])
        self.assertFalse(receipt["independent_editorial_review_claimed"])
        self.assertFalse(receipt["adapter_publication_authorized"])
        self.assertEqual(json.loads(self.receipt_file.read_text()), receipt)

    def test_sole_owner_cannot_claim_sources_of_another_rights_claimant(self) -> None:
        fingerprint = inspect(self.manifest)["corpus_fingerprint_sha256"]
        self.approval_data = {
            "schema_version": "aeonith.corpus_audit_owner_approval.v1",
            "corpus_fingerprint_sha256": fingerprint,
            "status": "APPROVED_SELF_AUTHORED_PRIVATE_TRAINING",
            "permission_to_train": True,
            "sole_owner_decision": {
                "identity": "Someone Else", "decision": "approve_sole_owner_original_private_training",
                "attested_at_utc": "2026-11-02T18:00:00Z",
                "corpus_fingerprint_sha256": fingerprint,
            },
        }
        self.write_approvals()
        with self.assertRaisesRegex(AdmissionError, "sole original owner|rights claimant"):
            admit(self.manifest, self.approvals, self.output_dir)
        self.assertFalse(self.receipt_file.exists())

    def test_owner_only_refuses_any_record_adapter_publication_permission(self) -> None:
        self.data["train"][0]["permission_to_publish_adapter"] = True
        self.files["train"].write_text(json.dumps(self.data["train"][0]) + "\n", encoding="utf-8")
        self.manifest_data["splits"]["train"]["sha256"] = _sha(self.files["train"])
        self.write_manifest()
        fingerprint = inspect(self.manifest)["corpus_fingerprint_sha256"]
        self.approval_data = {
            "schema_version": "aeonith.corpus_audit_owner_approval.v1",
            "corpus_fingerprint_sha256": fingerprint,
            "status": "APPROVED_SELF_AUTHORED_PRIVATE_TRAINING", "permission_to_train": True,
            "sole_owner_decision": {"identity": "Synthetic Rights Holder",
                "decision": "approve_sole_owner_original_private_training",
                "attested_at_utc": "2026-11-02T18:00:00Z", "corpus_fingerprint_sha256": fingerprint},
        }
        self.write_approvals()
        with self.assertRaisesRegex(AdmissionError, "adapter publication"):
            admit(self.manifest, self.approvals, self.output_dir)
        self.assertFalse(self.receipt_file.exists())

    def test_owner_only_refuses_other_valid_rights_basis(self) -> None:
        # Public-domain material may be usable under a different policy, but
        # it is not evidence of sole ownership of every source in this mode.
        self.data["train"][0]["rights_basis"] = "public_domain"
        self.write_all()
        self.manifest_data["sources"][0]["rights_basis"] = "public_domain"
        self.write_manifest()
        fingerprint = inspect(self.manifest)["corpus_fingerprint_sha256"]
        self.approval_data = {
            "schema_version": "aeonith.corpus_audit_owner_approval.v1",
            "corpus_fingerprint_sha256": fingerprint,
            "status": "APPROVED_SELF_AUTHORED_PRIVATE_TRAINING", "permission_to_train": True,
            "sole_owner_decision": {"identity": "Synthetic Rights Holder",
                "decision": "approve_sole_owner_original_private_training",
                "attested_at_utc": "2026-11-02T18:00:00Z", "corpus_fingerprint_sha256": fingerprint},
        }
        self.write_approvals()
        with self.assertRaisesRegex(AdmissionError, "self-authored source"):
            admit(self.manifest, self.approvals, self.output_dir)
        self.assertFalse(self.output_dir.exists())

    @unittest.skipIf(os.name == "nt", "Windows private receipt writing is intentionally disabled")
    def test_ancestor_swap_after_receipt_mkdir_cannot_redirect_private_bytes(self) -> None:
        """Synthetic same-user attacker swaps a newly created receipt directory."""
        attacker = self.root / "attacker-readable"
        attacker.mkdir()
        displaced = self.root / "displaced-private"
        actual_mkdir = os.mkdir

        def swap_after_mkdir(path, mode=0o777, *, dir_fd=None):
            if dir_fd is None:
                result = actual_mkdir(path, mode)
            else:
                result = actual_mkdir(path, mode, dir_fd=dir_fd)
            if str(path) in {str(self.output_dir), self.output_dir.name}:
                self.output_dir.rename(displaced)
                self.output_dir.symlink_to(attacker, target_is_directory=True)
            return result

        try:
            with patch("training.corpus_admission.os.mkdir", side_effect=swap_after_mkdir):
                with self.assertRaises((AdmissionError, OSError)):
                    admit(self.manifest, self.approvals, self.output_dir)
            self.assertFalse((attacker / "admission_receipt.json").exists())
            self.assertFalse((displaced / "admission_receipt.json").exists())
        finally:
            # Only synthetic paths created by this test are touched.
            if self.output_dir.is_symlink():
                self.output_dir.unlink()

    @unittest.skipIf(os.name == "nt", "Windows private receipt writing is intentionally disabled")
    def test_wsl_drvfs_9p_or_ntfs_mount_rejected_before_creating_receipt(self) -> None:
        for unsupported in ("9p", "drvfs", "ntfs3"):
            with self.subTest(filesystem=unsupported):
                with patch("aeonith.private_output._linux_mount_type_for_fd", return_value=unsupported):
                    with self.assertRaisesRegex(AdmissionError, "filesystem is unqualified"):
                        admit(self.manifest, self.approvals, self.output_dir)
                self.assertFalse(self.output_dir.exists())

    def test_wrong_attestation_or_consent_fails_without_output(self) -> None:
        self.approval_data["permission_to_train"] = False
        self.write_approvals()
        with self.assertRaisesRegex(AdmissionError, "not approved"):
            admit(self.manifest, self.approvals, self.output_dir)
        self.assertFalse(self.receipt_file.exists())

    def test_duplicate_editor_and_steward_identity_rejected(self) -> None:
        self.approval_data["editorial_reviewer"]["identity"] = "separate data steward"
        self.write_approvals()
        with self.assertRaisesRegex(AdmissionError, "distinct"):
            admit(self.manifest, self.approvals, self.output_dir)
        self.assertFalse(self.receipt_file.exists())

    def test_unknown_source_or_unapproved_record_rejected(self) -> None:
        self.manifest_data["sources"][0]["provenance_reference"] = "UNKNOWN"
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "unknown source"):
            inspect(self.manifest)
        self.manifest_data["sources"][0]["provenance_reference"] = "synthetic fixture"
        self.manifest_data["sources"][0]["permission_to_train"] = False
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "rights or editorial"):
            inspect(self.manifest)

    def test_file_mutation_without_rebinding_fingerprint_rejected(self) -> None:
        self.data["train"][0]["prompt"] += " More words."
        self.files["train"].write_text(json.dumps(self.data["train"][0]) + "\n")
        with self.assertRaisesRegex(AdmissionError, "fingerprint mismatch"):
            inspect(self.manifest)
        self.assertFalse(self.receipt_file.exists())

    def test_new_file_digest_requires_new_bound_attestations(self) -> None:
        self.manifest_data["sources"][0]["provenance_reference"] = "A new source description"
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "not approved"):
            admit(self.manifest, self.approvals, self.output_dir)
        self.assertFalse(self.receipt_file.exists())

    def test_normalized_duplicate_across_splits_rejected(self) -> None:
        self.data["validation"][0]["prompt"] = self.data["train"][0]["prompt"].upper()
        self.write_all()
        with self.assertRaisesRegex((AdmissionError, ValueError), "duplicated|overlap"):
            inspect(self.manifest)

    def test_near_duplicate_across_splits_rejected(self) -> None:
        first = "At sunrise the clock keeper carried an old copper lantern down the stone stairs toward the ancient river."
        second = "At sunrise the clock keeper carried an old copper lantern down the stone stairs toward the ancient river!"
        self.data["train"][0]["prompt"] = first
        self.data["validation"][0]["prompt"] = second + " A new ending."
        self.write_all()
        self.manifest_data["sources"][0]["source_text"] = first
        self.manifest_data["sources"][1]["source_text"] = second
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "near-duplicate"):
            inspect(self.manifest)

    def test_excluded_source_or_five_word_shingle_denied(self) -> None:
        self.excluded["excluded_source_ids"].append("source-1")
        self.write_all()
        with self.assertRaisesRegex(AdmissionError, "withheld evaluation source"):
            inspect(self.manifest)
        self.excluded["excluded_source_ids"].remove("source-1")
        phrase = "a keeper walks beyond a windmill toward the north ridge"
        self.excluded["excluded_5gram_sha256"] = fingerprints_for_text(phrase)["five_word_shingle_sha256"]
        self.write_all()
        with self.assertRaisesRegex(AdmissionError, "withheld evaluation shingles"):
            inspect(self.manifest)

    def test_reused_source_passage_under_distinct_ids_and_lenses_rejected(self) -> None:
        # Prompt wrappers differ; source ID and record IDs differ, but the
        # underlying literary text is identical across TRAIN and holdout.
        self.data["holdout"][0]["prompt"] = (
            "Evaluate this through a DIFFERENT ethical lens, not symbolism:\n"
            + "scene 1: " + SOURCE_TEXTS[1]
        )
        self.write_all()
        self.manifest_data["sources"][2]["source_text"] = (
            self.manifest_data["sources"][0]["source_text"])
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "identical source passage"):
            inspect(self.manifest)

    def test_false_source_content_claim_rejected_even_when_row_contract_valid(self) -> None:
        self.manifest_data["sources"][0]["source_text"] = (
            "This completely different scene never appears in the training prompt.")
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "not contained"):
            inspect(self.manifest)

    def test_withheld_normalized_source_text_digest_blocks_new_prompt_wrapper(self) -> None:
        source = self.manifest_data["sources"][0]["source_text"]
        self.excluded["excluded_text_sha256"] = [
            fingerprints_for_text(source.upper().replace("  ", " "))["text_sha256"]]
        self.write_all()
        with self.assertRaisesRegex(AdmissionError, "source passage overlaps"):
            inspect(self.manifest)

    def test_oversized_shingle_field_refused_without_truncating_tail(self) -> None:
        self.data["train"][0]["prompt"] = (
            "Study scene 1: " + ("zz " * 805)
            + self.manifest_data["sources"][0]["source_text"])
        # Keep within the existing per-row 12,000-character contract.
        self.assertLess(len(self.data["train"][0]["prompt"]), 12000)
        self.write_all()
        with self.assertRaisesRegex(AdmissionError, "shingle audit capacity"):
            inspect(self.manifest)

    def test_duplicate_json_metadata_rejected(self) -> None:
        self.manifest.write_text('{"schema_version":"x","schema_version":"x"}')
        with self.assertRaisesRegex(AdmissionError, "duplicate"):
            inspect(self.manifest)

    def test_cli_failure_does_not_print_private_text(self) -> None:
        self.approval_data["permission_to_train"] = False
        self.write_approvals()
        result = subprocess.run([
            sys.executable, "-m", "training.corpus_admission", "admit",
            "--manifest", str(self.manifest), "--approval", str(self.approvals),
            "--output", str(self.output_dir),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.receipt_file.exists())
        self.assertNotIn("windmill", result.stderr + result.stdout)

    def test_symlinked_private_input_refused(self) -> None:
        alias = self.root / "alias-train.jsonl"
        try:
            alias.symlink_to(self.files["train"])
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable to this host")
        self.manifest_data["splits"]["train"]["path"] = alias.name
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "symlinks"):
            inspect(self.manifest)

    def test_network_style_input_path_refused(self) -> None:
        self.manifest_data["splits"]["train"]["path"] = r"\\server\shared\train.jsonl"
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "local file path"):
            inspect(self.manifest)

    def test_unhashable_source_rights_basis_is_sanitized_refusal(self) -> None:
        self.manifest_data["sources"][0]["rights_basis"] = ["self_authored"]
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "rights or editorial"):
            inspect(self.manifest)
        cli = subprocess.run([
            sys.executable, "-m", "training.corpus_admission", "inspect",
            "--manifest", str(self.manifest),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(cli.returncode, 2)
        self.assertIn("Corpus audit refused", cli.stderr)
        self.assertNotIn("Traceback", cli.stderr)

    def test_private_inputs_inside_another_git_checkout_refused(self) -> None:
        other = self.root / "another-git-worktree"
        other.mkdir()
        (other / ".git").write_text("gitdir: /tmp/illustrative-worktree\n")
        copied = other / "train.jsonl"
        copied.write_bytes(self.files["train"].read_bytes())
        self.manifest_data["splits"]["train"]["path"] = str(copied)
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "all git checkouts"):
            inspect(self.manifest)

    def test_private_receipt_inside_another_git_checkout_refused(self) -> None:
        other = self.root / "another-git-worktree"
        other.mkdir()
        (other / ".git").write_text("gitdir: /tmp/illustrative-worktree\n")
        with self.assertRaisesRegex(AdmissionError, "outside git checkouts"):
            admit(self.manifest, self.approvals, other / "private-receipt")
        self.assertFalse((other / "private-receipt").exists())

    def test_short_near_duplicate_source_passages_crossing_splits_rejected(self) -> None:
        first = "The single silver key vanished beneath the copper window during autumn."
        second = "The single golden key vanished beneath the copper window during autumn."
        self.data["train"][0]["prompt"] = "Use a symbolic lens:\n" + first
        self.data["validation"][0]["prompt"] = "Use an ethical lens:\n" + second
        self.write_all()
        self.manifest_data["sources"][0]["source_text"] = first
        self.manifest_data["sources"][1]["source_text"] = second
        self.write_manifest()
        with self.assertRaisesRegex(AdmissionError, "near-duplicate source passages"):
            inspect(self.manifest)


if __name__ == "__main__":
    unittest.main()
