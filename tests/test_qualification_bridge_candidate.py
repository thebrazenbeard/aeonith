"""No optimizer or private content must escape the read-only bridge."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from unittest import TestCase
from unittest.mock import patch

from experimental.qualification_bridge_candidate import (
    inspect_cpu_pilot_readiness,
    main,
)
from training.cpu_step_candidate import CandidateStepError, experimental_loaded_cpu_lora_step


ALL_PATHS = {
    "plan": "/PRIVATE/writing/plan.json",
    "audit_manifest": "/PRIVATE/writing/audit.json",
    "approval": "/PRIVATE/writing/approval.json",
    "admission_receipt": "/PRIVATE/writing/admission.json",
    "expected_base_manifest": "/PRIVATE/writing/base.json",
}


class CPUBridgeReadinessTests(TestCase):
    def test_missing_evidence_does_no_private_io(self):
        with patch("experimental.qualification_bridge_candidate.inspect_admitted_plan") as inspect:
            report = inspect_cpu_pilot_readiness()
        inspect.assert_not_called()
        self.assertEqual(report["status"], "NO_OPTIMIZER_AUTHORITY")
        self.assertEqual(report["preflight"], "missing_evidence")
        self.assertEqual(report["actual_optimizer_steps"], 0)

    def test_partial_evidence_is_refused_before_io(self):
        with patch("experimental.qualification_bridge_candidate.inspect_admitted_plan") as inspect:
            report = inspect_cpu_pilot_readiness(plan=ALL_PATHS["plan"])
        inspect.assert_not_called()
        self.assertEqual(report["preflight"], "partial_evidence_refused")
        self.assertFalse(report["trained_adapter_created"])

    def test_admitted_source_and_matching_local_base_still_cannot_train(self):
        preflight = {
            "split_counts": {"train": 4, "validation": 2, "holdout": 2},
            "split_files": {
                split: {"sha256": "a" * 64}
                for split in ("train", "validation", "holdout")
            },
        }
        # Even a fully plausible operator-attested receipt and local bytes
        # match cannot establish the kernel/process/rights runtime leases.
        with patch(
            "experimental.qualification_bridge_candidate.inspect_admitted_plan",
            return_value=(preflight, {"train": [{"prompt": "secret text"}]}, {"status": "approved"}),
        ) as inspect, patch(
            "experimental.qualification_bridge_candidate.verify_declared_base_checkpoint",
            return_value={"files_verified": 10},
        ) as base:
            report = inspect_cpu_pilot_readiness(**ALL_PATHS)
        inspect.assert_called_once()
        base.assert_called_once()
        self.assertEqual(report["preflight"], "operator_claims_and_local_hashes_match_not_runtime_qualified")
        self.assertTrue(report["operator_attested_exact_corpus_admission_rechecked"])
        self.assertTrue(report["local_base_bytes_matched_expected_manifest"])
        self.assertFalse(report["publisher_origin_authenticated"])
        self.assertFalse(report["model_loader_custody_qualified"])
        self.assertFalse(report["host_owned_cpu_lease_qualified"])
        self.assertEqual(report["actual_optimizer_steps"], 0)
        self.assertNotIn("secret text", json.dumps(report))
        self.assertNotIn("/PRIVATE", json.dumps(report))

    def test_corpus_rejection_refuses_base_verification_and_sanitizes_errors(self):
        with patch(
            "experimental.qualification_bridge_candidate.inspect_admitted_plan",
            side_effect=ValueError("private/word/that/must/not/appear"),
        ), patch("experimental.qualification_bridge_candidate.verify_declared_base_checkpoint") as base:
            report = inspect_cpu_pilot_readiness(**ALL_PATHS)
        base.assert_not_called()
        self.assertEqual(report["preflight"], "evidence_refused")
        self.assertNotIn("private/word", json.dumps(report))

    def test_base_failure_cannot_leak_text_or_claim_hash_success(self):
        preflight = {"split_counts": {"train": 1}, "split_files": {}}
        with patch(
            "experimental.qualification_bridge_candidate.inspect_admitted_plan",
            return_value=(preflight, {}, {}),
        ), patch("experimental.qualification_bridge_candidate.verify_declared_base_checkpoint") as base:
            report = inspect_cpu_pilot_readiness(**ALL_PATHS)
        base.assert_not_called()
        self.assertFalse(report["local_base_bytes_matched_expected_manifest"])
        self.assertEqual(report["preflight"], "evidence_refused")

    def test_readiness_report_cannot_override_original_optimizer_gate(self):
        with patch(
            "experimental.qualification_bridge_candidate.inspect_admitted_plan",
            return_value=(
                {"split_counts": {"train": 1, "validation": 1, "holdout": 1},
                 "split_files": {split: {"sha256": "c" * 64}
                                 for split in ("train", "validation", "holdout")}},
                {}, {},
            ),
        ), patch(
            "experimental.qualification_bridge_candidate.verify_declared_base_checkpoint",
            return_value={"files_verified": 10},
        ):
            report = inspect_cpu_pilot_readiness(**ALL_PATHS)
        # Even if a caller presents every "true" field in a JSON object, the
        # actual direct primitive refuses before inspecting model/broker.
        self.assertTrue(report["local_base_bytes_matched_expected_manifest"])
        with self.assertRaisesRegex(CandidateStepError, "not qualified"):
            experimental_loaded_cpu_lora_step(None, None, (), (), None)

    def test_cli_no_execute_flag_and_even_preflight_exit_is_nonzero(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = main([])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(buffer.getvalue())["status"], "NO_OPTIMIZER_AUTHORITY")
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(["--execute"])
        self.assertEqual(exc.exception.code, 2)
