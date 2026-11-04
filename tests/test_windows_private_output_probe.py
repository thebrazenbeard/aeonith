"""Falsification-only tests for the opt-in Windows experiment."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from experimental import windows_private_output_probe as probe


class WindowsPrivateOutputSourceTests(unittest.TestCase):
    def test_default_cli_does_no_io(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(probe.main([]), 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["qualification_status"], "NOT_QUALIFIED")
        self.assertEqual(receipt["execution"], "NOT_RUN_OPT_IN_REQUIRED")

    def test_missing_evidence_is_never_a_pass(self) -> None:
        self.assertEqual(
            probe.classify_security_observation({}),
            {
                "qualification_status": "NOT_QUALIFIED",
                "falsifiers": [],
                "unknowns_remain": True,
            },
        )

    def test_favorable_owner_dacl_does_not_qualify(self) -> None:
        receipt = probe.classify_security_observation({
            "owner_present": True,
            "owner_matches_token_user": True,
            "dacl_present": True,
            "dacl_is_null": False,
            "dacl_protected": True,
            "reparse_point_present": False,
            "ancestor_redirect_observed": False,
        })
        self.assertEqual(receipt["qualification_status"], "NOT_QUALIFIED")
        self.assertTrue(receipt["unknowns_remain"])

    def test_adversarial_owner_and_dacl_falsifiers(self) -> None:
        receipt = probe.classify_security_observation({
            "owner_present": False,
            "owner_matches_token_user": False,
            "dacl_present": False,
            "dacl_is_null": True,
            "dacl_protected": False,
        })
        self.assertEqual(set(receipt["falsifiers"]), {
            "absent_owner", "noncaller_owner", "absent_dacl",
            "null_dacl", "inherited_dacl",
        })

    def test_adversarial_junction_parent_rename_falsifiers(self) -> None:
        receipt = probe.classify_security_observation({
            "reparse_point_present": True,
            "ancestor_redirect_observed": True,
        })
        self.assertEqual(set(receipt["falsifiers"]), {
            "reparse_point_present", "ancestor_reparse_traversed",
        })

    def test_junction_cmd_argument_whitelist(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(probe._safe_junction_paths(root / "new", root / "target", root))
            self.assertFalse(probe._safe_junction_paths(
                root / "injected&whoami", root / "target", root
            ))
            self.assertFalse(probe._safe_junction_paths(
                root / "child", root.parent / "outside", root
            ))

    def test_junction_launcher_uses_trusted_absolute_binary_and_disposable_cwd(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            trusted = Path("/system32/cmd.exe")
            with mock.patch.object(probe, "_trusted_cmd_path", return_value=trusted), \
                    mock.patch.object(probe.subprocess, "run") as process:
                process.return_value.returncode = 0
                probe._make_junction(root / "link", root / "target", root, object())
            command = process.call_args.args[0]
            self.assertEqual(command[0], str(trusted))
            self.assertNotEqual(command[0].lower(), "cmd.exe")
            self.assertEqual(process.call_args.kwargs["cwd"], str(root))
            self.assertFalse(process.call_args.kwargs.get("shell", False))
            self.assertEqual(command[1:5], ["/d", "/c", "mklink", "/J"])

    def test_junction_timeout_cannot_expose_temp_paths(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            # Simulate a timeout exception whose string includes private host
            # temp paths. This must be converted to a path-free RuntimeError.
            timeout = subprocess.TimeoutExpired(["cmd.exe", str(root / "secret")], 15)
            with mock.patch.object(probe, "_trusted_cmd_path", return_value=Path("/system32/cmd.exe")), \
                    mock.patch.object(probe.subprocess, "run", side_effect=timeout):
                with self.assertRaises(RuntimeError) as raised:
                    probe._make_junction(root / "link", root / "target", root, object())
            self.assertNotIn(str(root), str(raised.exception))
            self.assertNotIn("cmd.exe", str(raised.exception))

    def test_junction_process_error_cannot_expose_temp_paths(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(probe, "_trusted_cmd_path", return_value=Path("/system32/cmd.exe")), \
                    mock.patch.object(probe.subprocess, "run", side_effect=OSError(str(root))):
                with self.assertRaises(RuntimeError) as raised:
                    probe._make_junction(root / "link", root / "target", root, object())
            self.assertNotIn(str(root), str(raised.exception))

    def test_enabled_production_module_does_not_reference_experiment(self) -> None:
        source = Path(__file__).resolve().parents[1] / "aeonith" / "private_output.py"
        contents = source.read_text(encoding="utf-8")
        self.assertNotIn("experimental", contents)
        self.assertIn("Windows private output ACL boundary is not yet qualified", contents)

    @unittest.skipIf(os.name == "nt", "non-Windows test only")
    def test_opt_in_returns_not_run_outside_windows(self) -> None:
        self.assertEqual(
            probe.run_disposable_windows_probes(),
            {"qualification_status": "NOT_QUALIFIED", "execution": "NOT_RUN_NON_WINDOWS"},
        )

    @unittest.skipUnless(
        os.name == "nt" and os.environ.get("AEONITH_WINDOWS_PROBE_OPT_IN") == "1",
        "requires explicit opt-in on a disposable Windows host test",
    )
    def test_windows_host_disposable_falsification(self) -> None:
        receipt = probe.run_disposable_windows_probes()
        self.assertEqual(receipt["qualification_status"], "NOT_QUALIFIED")
        self.assertFalse(receipt["real_private_output_qualified"])
        self.assertEqual({case["test"] for case in receipt["cases"]}, {"junction", "symlink"})
        for case in receipt["cases"]:
            if case["execution"] == "EXECUTED":
                self.assertEqual(case["verdict"]["qualification_status"], "NOT_QUALIFIED")
            else:
                self.assertEqual(case["execution"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
