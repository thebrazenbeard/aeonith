"""Adversarial source-only checks for a Linux fd-pinned training output prototype."""

from __future__ import annotations

import os
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError
from training.private_artifact_broker import PinnedTrainingArtifacts, TrainingChildHandoff


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

    def _run_handoff_child(self, handoff, *, pass_fds=(), payload=None):
        # Separate CPython interpreter. No ML dependencies or expensive work.
        code = (
            "import os,sys; "
            "from training.private_artifact_broker import TrainingChildHandoff; "
            "h=TrainingChildHandoff.from_json(sys.argv[1]); "
            "fds=h.verify_current_process(); "
            "fd=os.open('child.fixture',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fds['adapter']); "
            "os.write(fd,b'inherited and pinned'); os.close(fd)"
        )
        return subprocess.run(
            [sys.executable, "-c", code, payload if payload is not None else handoff.to_json()],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, pass_fds=pass_fds,
        )

    def test_explicit_pass_fds_child_survives_ancestor_swap(self):
        original = self.root / "original"
        original.mkdir(mode=0o700)
        attacker = self.root / "attacker"
        attacker.mkdir(mode=0o700)
        with PinnedTrainingArtifacts.create(original / "run") as broker:
            handoff = broker.child_handoff()
            self.assertEqual(tuple(sorted(handoff.pass_fds)), handoff.pass_fds)
            original.rename(self.root / "moved")
            original.symlink_to(attacker, target_is_directory=True)
            child = self._run_handoff_child(handoff, pass_fds=handoff.pass_fds)
            self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(
            (self.root / "moved" / "run" / "adapter" / "child.fixture").read_bytes(),
            b"inherited and pinned",
        )
        self.assertFalse((attacker / "run").exists())

    def test_uninherited_child_fails_before_writing(self):
        with PinnedTrainingArtifacts.create(self.root / "no-inherit") as broker:
            handoff = broker.child_handoff()
            child = self._run_handoff_child(handoff)
            self.assertNotEqual(child.returncode, 0)
        self.assertFalse((self.root / "no-inherit" / "adapter" / "child.fixture").exists())

    def test_tampered_handoff_identity_fails_before_writing(self):
        with PinnedTrainingArtifacts.create(self.root / "tampered") as broker:
            handoff = broker.child_handoff()
            payload = json.loads(handoff.to_json())
            payload["adapter"]["inode"] += 1
            child = self._run_handoff_child(handoff, pass_fds=handoff.pass_fds,
                                            payload=json.dumps(payload))
            self.assertNotEqual(child.returncode, 0)
        self.assertFalse((self.root / "tampered" / "adapter" / "child.fixture").exists())

    def test_inherited_descriptor_reassigned_to_other_directory_fails(self):
        other = self.root / "other"
        other.mkdir(mode=0o700)
        with PinnedTrainingArtifacts.create(self.root / "reassigned") as broker:
            handoff = broker.child_handoff()
            code = (
                "import os,sys; "
                "from training.private_artifact_broker import TrainingChildHandoff; "
                "h=TrainingChildHandoff.from_json(sys.argv[1]); "
                "foreign=os.open(sys.argv[2],os.O_RDONLY|os.O_DIRECTORY); "
                "os.dup2(foreign,h.adapter.fd); "
                "h.verify_current_process(); "
                "fd=os.open('escaped.fixture',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=h.adapter.fd); "
                "os.close(fd)"
            )
            child = subprocess.run(
                [sys.executable, "-c", code, handoff.to_json(), str(other)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                text=True, pass_fds=handoff.pass_fds,
            )
            self.assertNotEqual(child.returncode, 0)
        self.assertFalse((other / "escaped.fixture").exists())
        self.assertFalse((self.root / "reassigned" / "adapter" / "escaped.fixture").exists())

    def test_child_rechecks_private_directory_access_mode(self):
        with PinnedTrainingArtifacts.create(self.root / "mode-changed") as broker:
            handoff = broker.child_handoff()
            adapter = broker.adapter_path
            adapter.chmod(0o755)
            try:
                child = self._run_handoff_child(handoff, pass_fds=handoff.pass_fds)
                self.assertNotEqual(child.returncode, 0)
                self.assertFalse((self.root / "mode-changed" / "adapter" / "child.fixture").exists())
            finally:
                adapter.chmod(0o700)

    def test_bad_or_ambiguous_transport_records_are_rejected(self):
        with PinnedTrainingArtifacts.create(self.root / "bad-records") as broker:
            payload = json.loads(broker.child_handoff().to_json())
            payload["runtime"]["fd"] = True
            with self.assertRaises(PrivateOutputError):
                TrainingChildHandoff.from_json(json.dumps(payload))
            payload = json.loads(broker.child_handoff().to_json())
            payload["runtime"]["fd"] = payload["adapter"]["fd"]
            with self.assertRaises(PrivateOutputError):
                TrainingChildHandoff.from_json(json.dumps(payload))
            with self.assertRaises(PrivateOutputError):
                TrainingChildHandoff.from_json("{}")
            valid = broker.child_handoff().to_json()
            with self.assertRaises(PrivateOutputError):
                TrainingChildHandoff.from_json(valid.replace('"schema":1', '"schema":1,"schema":1'))

    def test_child_handoff_requires_open_broker(self):
        broker = PinnedTrainingArtifacts.create(self.root / "closed-handoff")
        handoff = broker.child_handoff()
        self.assertIsInstance(TrainingChildHandoff.from_json(handoff.to_json()), TrainingChildHandoff)
        broker.close()
        with self.assertRaisesRegex(PrivateOutputError, "closed"):
            broker.child_handoff()

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
