"""Offline, fail-closed admission of *privately approved* critique proposals.

Candidate drafting never grants rights. The original multi-party path requires
separate rights, steward and editorial decisions. A distinct opt-in path for
solely owner-authored originals accepts only the owner's explicit declaration;
neither mode cryptographically authenticates the person or rights.
It creates only private JSONL, never model weights, a training plan, or a
publication approval.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from aeonith.private_output import PrivateOutputError, create_private_directory
from evaluation.quality_eval import CANONICAL_LENSES, audit_review
from .corpus import CorpusError, SPLITS, _check_isolation, _check_row


class AdmissionError(ValueError):
    """Candidate corpus has no sufficient explicit local training approval."""


REPO_ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_EXAMPLES = 500
ATTEST_FIELDS = {"identity", "decision", "attested_at_utc", "candidate_sha256"}
RECORD_FIELDS = {"id", "source_id", "rights_basis", "permission_to_train", "editorial_accepted"}
SYNTHETIC_DISPOSITIONS = frozenset({"admit", "reject", "exclude"})
SYNTHETIC_EXCLUSION_REASONS = frozenset({
    "rights_unclear", "quality", "duplicate", "out_of_scope", "other",
})


def _exact(value: Any, required: set[str], optional: set[str], name: str) -> dict:
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
        raise AdmissionError(f"invalid {name} fields")
    return value


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    obj: dict[str, Any] = {}
    for name, value in pairs:
        if name in obj:
            raise AdmissionError("duplicate JSON fields are not permitted")
        obj[name] = value
    return obj


def _no_constants(value: str) -> None:
    raise AdmissionError("non-finite JSON values are forbidden")


def _read(path: Path, description: str) -> tuple[dict, str]:
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_INPUT_BYTES:
        raise AdmissionError(f"missing or oversized {description} file")
    raw = path.read_bytes()
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                             parse_constant=_no_constants)
    except (UnicodeError, ValueError) as exc:
        raise AdmissionError(f"invalid {description} JSON") from exc
    if not isinstance(decoded, dict):
        raise AdmissionError(f"invalid {description} object")
    return decoded, hashlib.sha256(raw).hexdigest()


def _private_path(value: str | Path, *, exists: bool, label: str) -> Path:
    # Preserve the lexical ancestry before resolving anything: resolve() would
    # hide a symlink/reparse parent that can redirect private source material.
    raw_text = os.fspath(value)
    if raw_text.startswith(("//", "\\\\")) or (os.name != "nt" and re.match(r"^[A-Za-z]:", raw_text)):
        raise AdmissionError(f"{label} UNC or device paths are not permitted")
    path = Path(os.path.abspath(Path(value).expanduser()))
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise AdmissionError(f"{label} must not traverse an indirect path")
        try:
            attrs = ancestor.lstat()
        except FileNotFoundError:
            continue
        if (os.name == "nt" and getattr(attrs, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise AdmissionError(f"{label} must not traverse an indirect path")
        marker = ancestor / ".git"
        if marker.is_symlink():
            raise AdmissionError(f"{label} must not traverse an indirect Git marker")
        if marker.is_dir() and (marker / "HEAD").exists():
            raise AdmissionError(f"{label} must be outside the Git checkout (or any other Git checkout)")
        if marker.is_file():
            with marker.open("rb") as stream:
                if stream.read(7) == b"gitdir:":
                    raise AdmissionError(f"{label} must be outside the Git checkout (or any other Git checkout)")
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise AdmissionError(f"{label} must be outside the Git checkout")
    if exists and not path.is_file():
        raise AdmissionError(f"{label} file missing")
    if not exists and path.exists():
        raise AdmissionError("output directory already exists; never overwrite")
    return path


def _attestation(value: Any, role: str, decision: str, digest: str) -> str:
    item = _exact(value, ATTEST_FIELDS, set(), f"{role} attestation")
    identity = item["identity"]
    if (not isinstance(identity, str) or not 2 <= len(identity.strip()) <= 160
            or identity.strip().casefold() in {"unknown", "pending", "todo", "tbd"}):
        raise AdmissionError(f"missing {role} identity")
    if item["decision"] != decision or item["candidate_sha256"] != digest:
        raise AdmissionError(f"{role} attestation does not approve this exact SHA-256")
    when = item["attested_at_utc"]
    if not isinstance(when, str) or not when.endswith("Z"):
        raise AdmissionError(f"invalid {role} attestation time")
    try:
        parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionError(f"invalid {role} attestation time") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise AdmissionError(f"invalid {role} attestation timezone")
    return identity.strip().casefold()


def _candidate_rows(candidate: dict) -> list[dict]:
    _exact(candidate, {"schema_version", "status", "examples"}, {"generator_provenance"}, "candidate corpus")
    if candidate["schema_version"] != "aeonith.candidate_corpus.v1" or candidate["status"] != "REVIEW_PENDING_NOT_TRAINABLE":
        raise AdmissionError("input must be a review-pending candidate proposal")
    rows = candidate["examples"]
    if not isinstance(rows, list) or not 3 <= len(rows) <= MAX_EXAMPLES:
        raise AdmissionError("invalid candidate record count")
    ids: set[str] = set()
    sources: set[str] = set()
    counts: Counter[str] = Counter()
    for row in rows:
        _exact(row, {"id", "source_id", "split", "genre", "lens", "passage", "target", "draft_status"}, set(), "candidate row")
        if (not isinstance(row["id"], str) or not NAME.fullmatch(row["id"])
                or not isinstance(row["source_id"], str) or not NAME.fullmatch(row["source_id"])
                or row["id"] in ids or row["source_id"] in sources):
            raise AdmissionError("duplicate or invalid candidate record/source identifier")
        ids.add(row["id"])
        sources.add(row["source_id"])
        if row["split"] not in SPLITS or row["lens"] not in CANONICAL_LENSES:
            raise AdmissionError("invalid candidate split or lens")
        counts[row["split"]] += 1
        if (row["draft_status"] != "REVIEW_PENDING" or not isinstance(row["passage"], str)
                or not row["passage"].strip() or len(row["passage"]) > 8000):
            raise AdmissionError("invalid draft status or passage")
        if not isinstance(row["genre"], str) or not row["genre"].strip():
            raise AdmissionError("invalid candidate genre")
        target = _exact(row["target"], {"lens_reviews", "synthesis", "challenges", "uncertainties", "assessment"}, set(), "candidate target")
        audit = audit_review({"schema_version": "aeonith.review.v1", "work": {"text": row["passage"]},
                              "lenses": [row["lens"]]},
                             {"schema_version": "aeonith.review.v1", "status": "completed", **target})
        if audit["structural_status"] != "pass":
            raise AdmissionError("candidate target fails the structural quote/lens audit")
    if any(counts[split] < 1 for split in SPLITS):
        raise AdmissionError("train, validation and holdout must all contain distinct works")
    return rows


def _synthetic_provenance(candidate: dict) -> None:
    """Require exact model-generated origin claims, not invented authorship.

    This remains a self-reported claim: source code cannot prove a passage
    was generated without third-party copying. The separate post-generation
    operator approval is required for its exact bytes.
    """
    item = _exact(candidate.get("generator_provenance"),
                  {"origin", "generator", "third_party_text_used",
                   "human_authorship_claimed", "publication_authorized"}, set(),
                  "synthetic generator provenance")
    if (item["origin"] != "model_generated_synthetic"
            or not isinstance(item["generator"], str)
            or not 2 <= len(item["generator"].strip()) <= 160
            or item["third_party_text_used"] is not False
            or item["human_authorship_claimed"] is not False
            or item["publication_authorized"] is not False):
        raise AdmissionError("synthetic pilot must declare model-only generation without human authorship or publication")


def _validated_splits(candidate: dict, approval: dict, digest: str) -> tuple[dict[str, list[dict]], str]:
    schema = approval.get("schema_version")
    if schema == "aeonith.candidate_admission.v1":
        _exact(approval, {"schema_version", "candidate_sha256", "approval_status", "permission_to_train",
                          "rights_holder_decision", "independent_data_steward_decision", "editorial_decision", "records"},
               set(), "approval manifest")
        expected_status = "APPROVED_FOR_PRIVATE_LOCAL_TRAINING"
        mode = "multi_party_private"
    elif schema == "aeonith.candidate_owner_admission.v1":
        _exact(approval, {"schema_version", "candidate_sha256", "approval_status", "permission_to_train",
                          "sole_owner_decision", "records"}, set(), "sole original owner approval manifest")
        expected_status = "APPROVED_SELF_AUTHORED_PRIVATE_LOCAL_TRAINING"
        mode = "sole_original_owner_self_authored"
    elif schema == "aeonith.candidate_synthetic_admission.v1":
        _exact(approval, {"schema_version", "candidate_sha256", "approval_status", "permission_to_train",
                          "operator_decision", "records"}, set(), "synthetic pilot approval manifest")
        expected_status = "APPROVED_MODEL_GENERATED_PRIVATE_LOCAL_TRAINING"
        mode = "operator_approved_model_generated_private_only"
    elif schema == "aeonith.candidate_synthetic_admission.v2":
        # All proposal IDs must have an explicit decision. A rejected or
        # excluded example is never silently admitted to a training split.
        _exact(approval, {"schema_version", "candidate_sha256", "approval_status", "permission_to_train",
                          "operator_decision", "records"}, set(), "synthetic pilot approval manifest")
        expected_status = "APPROVED_MODEL_GENERATED_PRIVATE_LOCAL_TRAINING"
        mode = "operator_approved_model_generated_private_only"
    else:
        raise AdmissionError("unsupported candidate approval schema")
    if approval["candidate_sha256"] != digest or not HEX64.fullmatch(digest):
        raise AdmissionError("approval manifest SHA-256 does not match the candidate file")
    if (approval["approval_status"] != expected_status
            or approval["permission_to_train"] is not True):
        raise AdmissionError("approval manifest does not authorize private local training")
    if mode == "operator_approved_model_generated_private_only":
        _synthetic_provenance(candidate)
        _attestation(approval["operator_decision"], "synthetic pilot operator",
                     "approve_exact_model_generated_private_training", digest)
    elif "generator_provenance" in candidate:
        raise AdmissionError("model-generated candidates cannot use human-authored or third-party approvals")
    owner_identity: str | None = None
    if mode == "multi_party_private":
        identities = [
            _attestation(approval["rights_holder_decision"], "rights-holder", "approve_local_training", digest),
            _attestation(approval["independent_data_steward_decision"], "independent steward", "approve_local_training", digest),
            _attestation(approval["editorial_decision"], "editorial reviewer", "approve_editorial_targets", digest),
        ]
        if len(set(identities)) != len(identities):
            raise AdmissionError("rights-holder, steward and editor identities must be distinct")
    elif mode == "sole_original_owner_self_authored":
        owner_identity = _attestation(
            approval["sole_owner_decision"], "sole original owner",
            "approve_sole_owner_original_private_training", digest,
        )
    rows = _candidate_rows(candidate)
    decisions = approval["records"]
    if not isinstance(decisions, list) or len(decisions) != len(rows):
        raise AdmissionError("record-level decisions do not cover the candidate corpus")
    by_id: dict[str, dict] = {}
    for entry in decisions:
        if owner_identity is not None and isinstance(entry, dict) and "license_id" in entry:
            raise AdmissionError("sole original owner path cannot include licensed records")
        synthetic_v2 = schema == "aeonith.candidate_synthetic_admission.v2"
        optionals = ({"permission_to_publish_adapter", "license_id"} if owner_identity is None
                     else {"permission_to_publish_adapter", "rights_claimant"})
        required = RECORD_FIELDS if owner_identity is None else RECORD_FIELDS | {"rights_claimant"}
        if synthetic_v2:
            required = required | {"disposition"}
            optionals = (optionals - {"license_id"}) | {"reason_code"}
        _exact(entry, required, optionals - required, "record-level approval")
        identifier = entry["id"]
        if not isinstance(identifier, str) or identifier in by_id:
            raise AdmissionError("duplicate or invalid approval record")
        if synthetic_v2:
            disposition = entry["disposition"]
            if not isinstance(disposition, str) or disposition not in SYNTHETIC_DISPOSITIONS:
                raise AdmissionError("invalid synthetic record disposition")
            if disposition == "admit":
                if "reason_code" in entry:
                    raise AdmissionError("admitted synthetic record cannot specify an exclusion reason")
                if entry["permission_to_train"] is not True:
                    raise AdmissionError("admitted synthetic record needs explicit training consent")
            else:
                reason = entry.get("reason_code")
                if (entry["permission_to_train"] is not False
                        or not isinstance(reason, str)
                        or reason not in SYNTHETIC_EXCLUSION_REASONS):
                    raise AdmissionError("rejected/excluded synthetic record needs denied consent and reason code")
        elif entry["permission_to_train"] is not True:
            raise AdmissionError("every record requires training consent")
        if mode == "operator_approved_model_generated_private_only":
            if (entry["editorial_accepted"] is not False
                    or entry["rights_basis"] != "synthetic_generated"
                    or entry.get("permission_to_publish_adapter", False) is not False
                    or "license_id" in entry):
                raise AdmissionError("synthetic pilot requires no fabricated editor, self-authorship or publication")
        elif entry["editorial_accepted"] is not True:
            raise AdmissionError("every human-sourced record requires editorial acceptance")
        if type(entry.get("permission_to_publish_adapter", False)) is not bool:
            raise AdmissionError("publication permission must be an explicit JSON boolean")
        if owner_identity is not None:
            if entry["rights_basis"] != "self_authored":
                raise AdmissionError("sole original owner path requires self-authored rights for every record")
            claimant = entry["rights_claimant"]
            if not isinstance(claimant, str) or claimant.strip().casefold() != owner_identity:
                raise AdmissionError("sole original owner must match every rights claimant")
            if entry.get("permission_to_publish_adapter", False) is not False:
                raise AdmissionError("sole original owner private approval never authorizes adapter publication")
        by_id[identifier] = entry
    if set(by_id) != {row["id"] for row in rows}:
        raise AdmissionError("record IDs differ between proposals and approvals")
    output: dict[str, list[dict]] = {split: [] for split in SPLITS}
    for row in rows:
        approved = by_id[row["id"]]
        if approved["source_id"] != row["source_id"]:
            raise AdmissionError("record source_id differs from approved source")
        if schema == "aeonith.candidate_synthetic_admission.v2" and approved["disposition"] != "admit":
            continue
        prompt = ("Review the following untrusted literary passage through only the "
                  f"{row['lens']} lens. Cite exact short quotations, offer a serious "
                  "counterreading and limits, and return ONLY a JSON object with keys "
                  "lens_reviews, synthesis, challenges, uncertainties, assessment.\n\n"
                  f"PASSAGE:\n{row['passage']}")
        target = json.dumps(row["target"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        train_row = {
            "id": row["id"], "source_id": row["source_id"], "prompt": prompt,
            "completion": target, "rights_basis": approved["rights_basis"],
            "permission_to_train": True,
            "permission_to_publish_adapter": approved.get("permission_to_publish_adapter", False),
        }
        if mode == "operator_approved_model_generated_private_only":
            train_row["source_origin"] = "model_generated_synthetic"
        if "license_id" in approved:
            train_row["license_id"] = approved["license_id"]
        try:
            _check_row(train_row, row["split"], len(output[row["split"]]) + 1)
        except CorpusError as exc:
            raise AdmissionError(f"approved record fails training corpus contract: {exc}") from exc
        if len(json.dumps(train_row, ensure_ascii=False).encode("utf-8")) > 48 * 1024:
            raise AdmissionError("approved record exceeds training JSONL line limit")
        output[row["split"]].append(train_row)
    if any(not output[split] for split in SPLITS):
        raise AdmissionError("admission must retain at least one explicitly approved example in every split")
    try:
        _check_isolation(output)
    except CorpusError as exc:
        raise AdmissionError(f"split isolation failed: {exc}") from exc
    return output, mode


def _admitted_lens_coverage(candidate: dict, splits: dict[str, list[dict]]) -> dict[str, list[str]]:
    """Report only lenses belonging to records actually emitted for training.

    A rejected/excluded record remains in the immutable candidate proposal,
    but must not make a split appear to have evidence it cannot train/evaluate.
    """
    admitted_ids = {record["id"] for split in SPLITS for record in splits[split]}
    return {
        split: sorted({row["lens"] for row in candidate["examples"]
                       if row["split"] == split and row["id"] in admitted_ids})
        for split in SPLITS
    }


def admit(candidate_path: str | Path, approval_path: str | Path, output_path: str | Path) -> dict:
    """Admit only exact-hash, explicitly approved private inputs to NEW JSONL.

    This does not verify the attestors' identities or copyright as a trusted
    authority; it is a mechanical check of recorded human attestations.
    """
    candidate_file = _private_path(candidate_path, exists=True, label="candidate")
    approval_file = _private_path(approval_path, exists=True, label="approval manifest")
    output = _private_path(output_path, exists=False, label="output")
    if not output.parent.is_dir():
        raise AdmissionError("output parent must already exist")
    candidate, candidate_sha256 = _read(candidate_file, "candidate")
    approval, approval_sha256 = _read(approval_file, "approval manifest")
    splits, mode = _validated_splits(candidate, approval, candidate_sha256)
    lens_coverage = _admitted_lens_coverage(candidate, splits)
    serial = {
        split: "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
                       for row in splits[split])
        for split in SPLITS
    }
    receipt = {
        "schema_version": "aeonith.candidate_admission_receipt.v1",
        "status": "admitted_private_only_not_trained",
        "approval_mode": mode,
        "candidate_sha256": candidate_sha256,
        "approval_manifest_sha256": approval_sha256,
        "split_counts": {split: len(splits[split]) for split in SPLITS},
        "record_disposition_counts": dict(sorted(Counter(
            item.get("disposition", "admit") for item in approval["records"]
        ).items())),
        "lenses_by_split": lens_coverage,
        "train_lenses_missing": sorted(set(CANONICAL_LENSES) - set(lens_coverage["train"])),
        "split_files": {split: {"sha256": hashlib.sha256(serial[split].encode("utf-8")).hexdigest(),
                                "bytes": len(serial[split].encode("utf-8"))} for split in SPLITS},
        "adapter_publication_record_permissions_complete": all(
            row["permission_to_publish_adapter"] for split in SPLITS for row in splits[split]
        ),
        "attestation_verification": "operator_attested_not_cryptographically_verified",
        "attestation_issuer_identities_independently_authenticated": False,
        "independent_editorial_review_claimed": mode == "multi_party_private",
        "synthetic_generation_claim_operator_attested_only": mode == "operator_approved_model_generated_private_only",
        "editorial_semantic_quality_independently_verified_by_program": False,
        "blind_holdout_qualified": False,
        "model_trained": False,
        "limitations": [
            "attestation names and permissions are self-reported, not cryptographically authenticated",
            "proposal holdout may be visible and cannot qualify blind model skill",
            "separate consent and artifact review remain required before publication",
        ],
    }
    # POSIX: exclusively create a private directory and write via pinned FDs,
    # refusing symlink ancestry, unsafe parent permissions and Git checkouts.
    # Windows: fail closed until a verified DACL/handle-based writer exists.
    # All validations run before creating anything; an interrupted write leaves
    # an incomplete directory for manual review, never an automatic overwrite.
    try:
        with create_private_directory(output) as private:
            for split in SPLITS:
                private.write_text(f"{split}.jsonl", serial[split])
            private.write_text("admission_receipt.json",
                               json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    except PrivateOutputError as exc:
        raise AdmissionError(str(exc)) from exc
    except FileExistsError as exc:
        raise AdmissionError("output directory already exists; never overwrite") from exc
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline/private approved critique-candidate export; does not train or publish")
    parser.add_argument("--candidates", type=Path, required=True, help="private candidates.json outside checkout")
    parser.add_argument("--approval", type=Path, required=True, help="private exact-hash approval manifest outside checkout")
    parser.add_argument("--output", type=Path, required=True, help="nonexistent private output directory outside checkout")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(admit(args.candidates, args.approval, args.output), sort_keys=True))
        return 0
    except (AdmissionError, OSError, ValueError) as exc:
        print(f"Candidate admission refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
