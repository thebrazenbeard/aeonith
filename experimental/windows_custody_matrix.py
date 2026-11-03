"""Opt-in Windows *counterexample* matrix for disposable training-output paths.

This composes the existing reparse and handle-root experiments with a
synthetic interrupted-exclusive-create test. It does not qualify a private
writer, durable on-disk recovery, effective DACLs, or a Trainer output path.

All native effects are inside new TemporaryDirectory instances. The child
interruption deliberately leaves only an inert test marker; the parent
verifies the file survives and exclusive retry refuses to clobber it.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from . import windows_private_output_probe, windows_rootdir_probe


STATUS = "NOT_QUALIFIED"
_CHILD_EXIT = 39
_TEST_BYTES = b"AEONITH_DISPOSABLE_INTERRUPTED_CREATE\n"


def _crash_child_code() -> str:
    # No arbitrary target is accepted from the public CLI. The only path
    # supplied to this isolated interpreter is created by the parent below.
    return (
        "import os,sys\n"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\n"
        "os.write(fd,b'AEONITH_DISPOSABLE_INTERRUPTED_CREATE\\n')\n"
        "os.fsync(fd)\n"
        "os._exit(39)\n"
    )


def run_disposable_interruption_probe() -> dict[str, Any]:
    """Exercise crash residue and exclusive retry, never a real output path."""
    if os.name != "nt":
        return {"execution": "NOT_RUN_NON_WINDOWS", "qualification_status": STATUS}
    return _run_disposable_interruption()


def _run_disposable_interruption() -> dict[str, Any]:
    """Cross-platform mechanics, called by Windows native matrix only."""
    try:
        with tempfile.TemporaryDirectory(prefix="aeonith-win-interruption-probe-") as raw:
            root = Path(raw)
            pending = root / "partial-test-marker.bin"
            published = root / "final-training-receipt.json"
            child = subprocess.run(
                [sys.executable, "-I", "-c", _crash_child_code(), str(pending)],
                cwd=str(root), capture_output=True, timeout=8, check=False,
            )
            partial_exists = pending.is_file() and pending.read_bytes() == _TEST_BYTES
            refused = False
            if pending.exists():
                try:
                    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    refused = True
                else:
                    os.close(fd)
            return {
                "execution": "EXECUTED",
                "child_exited_by_design": child.returncode == _CHILD_EXIT,
                "partial_marker_preserved": partial_exists,
                "exclusive_retry_refused_clobber": refused,
                "final_receipt_absent": not published.exists(),
                "qualification_status": STATUS,
                "durable_flush_qualified": False,
            }
    except (OSError, subprocess.TimeoutExpired, ValueError):
        # Never include child stderr, command line, OS path or token content.
        return {"execution": "INCONCLUSIVE", "error_class": "disposable_interruption_unavailable",
                "qualification_status": STATUS}


def summarize_matrix(rooted: dict[str, Any], reparse: dict[str, Any],
                     interruption: dict[str, Any]) -> dict[str, Any]:
    """Report observable counterexamples; never turn favorable probes into GO."""
    falsifiers: list[str] = []
    rooted_cases = rooted.get("cases", []) if isinstance(rooted, dict) else []
    reparse_cases = reparse.get("cases", []) if isinstance(reparse, dict) else []
    for case in rooted_cases:
        if case.get("execution") != "EXECUTED":
            continue
        if case.get("original_directory_handle_identity_preserved") is False:
            falsifiers.append("root_handle_identity_changed")
        if case.get("rooted_create_landed_in_pinned_directory") is False:
            falsifiers.append("relative_create_escaped_pinned_directory")
        if case.get("decoy_marker_created") is True:
            falsifiers.append("relative_create_hit_decoy")
    for case in reparse_cases:
        if case.get("execution") != "EXECUTED":
            continue
        observations = case.get("observations")
        if not isinstance(observations, dict):
            observations = {}
        if case.get("opened_target_identity_after_swap") is True:
            falsifiers.append("path_open_redirected_after_ancestor_swap")
        if observations.get("owner_present") is False:
            falsifiers.append("absent_owner")
        if observations.get("owner_matches_token_user") is False:
            falsifiers.append("noncaller_owner")
        if observations.get("dacl_present") is False:
            falsifiers.append("absent_dacl")
        if observations.get("dacl_is_null") is True:
            falsifiers.append("null_dacl_observed")
        if observations.get("dacl_protected") is False:
            falsifiers.append("inherited_dacl")
        if observations.get("reparse_point_present") is True:
            falsifiers.append("reparse_point_present")
        if observations.get("ancestor_redirect_observed") is True:
            falsifiers.append("ancestor_reparse_traversed")
    if interruption.get("execution") == "EXECUTED":
        if interruption.get("child_exited_by_design") is not True:
            falsifiers.append("interrupted_child_exit_unverified")
        if interruption.get("partial_marker_preserved") is not True:
            falsifiers.append("interrupted_partial_not_preserved")
        if interruption.get("exclusive_retry_refused_clobber") is not True:
            falsifiers.append("exclusive_retry_overwrote_or_missed_partial")
        if interruption.get("final_receipt_absent") is not True:
            falsifiers.append("unexpected_final_receipt_after_interruption")
    # An inconclusive/absent case is UNKNOWN, never a favorable observation.
    return {
        "qualification_status": STATUS,
        "train_or_deploy_authorized": False,
        "native_windows_private_writer_qualified": False,
        "rooted_cases_executed": sum(c.get("execution") == "EXECUTED" for c in rooted_cases),
        "reparse_cases_executed": sum(c.get("execution") == "EXECUTED" for c in reparse_cases),
        "interruption_executed": interruption.get("execution") == "EXECUTED",
        "falsifiers": sorted(set(falsifiers)),
        "material_unknowns": [
            "effective_ACE_rights_and_privileges", "trusted_initial_ancestor_open",
            "same_SID_mutation_after_child_handoff", "atomic_promotion_and_crash_durability",
            "real_Trainer_PEFT_write_integration", "host_owned_runtime_lease",
        ],
    }


def run_disposable_matrix() -> dict[str, Any]:
    if os.name != "nt":
        return {"qualification_status": STATUS, "execution": "NOT_RUN_NON_WINDOWS"}
    rooted = windows_rootdir_probe.run_disposable_rootdir_probes()
    reparse = windows_private_output_probe.run_disposable_windows_probes()
    interruption = run_disposable_interruption_probe()
    return {
        "execution": "EXECUTED_SYNTHETIC_ONLY",
        "qualification_status": STATUS,
        "scope": "isolated_disposable_temp_and_child_process_only",
        "assessment": summarize_matrix(rooted, reparse, interruption),
        "rooted_creation": rooted,
        "reparse_and_acl_observations": reparse,
        "interrupted_exclusive_create": interruption,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-disposable-temp-matrix", action="store_true")
    args = parser.parse_args(argv)
    receipt = (run_disposable_matrix() if args.run_disposable_temp_matrix else
               {"qualification_status": STATUS, "execution": "NOT_RUN_OPT_IN_REQUIRED"})
    print(json.dumps(receipt, sort_keys=True))
    return 2  # Every diagnostic status is NOT_QUALIFIED, never a shell GO.


if __name__ == "__main__":
    raise SystemExit(main())
