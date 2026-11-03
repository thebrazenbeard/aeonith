"""Negative-first contracts for model-generated, privately approved pilot data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from training.admit_candidates import AdmissionError, _admitted_lens_coverage, _validated_splits, admit
from training.corpus import CorpusError, _check_row
from training.corpus_admission import (AdmissionError as AuditAdmissionError,
                                      check_approvals, fingerprints_for_text, inspect)


def candidate_example(number: int, split: str) -> dict:
    passage = f"At hour {number}, Nira set a copper bell beside a silent doorway."
    return {
        "id": f"synthetic-{number}", "source_id": f"synthetic-work-{number}",
        "split": split, "genre": "original synthetic fable", "lens": "symbolic",
        "passage": passage,
        "target": {
            "lens_reviews": [{"lens": "symbolic", "analysis": "The bell can suggest an invitation.",
                              "basis": "textual", "support": [{"source": "work", "quote": "copper bell"}],
                              "limitations": ["The passage does not establish anyone's intent."]}],
            "synthesis": "A tentative symbolism fits but is not mandatory.",
            "challenges": [{"text": "The bell might be ordinary hardware.",
                            "support": [{"source": "work", "quote": "copper bell"}]}],
            "uncertainties": ["Whether the doorway opens is unstated."], "assessment": None,
        },
        "draft_status": "REVIEW_PENDING",
    }


class SyntheticGeneratedAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidate_path = self.root / "candidate.json"
        self.approval_path = self.root / "approval.json"
        self.output_path = self.root / "admitted"
        self.candidate = {
            "schema_version": "aeonith.candidate_corpus.v1",
            "status": "REVIEW_PENDING_NOT_TRAINABLE",
            "generator_provenance": {
                "origin": "model_generated_synthetic", "generator": "ChatGPT",
                "third_party_text_used": False, "human_authorship_claimed": False,
                "publication_authorized": False,
            },
            "examples": [candidate_example(1, "train"), candidate_example(2, "validation"),
                         candidate_example(3, "holdout")],
        }
        self.write_candidate()
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        self.approval = {
            "schema_version": "aeonith.candidate_synthetic_admission.v1",
            "candidate_sha256": digest,
            "approval_status": "APPROVED_MODEL_GENERATED_PRIVATE_LOCAL_TRAINING",
            "permission_to_train": True,
            "operator_decision": {
                "identity": "Fixture Operator", "decision": "approve_exact_model_generated_private_training",
                "attested_at_utc": "2026-11-03T12:00:00Z", "candidate_sha256": digest,
            },
            "records": [{
                "id": row["id"], "source_id": row["source_id"],
                "rights_basis": "synthetic_generated", "permission_to_train": True,
                "editorial_accepted": False, "permission_to_publish_adapter": False,
            } for row in self.candidate["examples"]],
        }
        self.write_approval()

    def write_candidate(self) -> None:
        self.candidate_path.write_text(json.dumps(self.candidate, sort_keys=True), encoding="utf-8")

    def write_approval(self) -> None:
        self.approval_path.write_text(json.dumps(self.approval, sort_keys=True), encoding="utf-8")

    def test_approves_exact_model_generated_private_pilot_without_false_human_authorship(self) -> None:
        if os.name == "nt":
            # A semantically valid synthetic approval does not grant Windows
            # private-write authority. Check the admission contract in memory,
            # then independently verify the Windows custody gate refuses I/O.
            candidate_sha = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
            splits, mode = _validated_splits(self.candidate, self.approval, candidate_sha)
            self.assertEqual(mode, "operator_approved_model_generated_private_only")
            self.assertEqual({split: len(rows) for split, rows in splits.items()},
                             {"train": 1, "validation": 1, "holdout": 1})
            with self.assertRaisesRegex(AdmissionError, "Windows private output ACL boundary"):
                admit(self.candidate_path, self.approval_path, self.output_path)
            self.assertFalse(self.output_path.exists())
            return
        receipt = admit(self.candidate_path, self.approval_path, self.output_path)
        self.assertEqual(receipt["approval_mode"], "operator_approved_model_generated_private_only")
        self.assertFalse(receipt["independent_editorial_review_claimed"])
        self.assertFalse(receipt["adapter_publication_record_permissions_complete"])
        self.assertFalse(receipt["blind_holdout_qualified"])
        for split in ("train", "validation", "holdout"):
            row = json.loads((self.output_path / f"{split}.jsonl").read_text())
            self.assertEqual(row["rights_basis"], "synthetic_generated")
            self.assertEqual(row["source_origin"], "model_generated_synthetic")
            self.assertFalse(row["permission_to_publish_adapter"])
            self.assertFalse("rights_claimant" in row)

    def test_exact_approval_is_required_after_generation(self) -> None:
        self.approval["operator_decision"]["candidate_sha256"] = "0" * 64
        self.write_approval()
        with self.assertRaisesRegex(AdmissionError, "SHA-256|attestation"):
            admit(self.candidate_path, self.approval_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_cannot_relabel_third_party_or_human_authored_material_as_synthetic(self) -> None:
        for field, value in (("third_party_text_used", True), ("human_authorship_claimed", True),
                             ("publication_authorized", True), ("origin", "public_domain")):
            with self.subTest(field=field):
                self.candidate["generator_provenance"][field] = value
                self.write_candidate()
                digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
                self.approval["candidate_sha256"] = digest
                self.approval["operator_decision"]["candidate_sha256"] = digest
                self.write_approval()
                with self.assertRaises(AdmissionError):
                    admit(self.candidate_path, self.approval_path, self.output_path)
                self.assertFalse(self.output_path.exists())
                self.candidate["generator_provenance"][field] = (
                    "model_generated_synthetic" if field == "origin" else False)

    def test_synthetic_data_cannot_claim_self_authored_or_adapter_publication(self) -> None:
        for field, value in (("rights_basis", "self_authored"),
                             ("permission_to_publish_adapter", True), ("editorial_accepted", True)):
            with self.subTest(field=field):
                self.approval["records"][0][field] = value
                self.write_approval()
                with self.assertRaises(AdmissionError):
                    admit(self.candidate_path, self.approval_path, self.output_path)
                self.assertFalse(self.output_path.exists())
                self.approval["records"][0][field] = {
                    "rights_basis": "synthetic_generated", "permission_to_publish_adapter": False,
                    "editorial_accepted": False,
                }[field]

    def test_synthetic_training_row_needs_explicit_origin_and_private_only(self) -> None:
        row = {"id": "synthetic-1", "source_id": "synthetic-work-1", "prompt": "Review a bell.",
               "completion": "A bell may symbolize change.", "rights_basis": "synthetic_generated",
               "source_origin": "model_generated_synthetic", "permission_to_train": True,
               "permission_to_publish_adapter": False}
        self.assertEqual(_check_row(row, "train", 1), row)
        missing = {key: value for key, value in row.items() if key != "source_origin"}
        with self.assertRaises(CorpusError):
            _check_row(missing, "train", 1)
        publish = {**row, "permission_to_publish_adapter": True}
        with self.assertRaises(CorpusError):
            _check_row(publish, "train", 1)

    def prepare_v2_decisions(self) -> None:
        # Two extra proposals leave each split populated when one train and
        # one validation example are independently declined.
        self.candidate["examples"].extend((candidate_example(4, "train"),
                                           candidate_example(5, "validation")))
        # The rejected train example uniquely claims this lens; its removal
        # must not inflate the admitted train-lens coverage receipt.
        self.candidate["examples"][0]["lens"] = "psychological"
        self.candidate["examples"][0]["target"]["lens_reviews"][0]["lens"] = "psychological"
        self.write_candidate()
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        self.approval["schema_version"] = "aeonith.candidate_synthetic_admission.v2"
        self.approval["candidate_sha256"] = digest
        self.approval["operator_decision"]["candidate_sha256"] = digest
        self.approval["records"] = [{
            "id": row["id"], "source_id": row["source_id"],
            "rights_basis": "synthetic_generated", "permission_to_train": True,
            "editorial_accepted": False, "permission_to_publish_adapter": False,
            "disposition": "admit",
        } for row in self.candidate["examples"]]
        self.write_approval()

    def test_v2_explicit_rejections_and_exclusions_never_reach_training_files(self) -> None:
        self.prepare_v2_decisions()
        self.approval["records"][0].update(disposition="reject", permission_to_train=False,
                                           reason_code="quality")
        self.approval["records"][1].update(disposition="exclude", permission_to_train=False,
                                           reason_code="rights_unclear")
        self.write_approval()
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        splits, mode = _validated_splits(self.candidate, self.approval, digest)
        self.assertEqual(mode, "operator_approved_model_generated_private_only")
        self.assertEqual({split: len(rows) for split, rows in splits.items()},
                         {"train": 1, "validation": 1, "holdout": 1})
        self.assertEqual({row["id"] for rows in splits.values() for row in rows},
                         {"synthetic-3", "synthetic-4", "synthetic-5"})
        coverage = _admitted_lens_coverage(self.candidate, splits)
        self.assertEqual(coverage["train"], ["symbolic"])
        self.assertNotIn("psychological", coverage["train"])
        if os.name != "nt":
            receipt = admit(self.candidate_path, self.approval_path, self.output_path)
            self.assertEqual(receipt["record_disposition_counts"],
                             {"admit": 3, "exclude": 1, "reject": 1})
            self.assertEqual(receipt["lenses_by_split"], coverage)
            self.assertIn("psychological", receipt["train_lenses_missing"])
            for split in ("train", "validation", "holdout"):
                text = (self.output_path / f"{split}.jsonl").read_text()
                self.assertNotIn("synthetic-1", text)
                self.assertNotIn("synthetic-2", text)
        else:
            with self.assertRaisesRegex(AdmissionError, "Windows private output ACL boundary"):
                admit(self.candidate_path, self.approval_path, self.output_path)

    def test_v2_rejected_or_excluded_records_need_explicit_denial_and_reason(self) -> None:
        self.prepare_v2_decisions()
        first = self.approval["records"][0]
        first.update(disposition="reject", permission_to_train=False, reason_code="quality")
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        for field, value in (("permission_to_train", True), ("reason_code", []),
                             ("reason_code", ""),
                             ("reason_code", "unbounded-unrecognized-reason"),
                             ("disposition", "maybe")):
            with self.subTest(field=field, value=value):
                old = first[field]
                first[field] = value
                with self.assertRaises(AdmissionError):
                    _validated_splits(self.candidate, self.approval, digest)
                first[field] = old
        first.update(disposition="admit", permission_to_train=True)
        with self.assertRaisesRegex(AdmissionError, "exclusion reason"):
            _validated_splits(self.candidate, self.approval, digest)

    def test_v2_must_cover_every_id_and_keep_all_three_splits(self) -> None:
        self.prepare_v2_decisions()
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        one = self.approval["records"][0]
        self.approval["records"] = self.approval["records"][1:]
        with self.assertRaisesRegex(AdmissionError, "record-level decisions"):
            _validated_splits(self.candidate, self.approval, digest)
        self.approval["records"].insert(0, one)
        self.approval["records"][2].update(disposition="exclude", permission_to_train=False,
                                           reason_code="out_of_scope")
        with self.assertRaisesRegex(AdmissionError, "every split"):
            _validated_splits(self.candidate, self.approval, digest)


class SyntheticAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {split: self.root / f"{split}.jsonl" for split in
                      ("train", "validation", "holdout")}
        self.manifest_file = self.root / "audit.json"
        self.approval_file = self.root / "approval.json"
        self.candidate_sha = "9" * 64
        self.sources = (
            "the last oak held a lantern through the quiet winter",
            "a copper river crossed an empty orchard at sunrise",
            "beneath dark roofs a silver sparrow refused the storm",
        )
        self.rows = {}
        for index, (split, source) in enumerate(zip(self.files, self.sources), 1):
            self.rows[split] = {
                "id": f"synthetic-{index}", "source_id": f"work-{index}",
                "prompt": f"Examine the original synthetic phrase: {source}",
                "completion": f"The scene numbered {index} permits a tentative reading.",
                "rights_basis": "synthetic_generated", "source_origin": "model_generated_synthetic",
                "permission_to_train": True, "permission_to_publish_adapter": False,
            }
        self.exclusions_file = self.root / "exclusions.json"
        self.exclusions_file.write_text(json.dumps({
            "schema_version": "aeonith.eval_exclusions.v1",
            "excluded_source_ids": ["withheld-separate-source"],
            "excluded_text_sha256": [fingerprints_for_text("another separate unseen fable")
                                     ["text_sha256"]],
            "excluded_5gram_sha256": [],
        }), encoding="utf-8")
        self.write_manifest()
        self.approval = {
            "schema_version": "aeonith.corpus_audit_synthetic_approval.v1",
            "corpus_fingerprint_sha256": inspect(self.manifest_file)["corpus_fingerprint_sha256"],
            "candidate_sha256": self.candidate_sha,
            "status": "APPROVED_MODEL_GENERATED_PRIVATE_TRAINING",
            "permission_to_train": True,
            "operator_decision": {
                "identity": "Fixture Operator",
                "decision": "approve_exact_model_generated_private_training",
                "attested_at_utc": "2026-11-03T12:00:00Z",
                "corpus_fingerprint_sha256": inspect(self.manifest_file)["corpus_fingerprint_sha256"],
            },
        }
        self.write_approval()

    def write_manifest(self) -> None:
        for split, path in self.files.items():
            path.write_text(json.dumps(self.rows[split]) + "\n", encoding="utf-8")
        self.manifest = {
            "schema_version": "aeonith.corpus_audit_manifest.v1",
            "candidate_sha256": self.candidate_sha,
            "splits": {split: {"path": path.name,
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for split, path in self.files.items()},
            "exclusions": {"path": self.exclusions_file.name,
                           "sha256": hashlib.sha256(self.exclusions_file.read_bytes()).hexdigest()},
            "sources": [{
                "source_id": self.rows[split]["source_id"], "source_text": self.sources[index],
                "rights_basis": "synthetic_generated", "source_origin": "model_generated_synthetic",
                "source_generator": "ChatGPT", "source_candidate_sha256": self.candidate_sha,
                "provenance_reference": f"synthetic candidate {self.candidate_sha}, example {index + 1}",
                "permission_to_train": True, "editorial_accepted": False,
            } for index, split in enumerate(self.files)],
        }
        self.manifest_file.write_text(json.dumps(self.manifest), encoding="utf-8")

    def write_approval(self) -> None:
        self.approval_file.write_text(json.dumps(self.approval), encoding="utf-8")

    def test_synthetic_audit_approval_has_no_fake_editor_or_rights_holder(self) -> None:
        receipt = check_approvals(self.manifest_file, self.approval_file)
        self.assertEqual(receipt["approval_mode"], "operator_approved_model_generated_private_only")
        self.assertFalse(receipt["independent_editorial_review_claimed"])
        self.assertFalse(receipt["adapter_publication_authorized"])
        self.assertFalse(receipt["independent_rights_authentication"])

    def test_audit_rejects_missing_provenance_or_mismatched_candidate_digest(self) -> None:
        self.manifest["sources"][0].pop("source_generator")
        self.manifest_file.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(AuditAdmissionError):
            inspect(self.manifest_file)
        self.write_manifest()
        self.manifest["sources"][0]["source_candidate_sha256"] = "1" * 64
        self.manifest_file.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(AuditAdmissionError):
            inspect(self.manifest_file)

    def test_audit_rejects_stale_operator_approval(self) -> None:
        self.approval["operator_decision"]["corpus_fingerprint_sha256"] = "0" * 64
        self.write_approval()
        with self.assertRaises(AuditAdmissionError):
            check_approvals(self.manifest_file, self.approval_file)

    def test_synthetic_sources_cannot_use_four_fake_human_approvers(self) -> None:
        fingerprint = inspect(self.manifest_file)["corpus_fingerprint_sha256"]
        self.approval = {
            "schema_version": "aeonith.corpus_audit_approval.v1",
            "corpus_fingerprint_sha256": fingerprint,
            "status": "APPROVED_PRIVATE_LOCAL_TRAINING", "permission_to_train": True,
        }
        for role, decision in (("rights_holder", "approve_rights"),
                               ("corpus_owner", "approve_corpus"),
                               ("data_steward", "approve_data_use"),
                               ("editorial_reviewer", "approve_editorial_quality")):
            self.approval[role] = {
                "identity": f"Fake Human {role}", "decision": decision,
                "attested_at_utc": "2026-11-03T12:00:00Z",
                "corpus_fingerprint_sha256": fingerprint,
            }
        self.write_approval()
        with self.assertRaises(AuditAdmissionError):
            check_approvals(self.manifest_file, self.approval_file)

    def test_audit_rejects_mixed_synthetic_and_non_synthetic_sources(self) -> None:
        self.rows["holdout"]["rights_basis"] = "public_domain"
        self.rows["holdout"].pop("source_origin")
        self.manifest["sources"][2] = {
            "source_id": "work-3", "source_text": self.sources[2],
            "rights_basis": "public_domain", "provenance_reference": "test unrelated domain",
            "rights_claimant": "Unrelated Domain", "permission_to_train": True,
            "editorial_accepted": True,
        }
        for split, path in self.files.items():
            path.write_text(json.dumps(self.rows[split]) + "\n")
            self.manifest["splits"][split]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest_file.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(AuditAdmissionError):
            inspect(self.manifest_file)


if __name__ == "__main__":
    unittest.main()
