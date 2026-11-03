"""The Windows custody matrix is evidence-only and synthetic by default."""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from types import SimpleNamespace
import unittest

from experimental import windows_custody_matrix as matrix


class WindowsCustodyMatrixTests(unittest.TestCase):
    def test_interrupted_child_requests_binary_file_mode(self):
        """Exercise the actual generated script's open flags without host effects."""
        class OpenIntercept(Exception):
            pass

        observed_flags = []

        def fake_open(_path, flags, _mode):
            observed_flags.append(flags)
            raise OpenIntercept

        fake_os = SimpleNamespace(O_WRONLY=1, O_CREAT=2, O_EXCL=4,
                                  O_BINARY=8, open=fake_open)
        fake_sys = SimpleNamespace(argv=["child", "synthetic-test-path"])

        def import_fake(name, *_args, **_kwargs):
            return {"os": fake_os, "sys": fake_sys}[name]

        with self.assertRaises(OpenIntercept):
            exec(matrix._crash_child_code(), {"__builtins__": {
                "__import__": import_fake, "getattr": getattr,
            }})
        self.assertEqual(observed_flags, [1 | 2 | 4 | 8])

    def test_default_cli_never_runs_any_native_probe(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(matrix.main([]), 2)
        self.assertEqual(json.loads(output.getvalue()), {
            "qualification_status": "NOT_QUALIFIED",
            "execution": "NOT_RUN_OPT_IN_REQUIRED",
        })

    @unittest.skipIf(os.name == "nt", "non-Windows fail-closed contract")
    def test_explicit_flag_on_linux_still_has_no_native_effect(self):
        self.assertEqual(matrix.run_disposable_matrix(), {
            "qualification_status": "NOT_QUALIFIED",
            "execution": "NOT_RUN_NON_WINDOWS",
        })

    def test_favorable_observations_do_not_make_training_qualified(self):
        rooted = {"cases": [{"test": "junction", "execution": "EXECUTED",
                             "original_directory_handle_identity_preserved": True,
                             "rooted_create_landed_in_pinned_directory": True,
                             "decoy_marker_created": False}]}
        reparse = {"cases": [{"test": "junction", "execution": "EXECUTED",
                              "opened_target_identity_after_swap": False,
                              "observations": {"dacl_is_null": False}}]}
        interruption = {"execution": "EXECUTED", "child_exited_by_design": True,
                        "partial_marker_preserved": True,
                        "exclusive_retry_refused_clobber": True, "final_receipt_absent": True}
        verdict = matrix.summarize_matrix(rooted, reparse, interruption)
        self.assertEqual(verdict["qualification_status"], "NOT_QUALIFIED")
        self.assertFalse(verdict["train_or_deploy_authorized"])
        self.assertFalse(verdict["native_windows_private_writer_qualified"])
        self.assertFalse(verdict["falsifiers"])
        self.assertIn("effective_ACE_rights_and_privileges", verdict["material_unknowns"])

    def test_bad_handle_reparse_and_recovery_are_falsifiers(self):
        rooted = {"cases": [{"execution": "EXECUTED",
                             "original_directory_handle_identity_preserved": False,
                             "rooted_create_landed_in_pinned_directory": False,
                             "decoy_marker_created": True}]}
        reparse = {"cases": [{"execution": "EXECUTED",
                              "opened_target_identity_after_swap": True,
                              "observations": {
                                  "owner_present": False,
                                  "owner_matches_token_user": False,
                                  "dacl_present": False,
                                  "dacl_is_null": True,
                                  "dacl_protected": False,
                                  "reparse_point_present": True,
                                  "ancestor_redirect_observed": True,
                              }}]}
        interrupted = {"execution": "EXECUTED", "child_exited_by_design": False,
                       "partial_marker_preserved": False,
                       "exclusive_retry_refused_clobber": False, "final_receipt_absent": False}
        verdict = matrix.summarize_matrix(rooted, reparse, interrupted)
        self.assertEqual(set(verdict["falsifiers"]), {
            "root_handle_identity_changed", "relative_create_escaped_pinned_directory",
            "relative_create_hit_decoy", "path_open_redirected_after_ancestor_swap",
            "null_dacl_observed", "exclusive_retry_overwrote_or_missed_partial",
            "unexpected_final_receipt_after_interruption", "interrupted_child_exit_unverified",
            "interrupted_partial_not_preserved", "absent_owner", "noncaller_owner",
            "absent_dacl", "inherited_dacl", "reparse_point_present",
            "ancestor_reparse_traversed",
        })

    def test_live_vn1_style_observations_expose_acl_and_path_falsifiers(self):
        case = {"execution": "EXECUTED", "opened_target_identity_after_swap": True,
                "observations": {"owner_present": True, "owner_matches_token_user": False,
                                 "dacl_present": True, "dacl_is_null": False,
                                 "dacl_protected": False, "reparse_point_present": True,
                                 "ancestor_redirect_observed": True}}
        verdict = matrix.summarize_matrix({"cases": []}, {"cases": [case]},
                                          {"execution": "INCONCLUSIVE"})
        self.assertEqual(set(verdict["falsifiers"]), {
            "path_open_redirected_after_ancestor_swap", "noncaller_owner",
            "inherited_dacl", "reparse_point_present", "ancestor_reparse_traversed",
        })

    def test_missing_interruption_evidence_is_not_silently_favorable(self):
        verdict = matrix.summarize_matrix({"cases": []}, {"cases": []},
                                          {"execution": "EXECUTED"})
        self.assertEqual(set(verdict["falsifiers"]), {
            "interrupted_child_exit_unverified", "interrupted_partial_not_preserved",
            "exclusive_retry_overwrote_or_missed_partial",
            "unexpected_final_receipt_after_interruption",
        })

    def test_inconclusive_is_not_pass_or_an_authority_upgrade(self):
        result = matrix.summarize_matrix({"cases": [{"execution": "INCONCLUSIVE"}]},
                                         {"cases": []}, {"execution": "INCONCLUSIVE"})
        self.assertEqual(result["rooted_cases_executed"], 0)
        self.assertFalse(result["interruption_executed"])
        self.assertFalse(result["train_or_deploy_authorized"])

    def test_disposable_child_interruption_preserves_exclusive_partial(self):
        """Cross-platform mechanics test, not Windows durability evidence."""
        result = matrix._run_disposable_interruption()
        self.assertEqual(result["execution"], "EXECUTED")
        self.assertTrue(result["child_exited_by_design"])
        self.assertTrue(result["partial_marker_preserved"])
        self.assertTrue(result["exclusive_retry_refused_clobber"])
        self.assertTrue(result["final_receipt_absent"])
        self.assertFalse(result["durable_flush_qualified"])

    def test_inspect_cli_never_reports_shell_success_even_with_favorable_matrix(self):
        output = StringIO()
        with redirect_stdout(output):
            status = matrix.main(["--run-disposable-temp-matrix"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["qualification_status"], "NOT_QUALIFIED")

    @unittest.skipUnless(os.name == "nt" and os.environ.get("AEONITH_WIN_MATRIX_PROBE_OPT_IN") == "1",
                         "Windows disposable matrix requires explicit opt-in")
    def test_real_windows_temp_only_matrix_stays_unqualified(self):
        result = matrix.run_disposable_matrix()
        self.assertEqual(result["execution"], "EXECUTED_SYNTHETIC_ONLY")
        self.assertFalse(result["assessment"]["train_or_deploy_authorized"])
        self.assertFalse(result["assessment"]["native_windows_private_writer_qualified"])
        self.assertEqual(result["interrupted_exclusive_create"]["qualification_status"],
                         "NOT_QUALIFIED")


if __name__ == "__main__":
    unittest.main()
