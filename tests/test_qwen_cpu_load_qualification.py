"""Source-only tests: never import a checkpoint or instantiate a Qwen model."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

from experimental import qwen_cpu_load_qualification as subject


class CgroupReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.unit = "aeonith-modelcheck-123-0123456789abcdef01234567.scope"
        self.scope = self.root / "user.slice" / self.unit
        self.scope.mkdir(parents=True)
        self.membership = self.root / "membership"
        self.membership.write_text(f"0::/user.slice/{self.unit}\n", encoding="ascii")
        values = {
            "memory.max": str(subject._MEMORY_MAX),
            "memory.high": str(subject._MEMORY_HIGH),
            "memory.swap.max": "0", "cpu.max": "50000 100000", "pids.max": "64",
        }
        for name, content in values.items():
            (self.scope / name).write_text(content, encoding="ascii")

    def test_exact_cgroup_membership_and_limits(self):
        root, values = subject._read_own_scope(self.unit, root=self.root, membership=self.membership)
        self.assertEqual(root, self.scope)
        self.assertEqual(values["cpu_max"], "50000 100000")

    def test_unknown_or_mismatched_limits_fail_closed(self):
        for filename, bad in (("memory.max", "max"), ("memory.swap.max", "1024"),
                              ("cpu.max", "40000 100000"), ("pids.max", "max")):
            with self.subTest(filename=filename):
                path = self.scope / filename
                old = path.read_text(encoding="ascii")
                path.write_text(bad, encoding="ascii")
                with self.assertRaises(subject.ModelLoadQualificationError):
                    subject._read_own_scope(self.unit, root=self.root, membership=self.membership)
                path.write_text(old, encoding="ascii")

    def test_wrong_unit_and_windows_shaped_membership_fail(self):
        for membership in ("0::/user.slice/other.scope\n",
                           f"0::C:\\user.slice\\{self.unit}\n", "1::/user.slice\n"):
            with self.subTest(membership=membership):
                self.membership.write_text(membership, encoding="ascii")
                with self.assertRaises(subject.ModelLoadQualificationError):
                    subject._read_own_scope(self.unit, root=self.root, membership=self.membership)


class LauncherTests(unittest.TestCase):
    def test_without_execute_never_starts_scope(self):
        with patch.object(subject, "_run_parent", side_effect=AssertionError("would have run")):
            self.assertEqual(subject.main(["--base-dir", "/invalid"]), 2)

    def _run_with(self, result):
        with (patch.object(subject, "_controllers_available"),
              patch.object(subject, "_private_base"),
              patch.object(subject, "_available_memory_mib", return_value=7000),
              patch.object(subject, "_assert_unloaded") as unload,
              patch.object(subject, "_stop_owned_unit") as stop,
              patch.object(subject.subprocess, "run", return_value=result) as run):
            try:
                return subject._run_parent("/home/vera/private-base"), run, stop, unload
            except subject.ModelLoadQualificationError:
                return None, run, stop, unload

    def test_only_one_direct_argv_scope_with_fixed_caps(self):
        # Unit name is random at runtime; stub only the nonce to make receipt exact.
        unit = f"aeonith-modelcheck-{subject.os.getpid()}-000000000000000000000000.scope"
        receipt = self._complete_receipt(unit)
        with patch.object(subject.secrets, "token_hex", return_value="0" * 24):
            result, run, stop, unload = self._run_with(
                CompletedProcess(args=[], returncode=0, stdout=json.dumps(receipt)))
        self.assertTrue(result["temporary_scope_unloaded"])
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["systemd-run", "--user", "--scope"])
        self.assertIn("--property=MemoryMax=4608M", command)
        self.assertIn("--property=MemoryHigh=4096M", command)
        self.assertIn("--property=MemorySwapMax=0", command)
        self.assertIn("--property=CPUQuota=50%", command)
        self.assertIn("--property=TasksMax=64", command)
        self.assertEqual(command[command.index(sys.executable) + 1:command.index(sys.executable) + 3],
                         ["-m", "experimental.qwen_cpu_load_qualification"])
        self.assertEqual(run.call_args.kwargs["cwd"], subject._REPO_ROOT)
        self.assertNotIn("-c", command)
        self.assertNotIn("--wait", command)
        self.assertTrue(stop.called)
        self.assertEqual(unload.call_count, 2)

    @staticmethod
    def _complete_receipt(unit):
        return {
            "schema_version": "aeonith.qwen_cpu_load_probe.v1",
            "status": "scoped_cpu_float32_model_loaded_not_training_qualified",
            "unit": unit, "model_id": subject._BASE_MODEL,
            "revision_declared": subject._REVISION,
            "verified_files": 10,
            "manifest_sha256": hashlib.sha256(subject._MANIFEST.read_bytes()).hexdigest(),
            "cpu_float32_parameter_count": 100,
            "effective_controls": {
                "memory_max": str(subject._MEMORY_MAX),
                "memory_high": str(subject._MEMORY_HIGH),
                "swap_max": "0", "cpu_max": "50000 100000", "pids_max": "64",
            },
            "cgroup_memory_peak_bytes": 3 * 1024**3,
            "cgroup_memory_current_bytes": 2 * 1024**3,
            "model_loaded": True, "forward_passes": 0,
            "optimizer_steps": 0, "trained_adapter_created": False,
            "protected_loader_custody": False,
            "training_lease_established": False,
        }

    def test_truncated_or_spoofed_receipts_never_promoted(self):
        unit = "aeonith-modelcheck-123-0123456789abcdef01234567.scope"
        true_receipt = self._complete_receipt(unit)
        attacks = [
            {"unit": unit, "status": true_receipt["status"],
             "optimizer_steps": 0, "training_lease_established": False},
            {**true_receipt, "cpu_float32_parameter_count": 0},
            {**true_receipt, "model_loaded": False},
            {**true_receipt, "forward_passes": True},
            {**true_receipt, "verified_files": 0},
            {**true_receipt, "manifest_sha256": "0" * 64},
            {**true_receipt, "effective_controls": {**true_receipt["effective_controls"], "swap_max": "max"}},
            {**true_receipt, "effective_controls": {**true_receipt["effective_controls"], "cpu_max": "max 100000"}},
            {**true_receipt, "cgroup_memory_peak_bytes": subject._MEMORY_MAX + 1},
            {**true_receipt, "cgroup_memory_current_bytes": 0},
            {**true_receipt, "trained_adapter_created": True},
            {**true_receipt, "unexpected_path": "/private/source"},
        ]
        for attack in attacks:
            with self.subTest(index=attacks.index(attack)):
                with self.assertRaises(subject.ModelLoadQualificationError):
                    subject._validate_child_receipt(attack, unit)

    def test_memory_headroom_preserves_two_gib_for_other_work(self):
        for available_mib, allowed in ((6655, False), (6656, True), (7025, True)):
            with self.subTest(available_mib=available_mib):
                with patch.object(subject.Path, "read_text",
                                  return_value=f"MemAvailable: {available_mib * 1024} kB\n"):
                    if allowed:
                        self.assertEqual(subject._available_memory_mib(), available_mib)
                    else:
                        with self.assertRaises(subject.ModelLoadQualificationError):
                            subject._available_memory_mib()

    def test_failed_child_preserves_zero_training_claim_and_teardown(self):
        report, run, stop, unload = self._run_with(
            CompletedProcess(args=[], returncode=2, stdout=""))
        self.assertIsNone(report)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(unload.call_count, 2)

    def test_real_module_entrypoint_refuses_without_execute(self):
        """Unlike direct script-file invocation, -m can import its package."""
        result = subprocess.run([
            sys.executable, "-m", "experimental.qwen_cpu_load_qualification",
            "--base-dir", "/not-present",
        ], cwd=subject._REPO_ROOT, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('"status": "not_executed"', result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
