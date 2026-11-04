"""Exact-byte, no-automatic-consent tests for the synthetic audit proposal bridge."""

from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training.admit_candidates import admit
from training import synthetic_audit_draft
from training.synthetic_audit_draft import AuditDraftError, main, prepare


def _example(number: int, split: str, passage: str) -> dict:
    return {
        "id": f"proposal-{number}", "source_id": f"synthetic-source-{number}",
        "split": split, "genre": "original synthetic fable", "lens": "symbolic",
        "passage": passage, "draft_status": "REVIEW_PENDING",
        "target": {
            "lens_reviews": [{"lens": "symbolic", "analysis": f"The bell permits a tentative symbol in story {number}.",
                              "basis": "textual", "support": [{"source": "work", "quote": "copper bell"}],
                              "limitations": ["The author's intention is not supplied."]}],
            "synthesis": f"A symbolic reading in story {number} is possible but not necessary.",
            "challenges": [{"text": "The bell might be an ordinary object.",
                            "support": [{"source": "work", "quote": "copper bell"}]}],
            "uncertainties": ["The passage does not disclose its final consequence."],
            "assessment": None,
        },
    }


@unittest.skipIf(os.name == "nt", "Native Windows private output writer is unqualified")
class SyntheticAuditDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.candidates = self.root / "candidates.json"
        self.approval = self.root / "approval.json"
        self.admitted = self.root / "admitted"
        self.exclusions = self.root / "withheld-exclusions.json"
        self.draft = self.root / "audit-draft"
        passages = (
            "Beneath a bent pine at noon, Mara polished a copper bell without ringing it.",
            "Across the winter market, ten glass kites followed a child carrying a copper bell.",
            "During the quiet storm, a mason buried a copper bell beside the shuttered observatory.",
            "Behind a crimson curtain, a wooden automaton balanced a copper bell above wet sand.",
        )
        examples = [_example(index, split, passage) for index, (split, passage) in
                    enumerate(zip(("train", "validation", "holdout", "train"), passages), 1)]
        candidate = {
            "schema_version": "aeonith.candidate_corpus.v1",
            "status": "REVIEW_PENDING_NOT_TRAINABLE",
            "generator_provenance": {
                "origin": "model_generated_synthetic", "generator": "ChatGPT",
                "third_party_text_used": False, "human_authorship_claimed": False,
                "publication_authorized": False,
            },
            "examples": examples,
        }
        self.candidates.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
        digest = hashlib.sha256(self.candidates.read_bytes()).hexdigest()
        records = [{
            "id": item["id"], "source_id": item["source_id"],
            "rights_basis": "synthetic_generated", "editorial_accepted": False,
            "permission_to_publish_adapter": False,
            "permission_to_train": item["id"] != "proposal-4",
            "disposition": "reject" if item["id"] == "proposal-4" else "admit",
            **({"reason_code": "quality"} if item["id"] == "proposal-4" else {}),
        } for item in examples]
        approval = {
            "schema_version": "aeonith.candidate_synthetic_admission.v2",
            "candidate_sha256": digest,
            "approval_status": "APPROVED_MODEL_GENERATED_PRIVATE_LOCAL_TRAINING",
            "permission_to_train": True,
            "operator_decision": {
                "identity": "Fixture Operator", "decision": "approve_exact_model_generated_private_training",
                "attested_at_utc": "2026-11-03T12:00:00Z", "candidate_sha256": digest,
            },
            "records": records,
        }
        self.approval.write_text(json.dumps(approval, sort_keys=True), encoding="utf-8")
        self.exclusions.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["independently-withheld-work-001"],
            "excluded_text_sha256": [], "excluded_5gram_sha256": [],
        }, sort_keys=True), encoding="utf-8")
        admit(self.candidates, self.approval, self.admitted)

    def test_prepared_manifest_contains_only_admitted_private_sources(self) -> None:
        audit = prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertEqual(audit["status"], "mechanically_checked_not_approved_or_trained")
        self.assertTrue(audit["draft_not_approved_or_trained"])
        self.assertEqual(audit["source_count"], 3)
        self.assertFalse(audit["model_trained"])
        manifest = json.loads((self.draft / "audit-manifest.json").read_text())
        self.assertEqual((self.draft / "audit-manifest.json").stat().st_ino,
                         (self.draft / "audit-inspect-pending.json").stat().st_ino)
        self.assertEqual({item["source_id"] for item in manifest["sources"]},
                         {"synthetic-source-1", "synthetic-source-2", "synthetic-source-3"})
        self.assertFalse((self.draft / "approval.json").exists())
        self.assertFalse((self.draft / "admission_receipt.json").exists())
        self.assertEqual(manifest["candidate_sha256"],
                         hashlib.sha256(self.candidates.read_bytes()).hexdigest())
        self.assertEqual(os.stat(self.draft).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.draft / "audit-manifest.json").st_mode & 0o777, 0o600)

    def test_admitted_split_byte_substitution_refused_without_draft(self) -> None:
        train = self.admitted / "train.jsonl"
        train.write_bytes(train.read_bytes() + b" ")
        with self.assertRaisesRegex(AuditDraftError, "bytes differ"):
            prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertFalse(self.draft.exists())

    def test_stale_candidate_sha_refused_without_draft(self) -> None:
        candidate = json.loads(self.candidates.read_text())
        candidate["examples"][0]["passage"] += " The room was empty."
        self.candidates.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertFalse(self.draft.exists())

    def test_approval_receipt_substitution_refused_without_draft(self) -> None:
        path = self.admitted / "admission_receipt.json"
        receipt = json.loads(path.read_text())
        receipt["split_counts"]["train"] = 400
        path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(AuditDraftError, "receipt is stale"):
            prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertFalse(self.draft.exists())

    def test_external_withheld_exclusion_required(self) -> None:
        self.exclusions.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": [], "excluded_text_sha256": [], "excluded_5gram_sha256": [],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertFalse(self.draft.exists())

    def test_overlapping_withheld_source_does_not_leave_apparently_valid_draft(self) -> None:
        """An inspector rejection must not leave a proposed manifest for promotion."""
        self.exclusions.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["synthetic-source-1"],
            "excluded_text_sha256": [], "excluded_5gram_sha256": [],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "withheld evaluation source"):
            prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertTrue(self.draft.is_dir(), "retain failed draft for operator diagnosis")
        self.assertFalse((self.draft / "audit-manifest.json").exists(),
                         "an invalid draft must not look promotable")
        self.assertTrue((self.draft / "audit-inspect-pending.json").is_file())

    def test_hostile_parent_swap_never_deletes_replacement_directory(self) -> None:
        """Same-UID path replacement must not direct cleanup at an unrelated inode."""
        self.exclusions.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["synthetic-source-1"],
            "excluded_text_sha256": [], "excluded_5gram_sha256": [],
        }), encoding="utf-8")
        moved = self.root / "moved-original"
        original_inspect = synthetic_audit_draft.inspect

        def swap_before_rejection(path: Path) -> dict:
            try:
                return original_inspect(path)
            except Exception:
                self.draft.rename(moved)
                self.draft.mkdir(mode=0o700)
                (self.draft / "decoy-keepsake").write_text("do not delete", encoding="utf-8")
                raise

        with patch("training.synthetic_audit_draft.inspect", side_effect=swap_before_rejection):
            with self.assertRaisesRegex(ValueError, "withheld evaluation source"):
                prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertEqual((self.draft / "decoy-keepsake").read_text(), "do not delete")
        self.assertFalse((moved / "audit-manifest.json").exists())
        self.assertTrue((moved / "audit-inspect-pending.json").exists())

    def test_inspection_failure_does_not_overwrite_same_uid_marker(self) -> None:
        """Never rename onto an existing user/other-process file on failure."""
        self.exclusions.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["synthetic-source-1"],
            "excluded_text_sha256": [], "excluded_5gram_sha256": [],
        }), encoding="utf-8")
        original_inspect = synthetic_audit_draft.inspect

        def insert_marker_then_reject(path: Path) -> dict:
            (self.draft / "audit-rejected.json").write_text("PRESERVE ME", encoding="utf-8")
            return original_inspect(path)

        with patch("training.synthetic_audit_draft.inspect", side_effect=insert_marker_then_reject):
            with self.assertRaisesRegex(ValueError, "withheld evaluation source"):
                prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertEqual((self.draft / "audit-rejected.json").read_text(), "PRESERVE ME")
        self.assertFalse((self.draft / "audit-manifest.json").exists())

    def test_successful_inspection_refuses_to_overwrite_injected_final_name(self) -> None:
        """An otherwise valid audit cannot clobber a same-UID inserted final file."""
        original_inspect = synthetic_audit_draft.inspect

        def insert_final_then_return(path: Path) -> dict:
            report = original_inspect(path)
            (self.draft / "audit-manifest.json").write_text("PRESERVE ME", encoding="utf-8")
            return report

        with patch("training.synthetic_audit_draft.inspect", side_effect=insert_final_then_return):
            with self.assertRaisesRegex(AuditDraftError, "publication refused"):
                prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertEqual((self.draft / "audit-manifest.json").read_text(), "PRESERVE ME")
        self.assertTrue((self.draft / "audit-inspect-pending.json").exists())

    def test_inspector_report_must_bind_exact_staged_manifest_bytes(self) -> None:
        """A substituted path/report with matching candidate ID is not an audit."""
        original_inspect = synthetic_audit_draft.inspect

        def substituted_report(path: Path) -> dict:
            report = original_inspect(path)
            return {**report, "manifest_sha256": "0" * 64}

        with patch("training.synthetic_audit_draft.inspect", side_effect=substituted_report):
            with self.assertRaisesRegex(AuditDraftError, "exact staged manifest"):
                prepare(self.candidates, self.approval, self.admitted, self.exclusions, self.draft)
        self.assertFalse((self.draft / "audit-manifest.json").exists())
        self.assertTrue((self.draft / "audit-inspect-pending.json").exists())

    def test_indirect_draft_parent_refused(self) -> None:
        target = self.root / "real-parent"
        target.mkdir(mode=0o700)
        link = self.root / "link-parent"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "indirect path"):
            prepare(self.candidates, self.approval, self.admitted, self.exclusions, link / "draft")
        self.assertFalse((target / "draft").exists())

    def test_cli_never_leaks_private_filenames_from_os_errors(self) -> None:
        private_name = "/private/family/manuscripts/Highly-Sensitive.docx"
        stderr = StringIO()
        arguments = ["--candidates", str(self.candidates), "--approval", str(self.approval),
                     "--admitted-dir", str(self.admitted), "--exclusions", str(self.exclusions),
                     "--output", str(self.draft)]
        with patch("training.synthetic_audit_draft.prepare",
                   side_effect=PermissionError(13, "Permission denied", private_name)):
            with redirect_stderr(stderr):
                self.assertEqual(main(arguments), 2)
        self.assertNotIn(private_name, stderr.getvalue())
        self.assertNotIn("Highly-Sensitive", stderr.getvalue())
        self.assertIn("refused", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
