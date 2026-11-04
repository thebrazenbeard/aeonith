"""Prepare a private, *unapproved* audit manifest from exact admitted synthetic bytes.

This is a convenience bridge between the independently approved candidate
export and the separate corpus audit. It does not make an approval decision,
create a corpus admission receipt, train a model, or authenticate an operator.
Only an already-present, independently supplied exclusion file is accepted.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from aeonith.private_output import (
    PrivateOutputError,
    create_private_directory,
)
from .admit_candidates import (
    AdmissionError as CandidateAdmissionError,
    _admitted_lens_coverage,
    _private_path,
    _read,
    _validated_splits,
)
from .corpus import SPLITS
from .corpus_admission import (
    AdmissionError as AuditAdmissionError,
    _excluded,
    _private_file,
    _read_metadata,
    inspect,
)


class AuditDraftError(ValueError):
    """Input is not an exact, approved-private synthetic split export."""


def _serialized(rows: list[dict]) -> bytes:
    return ("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                               allow_nan=False) + "\n" for row in rows)).encode("utf-8")


def _verified_inputs(candidate_path: Path, approval_path: Path,
                     admitted_dir: Path, exclusion_path: Path) -> tuple[dict, dict, dict, str]:
    candidate_file = _private_path(candidate_path, exists=True, label="candidate")
    approval_file = _private_path(approval_path, exists=True, label="approval")
    if _private_path(admitted_dir / "admission_receipt.json", exists=True,
                     label="admission receipt").parent != admitted_dir.absolute():
        raise AuditDraftError("admission directory identity is inconsistent")
    if not isinstance(admitted_dir, Path) or not admitted_dir.is_dir():
        raise AuditDraftError("admitted split directory is unavailable")

    candidate, candidate_sha = _read(candidate_file, "candidate")
    approval, approval_sha = _read(approval_file, "approval")
    if approval.get("schema_version") != "aeonith.candidate_synthetic_admission.v2":
        raise AuditDraftError("exact per-record synthetic v2 decisions are required")
    rows, mode = _validated_splits(candidate, approval, candidate_sha)
    if mode != "operator_approved_model_generated_private_only":
        raise AuditDraftError("this preparer accepts synthetic private admission only")
    receipt, _ = _read(admitted_dir / "admission_receipt.json", "admission receipt")
    observed_coverage = _admitted_lens_coverage(candidate, rows)
    required_receipt = {
        "schema_version": "aeonith.candidate_admission_receipt.v1",
        "status": "admitted_private_only_not_trained",
        "approval_mode": mode,
        "candidate_sha256": candidate_sha,
        "approval_manifest_sha256": approval_sha,
        "split_counts": {split: len(rows[split]) for split in SPLITS},
        "record_disposition_counts": dict(sorted(Counter(
            item["disposition"] for item in approval["records"]).items())),
        "lenses_by_split": observed_coverage,
        "model_trained": False,
        "blind_holdout_qualified": False,
        "adapter_publication_record_permissions_complete": False,
    }
    if any(receipt.get(key) != value for key, value in required_receipt.items()):
        raise AuditDraftError("admission receipt is stale or inconsistent with exact decisions")
    digests: dict[str, dict[str, str]] = {}
    for split in SPLITS:
        path = _private_path(admitted_dir / f"{split}.jsonl", exists=True, label="admitted split")
        expected = _serialized(rows[split])
        if path.read_bytes() != expected:
            raise AuditDraftError("admitted split bytes differ from exact candidate decisions")
        sha = hashlib.sha256(expected).hexdigest()
        if receipt.get("split_files", {}).get(split) != {"sha256": sha, "bytes": len(expected)}:
            raise AuditDraftError("admission split receipt mismatches exact exported bytes")
        digests[split] = {"path": str(path), "sha256": sha}

    withheld_path = _private_file(str(exclusion_path), Path.cwd())
    exclusion_data, exclusion_sha = _read_metadata(withheld_path)
    _excluded(exclusion_data)  # A genuinely separate, nonempty exclusion is mandatory.
    return candidate, rows, {
        "schema_version": "aeonith.corpus_audit_manifest.v1",
        "candidate_sha256": candidate_sha,
        "splits": digests,
        "exclusions": {"path": str(withheld_path), "sha256": exclusion_sha},
        "sources": [],
    }, candidate_sha


def prepare(candidate_path: str | Path, approval_path: str | Path,
            admitted_dir: str | Path, exclusions_path: str | Path,
            output_dir: str | Path) -> dict[str, Any]:
    """Create one new private proposed manifest and return text-free audit data.

    The new directory is not an approval. An inspect failure retains a private
    `audit-inspect-pending.json` for diagnosis, with no promotable manifest.
    """
    candidate_path, approval_path = Path(candidate_path), Path(approval_path)
    admitted_dir, exclusions_path = Path(admitted_dir).absolute(), Path(exclusions_path)
    output_path = _private_path(Path(output_dir), exists=False, label="audit draft output")
    if not output_path.parent.is_dir():
        raise AuditDraftError("audit draft parent directory must already exist")
    candidate, admitted_rows, manifest, candidate_sha = _verified_inputs(
        candidate_path, approval_path, admitted_dir, exclusions_path)

    accepted_ids = {row["id"] for split in SPLITS for row in admitted_rows[split]}
    sources = []
    for candidate_row in candidate["examples"]:
        if candidate_row["id"] not in accepted_ids:
            continue  # Rejected/excluded proposals must never become source attestations.
        sources.append({
            "source_id": candidate_row["source_id"],
            "source_text": candidate_row["passage"],
            "rights_basis": "synthetic_generated",
            "provenance_reference": f"exact synthetic candidate sha256:{candidate_sha}",
            "source_origin": "model_generated_synthetic",
            "source_generator": candidate["generator_provenance"]["generator"],
            "source_candidate_sha256": candidate_sha,
            "permission_to_train": True,
            "editorial_accepted": False,
        })
    if len(sources) != len(accepted_ids):
        raise AuditDraftError("admitted source provenance coverage mismatch")
    manifest["sources"] = sorted(sources, key=lambda item: item["source_id"])
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False) + "\n"
    exact_manifest_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    try:
        with create_private_directory(output_path) as private:
            # The only file present on inspection failure has a deliberately
            # non-promotable name. No cleanup/rename/unlink/rmdir is necessary,
            # including when a same-UID process substitutes the parent path.
            private.write_text("audit-inspect-pending.json", payload)
            report = inspect(output_path / "audit-inspect-pending.json")
            if report.get("synthetic_candidate_sha256") != candidate_sha:
                raise AuditDraftError("audit candidate fingerprint did not survive inspection")
            if report.get("manifest_sha256") != exact_manifest_sha:
                raise AuditDraftError("audit inspector did not inspect the exact staged manifest")
            directory_fd = private._directory_fd
            if directory_fd is None:
                raise AuditDraftError("private draft directory descriptor is unavailable")
            # Hard-link into the same pinned private directory, using kernel
            # exclusive new-name semantics. Unlike rename, os.link refuses to
            # overwrite a concurrently created destination. The staged name
            # persists as recoverable evidence and does not copy private bytes.
            try:
                os.link("audit-inspect-pending.json", "audit-manifest.json",
                        src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                        follow_symlinks=False)
                os.fsync(directory_fd)
            except OSError as exc:
                raise AuditDraftError("private audit draft publication refused") from exc
    except (PrivateOutputError, FileExistsError) as exc:
        raise AuditDraftError("qualified private audit draft destination unavailable") from exc
    return {**report, "draft_not_approved_or_trained": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a private synthetic corpus audit proposal; NEVER approves or trains")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--admitted-dir", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="new PRIVATE directory, not an existing checkout")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.candidates, args.approval, args.admitted_dir,
                                 args.exclusions, args.output), sort_keys=True))
        return 0
    except (AuditDraftError, CandidateAdmissionError, AuditAdmissionError,
            PrivateOutputError, OSError, ValueError):
        # OS errors may embed the private manuscript/manifest path; do not
        # propagate even supposedly useful details to a console or log.
        print("Synthetic audit proposal refused: private inputs or custody did not qualify",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
