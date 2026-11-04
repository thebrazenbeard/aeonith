"""Unit-only adversarial checks for the one-shot WSL user scope probe."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from experimental.wsl_scope_qualification import (
    ScopeQualificationError, _read_child_cgroup, main, run_qualification,
)


class ScopeReadbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.unit = "aeonith-scopecheck-42-deadbeef.scope"
        self.cg = self.root / "user.slice" / "app.slice" / self.unit
        self.cg.mkdir(parents=True)
        self.membership = self.root / "membership"
        self.membership.write_text(f"0::/user.slice/app.slice/{self.unit}\n", encoding="ascii")
        self.values = {
            "memory.max": "536870912\n",
            "memory.high": "402653184\n",
            "memory.swap.max": "0\n",
            "cpu.max": "25000 100000\n",
            "pids.max": "16\n",
        }
        self.write_values()

    def write_values(self):
        for name, value in self.values.items():
            (self.cg / name).write_text(value, encoding="ascii")

    def test_exact_effective_controls_pass_not_training_lease(self):
        report = _read_child_cgroup(self.unit, root=self.root, membership=self.membership)
        self.assertEqual(report["effective"]["cpu_max"], "25000 100000")
        self.assertFalse(report["model_loaded"])
        self.assertFalse(report["training_lease_established"])
        self.assertEqual(report["optimizer_steps"], 0)

    def test_rejects_missing_membership_or_alias(self):
        for path in (
            "0::/other.scope\n", "0::/app.slice/..\n", "1:cpu:/unit.scope\n",
            f"0::C:\\user.slice\\app.slice\\{self.unit}\n",
        ):
            with self.subTest(path=path):
                self.membership.write_text(path, encoding="ascii")
                with self.assertRaises(ScopeQualificationError):
                    _read_child_cgroup(self.unit, root=self.root, membership=self.membership)

    def test_rejects_unlimited_or_mismatched_controls(self):
        for key, bad in (
            ("memory.max", "max\n"), ("memory.high", "536870912\n"),
            ("memory.swap.max", "1024\n"), ("pids.max", "max\n"),
            ("cpu.max", "max 100000\n"), ("cpu.max", "50000 100000\n"),
        ):
            with self.subTest(key=key, bad=bad):
                original = self.values[key]
                self.values[key] = bad
                self.write_values()
                with self.assertRaises(ScopeQualificationError):
                    _read_child_cgroup(self.unit, root=self.root, membership=self.membership)
                self.values[key] = original
        self.write_values()

    def test_rejects_missing_cgroup_control_file(self):
        (self.cg / "pids.max").unlink()
        with self.assertRaises(ScopeQualificationError):
            _read_child_cgroup(self.unit, root=self.root, membership=self.membership)


class ScopeLauncherTests(unittest.TestCase):
    def _fake_receipt(self, unit):
        return {
            "schema_version": "aeonith.scope_limits_probe.v1",
            "status": "process_effective_limits_verified",
            "unit": unit,
            "effective": {"cpu_max": "25000 100000"},
            "training_lease_established": False,
        }

    def test_launch_has_no_shell_expansion_and_teardown(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            self.assertIsInstance(command, list)
            self.assertNotIn("/bin/sh", command)
            self.assertNotIn("bash", command)
            self.assertNotIn("--wait", command)
            unit = next(item.partition("=")[2] for item in command if item.startswith("--unit="))
            payload = json.dumps(self._fake_receipt(unit), sort_keys=True)
            return subprocess.CompletedProcess(command, 0, "Running as unit: " + unit + "\n" + payload + "\n", "")

        with patch("experimental.wsl_scope_qualification._controllers_available"), \
             patch("experimental.wsl_scope_qualification.subprocess.run", side_effect=fake_run), \
             patch("experimental.wsl_scope_qualification._stop_owned_unit") as stop, \
             patch("experimental.wsl_scope_qualification._assert_unloaded") as unloaded:
            receipt = run_qualification()
        self.assertEqual(len(calls), 1)
        self.assertEqual(receipt["status"], "process_effective_limits_verified")
        self.assertTrue(receipt["temporary_scope_unloaded"])
        unit = receipt["unit"]
        stop.assert_called_once_with(unit)
        self.assertEqual(unloaded.call_count, 2)
        unloaded.assert_any_call(unit)

    def test_no_receipt_fails_closed_and_stops_only_owned_scope(self):
        with patch("experimental.wsl_scope_qualification._controllers_available"), \
             patch("experimental.wsl_scope_qualification.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Running as unit\n", "")), \
             patch("experimental.wsl_scope_qualification._stop_owned_unit") as stop, \
             patch("experimental.wsl_scope_qualification._assert_unloaded"):
            with self.assertRaises(ScopeQualificationError):
                run_qualification()
        self.assertEqual(stop.call_count, 1)
        self.assertTrue(stop.call_args.args[0].startswith("aeonith-scopecheck-"))

    def test_preexisting_unit_is_never_launched_or_stopped(self):
        with patch("experimental.wsl_scope_qualification._controllers_available"), \
             patch("experimental.wsl_scope_qualification._assert_unloaded", side_effect=ScopeQualificationError("occupied")), \
             patch("experimental.wsl_scope_qualification.subprocess.run") as launch, \
             patch("experimental.wsl_scope_qualification._stop_owned_unit") as stop:
            with self.assertRaises(ScopeQualificationError):
                run_qualification()
        launch.assert_not_called()
        stop.assert_not_called()

    def test_timeout_stops_own_disposable_unit_and_refuses(self):
        with patch("experimental.wsl_scope_qualification._controllers_available"), \
             patch("experimental.wsl_scope_qualification.subprocess.run", side_effect=subprocess.TimeoutExpired("systemd-run", 20)), \
             patch("experimental.wsl_scope_qualification._stop_owned_unit") as stop, \
             patch("experimental.wsl_scope_qualification._assert_unloaded"):
            with self.assertRaises(ScopeQualificationError):
                run_qualification()
        self.assertEqual(stop.call_count, 1)

    def test_default_refuses_and_never_calls_runtime(self):
        with patch("experimental.wsl_scope_qualification.run_qualification", side_effect=AssertionError("launched")):
            self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
