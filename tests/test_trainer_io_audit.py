"""Synthetic-only falsifiers for the non-authoritative trainer I/O observer."""

import os
from pathlib import Path
import tempfile
import unittest

from experimental.trainer_io_audit import (
    MAX_OBSERVED_EVENTS,
    PythonTrainerIOObservation,
)


class TrainerIOObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aeonith-io-observe-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = self.root / "private"
        self.allowed.mkdir()

    def test_detects_python_visible_external_write_without_leaking_path(self):
        private_marker = "PRIVATE_MANUSCRIPT_FILENAME_123"
        with PythonTrainerIOObservation(self.allowed) as observer:
            (self.root / private_marker).write_text("synthetic only", encoding="utf-8")
            (self.allowed / "adapter_config.json").write_bytes(b"{}")
        receipt = observer.receipt()
        self.assertGreaterEqual(receipt["observed_event_count"], 2)
        self.assertEqual(receipt["lexical_scope_counts"]["outside_expected_root"], 1)
        self.assertGreaterEqual(receipt["lexical_scope_counts"]["lexically_within_expected_root"], 1)
        self.assertNotIn(private_marker, str(receipt))
        self.assertFalse(receipt["trainer_output_custody_qualified"])

    def test_mutation_events_include_directory_creation(self):
        with PythonTrainerIOObservation(self.allowed) as observer:
            (self.allowed / "subdir").mkdir()
        self.assertGreaterEqual(observer.receipt()["event_category_counts"].get("os.mkdir", 0), 1)

    def test_existing_fd_write_escapes_python_open_observation(self):
        # This is a concrete FALSE NEGATIVE, not a successful custody result.
        external = self.root / "existing_fd_synthetic.txt"
        fd = os.open(external, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        try:
            with PythonTrainerIOObservation(self.allowed) as observer:
                os.write(fd, b"not a manuscript")
            receipt = observer.receipt()
            self.assertEqual(receipt["observed_event_count"], 0)
            self.assertFalse(receipt["absence_of_external_writes_proven"])
            self.assertEqual(external.read_bytes(), b"not a manuscript")
        finally:
            os.close(fd)

    def test_symlink_redirects_write_outside_despite_lexical_inside_count(self):
        external = self.root / "external_real_dir"
        external.mkdir()
        alias = self.allowed / "inside_alias"
        try:
            alias.symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"synthetic symlink unavailable: {type(exc).__name__}")
        with PythonTrainerIOObservation(self.allowed) as observer:
            (alias / "redirected.txt").write_text("synthetic", encoding="utf-8")
        receipt = observer.receipt()
        self.assertEqual(receipt["lexical_scope_counts"].get("outside_expected_root", 0), 0)
        self.assertGreaterEqual(receipt["lexical_scope_counts"]["lexically_within_expected_root"], 1)
        self.assertEqual((external / "redirected.txt").read_text(), "synthetic")
        self.assertFalse(receipt["trainer_output_custody_qualified"])

    def test_rename_inside_to_outside_counts_destination_not_just_source(self):
        source = self.allowed / "staged.txt"
        source.write_text("synthetic", encoding="utf-8")
        destination = self.root / "external_renamed.txt"
        with PythonTrainerIOObservation(self.allowed) as observer:
            os.rename(source, destination)
        receipt = observer.receipt()
        self.assertEqual(receipt["lexical_scope_counts"]["outside_expected_root"], 1)
        self.assertEqual(receipt["source_operand_scope_counts"]["lexically_within_expected_root"], 1)
        self.assertEqual(destination.read_text(), "synthetic")
        self.assertFalse(source.exists())

    def test_link_inside_to_outside_counts_destination(self):
        source = self.allowed / "source.txt"
        source.write_text("synthetic", encoding="utf-8")
        destination = self.root / "external_hardlink.txt"
        try:
            with PythonTrainerIOObservation(self.allowed) as observer:
                os.link(source, destination)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"synthetic hardlink unavailable: {type(exc).__name__}")
        receipt = observer.receipt()
        self.assertEqual(receipt["lexical_scope_counts"]["outside_expected_root"], 1)
        self.assertEqual(receipt["source_operand_scope_counts"]["lexically_within_expected_root"], 1)
        self.assertEqual(destination.read_text(), "synthetic")

    def test_symlink_creation_classifies_link_name_not_target_text(self):
        destination = self.root / "external_link"
        try:
            with PythonTrainerIOObservation(self.allowed) as observer:
                os.symlink(self.allowed / "target", destination)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"synthetic symlink unavailable: {type(exc).__name__}")
        receipt = observer.receipt()
        self.assertEqual(receipt["lexical_scope_counts"]["outside_expected_root"], 1)
        self.assertEqual(receipt["source_operand_scope_counts"], {})
        self.assertTrue(destination.is_symlink())

    @unittest.skipUnless(os.mkdir in os.supports_dir_fd, "dir_fd mkdir unavailable")
    def test_dirfd_relative_write_is_unknown_not_false_cwd_scoped(self):
        external = self.root / "external_fd_directory"
        external.mkdir()
        fd = os.open(external, os.O_RDONLY)
        try:
            with PythonTrainerIOObservation(self.allowed) as observer:
                os.mkdir("child_via_fd", dir_fd=fd)
            receipt = observer.receipt()
            self.assertEqual(receipt["lexical_scope_counts"], {"unknown_dirfd_relative": 1})
            self.assertTrue((external / "child_via_fd").is_dir())
        finally:
            os.close(fd)

    def test_oversized_event_stream_is_bounded_but_counted(self):
        with PythonTrainerIOObservation(self.allowed) as observer:
            for _ in range(MAX_OBSERVED_EVENTS + 1):
                observer._hook("open", ("/outside", "wb", os.O_WRONLY))
        receipt = observer.receipt()
        self.assertEqual(receipt["observed_event_count"], MAX_OBSERVED_EVENTS + 1)
        self.assertTrue(receipt["event_limit_exceeded"])
        self.assertEqual(sum(receipt["event_category_counts"].values()), MAX_OBSERVED_EVENTS)

    def test_reuse_and_active_receipt_refused(self):
        observer = PythonTrainerIOObservation(self.allowed)
        with observer:
            with self.assertRaises(RuntimeError):
                observer.receipt()
        with self.assertRaises(RuntimeError):
            with observer:
                pass


if __name__ == "__main__":
    unittest.main()
