"""Adversarial source-only checks for a Linux fd-pinned training output prototype."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError
from training.private_artifact_broker import PinnedTrainingArtifacts


@unittest.skipUnless(sys.platform == "linux", "Linux procfs fd paths are required")
class LinuxPrivateTrainingBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_trainer_named_subdirectories_are_private_and_pinned(self):
        with PinnedTrainingArtifacts.create(self.root / "adapter-run") as broker:
            for location in (broker.runtime_path, broker.adapter_path):
                self.assertTrue(location.is_dir())
                self.assertEqual(stat.S_IMODE(location.stat().st_mode), 0o700)
                self.assertEqual(location.stat().st_uid, os.geteuid())
            (broker.runtime_path / "checkpoint.fixture").write_text("safe", encoding="utf-8")
            (broker.adapter_path / "adapter.fixture").write_text("safe", encoding="utf-8")
            broker.write_receipt(b'{"synthetic":true}\n')
            broker.verify_live()
        self.assertEqual((self.root / "adapter-run" / "runtime" / "checkpoint.fixture").read_text(), "safe")
        self.assertEqual((self.root / "adapter-run" / "adapter" / "adapter.fixture").read_text(), "safe")
        self.assertEqual((self.root / "adapter-run" / "training_receipt.json").read_bytes(), b'{"synthetic":true}\n')

    def test_rename_and_original_path_symlink_cannot_redirect_fd_anchored_writes(self):
        parent = self.root / "original"
        parent.mkdir(mode=0o700)
        attacker = self.root / "attacker"
        attacker.mkdir(mode=0o700)
        with PinnedTrainingArtifacts.create(parent / "run") as broker:
            parent.rename(self.root / "moved")
            parent.symlink_to(attacker, target_is_directory=True)
            (broker.adapter_path / "adapter.fixture").write_text("pinned", encoding="utf-8")
            broker.write_receipt(b"not manuscript text\n")
            broker.verify_live()
        self.assertEqual((self.root / "moved" / "run" / "adapter" / "adapter.fixture").read_text(), "pinned")
        self.assertFalse((attacker / "run").exists())
        self.assertEqual((self.root / "moved" / "run" / "training_receipt.json").read_bytes(), b"not manuscript text\n")

    def test_realpath_consumer_breaks_procfd_guarantee_so_trainer_gate_stays_closed(self):
        # This is a deliberately hostile *counterexample*: a framework that
        # canonicalizes /proc/self/fd/N before opening files can lose custody.
        original = self.root / "original"
        original.mkdir(mode=0o700)
        attacker = self.root / "attacker"
        attacker.mkdir(mode=0o700)
        with PinnedTrainingArtifacts.create(original / "run") as broker:
            untrusted_canonicalized_path = broker.adapter_path.resolve()
            original.rename(self.root / "moved")
            (attacker / "run" / "adapter").mkdir(parents=True)
            original.symlink_to(attacker, target_is_directory=True)
            (untrusted_canonicalized_path / "escaped.fixture").write_text("escaped")
            (broker.adapter_path / "pinned.fixture").write_text("protected")
        self.assertTrue((attacker / "run" / "adapter" / "escaped.fixture").exists())
        self.assertFalse((attacker / "run" / "adapter" / "pinned.fixture").exists())
        self.assertEqual((self.root / "moved" / "run" / "adapter" / "pinned.fixture").read_text(), "protected")

    def test_procfd_path_is_not_inherited_by_normal_subprocess(self):
        with PinnedTrainingArtifacts.create(self.root / "child") as broker:
            proc_path = str(broker.runtime_path)
            child = subprocess.run(
                [sys.executable, "-c", "from pathlib import Path; import sys; print(Path(sys.argv[1]).is_dir())", proc_path],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(child.stdout.strip(), "False")

    def test_cached_procfd_path_can_alias_reused_descriptor_after_close(self):
        # A returned Path is not revocable. Closing the broker invalidates its
        # properties, but a consumer can retain the old /proc/self/fd/N text.
        broker = PinnedTrainingArtifacts.create(self.root / "closed-owner")
        stale_path = broker.adapter_path
        stale_fd = int(stale_path.name)
        broker.close()
        other = self.root / "other-directory"
        other.mkdir(mode=0o700)
        source_fd = os.open(other, os.O_RDONLY | os.O_DIRECTORY)
        try:
            if source_fd != stale_fd:
                os.dup2(source_fd, stale_fd)
            (stale_path / "stale.fixture").write_text("redirected", encoding="utf-8")
            self.assertEqual((other / "stale.fixture").read_text(), "redirected")
            self.assertFalse((self.root / "closed-owner" / "adapter" / "stale.fixture").exists())
        finally:
            if source_fd != stale_fd:
                os.close(source_fd)
            os.close(stale_fd)

    def test_bare_git_parent_fails_before_creation(self):
        bare = self.root / "bare.git"
        bare.mkdir()
        (bare / "HEAD").write_text("ref: refs/heads/main\n")
        (bare / "objects").mkdir()
        (bare / "refs").mkdir()
        with self.assertRaisesRegex(PrivateOutputError, "bare Git"):
            PinnedTrainingArtifacts.create(bare / "private-run")
        self.assertFalse((bare / "private-run").exists())

    def test_windows_private_output_stays_fail_closed(self):
        with patch("aeonith.private_output._is_windows", return_value=True):
            with self.assertRaisesRegex(PrivateOutputError, "Windows private output ACL"):
                PinnedTrainingArtifacts.create(self.root / "never-create")
        self.assertFalse((self.root / "never-create").exists())

    def test_closed_broker_refuses_reusing_procfd_path(self):
        broker = PinnedTrainingArtifacts.create(self.root / "closed")
        broker.close()
        with self.assertRaisesRegex(PrivateOutputError, "closed"):
            _ = broker.adapter_path
        with self.assertRaisesRegex(PrivateOutputError, "closed"):
            broker.write_receipt(b"too late")


if __name__ == "__main__":
    unittest.main()
