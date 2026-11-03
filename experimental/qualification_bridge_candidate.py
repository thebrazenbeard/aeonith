"""Read-only preflight for the experimental Qwen3.5 CPU-LoRA bridge.

There is no executable training authority in this module. In particular, a
JSON receipt, a caller's flags or a successful corpus/byte check MUST NOT be
used to bypass ``training.cpu_step_candidate``'s unconditional runtime gate.
The purpose is to inspect already-existing admission/base evidence without
constructing an optimizer, opening output artifacts or loading weights.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from training.corpus import CorpusError
from training.train_lora import inspect_admitted_plan, verify_declared_base_checkpoint


_REMAINING_GATES = (
    "independent_upstream_origin_authentication",
    "host_owned_immutable_checkpoint_loader_custody",
    "pinned_immutable_training_input_and_holdout_custody",
    "host_owned_cpu_ram_lease_and_revoke",
    "runtime_process_identity_and_framework_io_qualification",
    "end_to_end_private_adapter_output_and_fresh_reload",
)


def inspect_cpu_pilot_readiness(
    *,
    plan: str | Path | None = None,
    audit_manifest: str | Path | None = None,
    approval: str | Path | None = None,
    admission_receipt: str | Path | None = None,
    expected_base_manifest: str | Path | None = None,
) -> dict[str, Any]:
    """Return an explicitly non-authorizing, text-free readiness report.

    A verified admission means that exact *operator attestation bytes* match;
    it is not an independent rights or human-identity determination. Likewise
    a matched local base is not authenticated publisher provenance and is not
    evidence of immutable bytes at future model-loader invocation.
    """
    requested = {
        "plan": plan,
        "audit_manifest": audit_manifest,
        "approval": approval,
        "admission_receipt": admission_receipt,
        "expected_base_manifest": expected_base_manifest,
    }
    # Refuse partial arguments before resolving paths or touching any corpus.
    complete = all(item is not None for item in requested.values())
    report: dict[str, Any] = {
        "schema_version": "aeonith.cpu_pilot_bridge_preflight.v1",
        "status": "NO_OPTIMIZER_AUTHORITY",
        "actual_optimizer_steps": 0,
        "trained_adapter_created": False,
        "operator_attested_exact_corpus_admission_rechecked": False,
        "local_base_bytes_matched_expected_manifest": False,
        "publisher_origin_authenticated": False,
        "protected_training_input_qualified": False,
        "host_owned_cpu_lease_qualified": False,
        "model_loader_custody_qualified": False,
        "private_output_and_reload_qualified": False,
        "missing_qualification": list(_REMAINING_GATES),
    }
    if not complete:
        report["preflight"] = (
            "missing_evidence" if not any(item is not None for item in requested.values())
            else "partial_evidence_refused"
        )
        return report

    try:
        preflight, _dataset, _admitted = inspect_admitted_plan(
            plan, audit_manifest, approval, admission_receipt
        )
        # No data or private path is emitted; the only bound split claims are
        # counts and hashes already computed by the source preflight.
        report["operator_attested_exact_corpus_admission_rechecked"] = True
        report["split_counts"] = preflight["split_counts"]
        report["split_sha256"] = {
            split: preflight["split_files"][split]["sha256"]
            for split in ("train", "validation", "holdout")
        }
        base = verify_declared_base_checkpoint(plan, preflight, expected_base_manifest)
        report["local_base_bytes_matched_expected_manifest"] = True
        report["base_file_count"] = base["files_verified"]
        report["preflight"] = "operator_claims_and_local_hashes_match_not_runtime_qualified"
    except (CorpusError, OSError, ValueError, KeyError, TypeError):
        # Do not echo errors: malformed local JSON and paths can include
        # passages, private directory names, or arbitrary user-supplied text.
        report["preflight"] = "evidence_refused"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Aeonith CPU-LoRA qualification diagnosis; NEVER trains."
    )
    parser.add_argument("--plan")
    parser.add_argument("--audit-manifest")
    parser.add_argument("--approval")
    parser.add_argument("--admission-receipt")
    parser.add_argument("--expected-base-manifest")
    args = parser.parse_args(argv)
    report = inspect_cpu_pilot_readiness(
        plan=args.plan,
        audit_manifest=args.audit_manifest,
        approval=args.approval,
        admission_receipt=args.admission_receipt,
        expected_base_manifest=args.expected_base_manifest,
    )
    print(json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":")))
    # Return nonzero even when the read-only evidence checks pass. A green
    # process exit must never be mistaken for permission to train.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
