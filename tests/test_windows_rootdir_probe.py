"""The Windows rooted-handle experiment is opt-in and never a production gate."""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
import unittest

from experimental import windows_rootdir_probe as probe


class WindowsRootDirectoryProbeTests(unittest.TestCase):
    def test_fixed_name_prevents_device_aliases_and_paths(self):
        self.assertEqual(
            probe._marker_basename("relative-pinned-marker.bin"),
            "relative-pinned-marker.bin",
        )
        for name in ("..", ".", "CON", "NUL", "foo\\bar", "foo/bar", "a:b", "", 7):
            with self.subTest(name=name), self.assertRaises(ValueError):
                probe._marker_basename(name)

    def test_default_cli_is_no_op(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(probe.main([]), 0)
        result = json.loads(buffer.getvalue())
        self.assertEqual(result["execution"], "NOT_RUN_OPT_IN_REQUIRED")
        self.assertEqual(result["qualification_status"], "NOT_QUALIFIED")

    @unittest.skipIf(os.name == "nt", "non-Windows branch only")
    def test_non_windows_never_attempts_native_calls(self):
        self.assertEqual(probe.run_disposable_rootdir_probes(), {
            "qualification_status": "NOT_QUALIFIED",
            "execution": "NOT_RUN_NON_WINDOWS",
        })

    @unittest.skipUnless(
        os.name == "nt" and os.environ.get("AEONITH_WINDOWS_ROOTDIR_PROBE_OPT_IN") == "1",
        "real Windows disposable probe requires explicit opt-in",
    )
    def test_windows_synthetic_ancestry_swap(self):
        result = probe.run_disposable_rootdir_probes()
        self.assertEqual(result["qualification_status"], "NOT_QUALIFIED")
        self.assertFalse(result["real_private_output_qualified"])
        self.assertFalse(result["same_sid_acl_isolation_qualified"])
        self.assertEqual([case["test"] for case in result["cases"]], ["junction", "symlink"])
        for case in result["cases"]:
            if case["execution"] == "EXECUTED":
                self.assertTrue(case["same_sid_ancestor_swap"])
                self.assertTrue(case["original_directory_handle_identity_preserved"])
                # A positive result in a synthetic test is never a private
                # file-writer qualification. A false value is a falsifier.
                self.assertIn(case["rooted_create_landed_in_pinned_directory"], (True, False))
                self.assertIn(case["decoy_marker_created"], (True, False))
            else:
                self.assertEqual(case["execution"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
