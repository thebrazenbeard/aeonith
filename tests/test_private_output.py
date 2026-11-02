"""Adversarial tests for the optional private artifact directory boundary."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError, create_private_directory


@unittest.skipUnless(os.name == "posix", "POSIX descriptor-pinning tests")
class PrivateOutputDirectoryTests(unittest.TestCase):
    def setUp(self):
        # The test runner's TMPDIR may be inside the source Git worktree;
        # private outputs must instead be outside every checkout.
        self.temp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_private_directory_and_file_are_exclusive(self):
        destination = self.root / "work"
        with create_private_directory(destination) as output:
            output.write_text("review.json", '{"passage":"private"}')
            self.assertEqual((destination / "review.json").read_text(), '{"passage":"private"}')
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((destination / "review.json").stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                output.write_text("review.json", "replacement")
            with self.assertRaises(FileExistsError):
                create_private_directory(destination)
        self.assertTrue((destination / "review.json").is_file())

    def test_closed_directory_rejects_writes(self):
        with create_private_directory(self.root / "run") as output:
            pass
        with self.assertRaisesRegex(PrivateOutputError, "closed"):
            output.write_text("later.json", "no")

    def test_rejects_path_traversal_and_oversized_payloads(self):
        with create_private_directory(self.root / "run") as output:
            for name in ("../escape", "sub/file", "..", ".", ".git", "C:\\evil", "x\x00y"):
                with self.subTest(name=name), self.assertRaises(PrivateOutputError):
                    output.write_bytes(name, b"secret")
            with patch("aeonith.private_output.MAX_PRIVATE_FILE_BYTES", 4):
                with self.assertRaises(PrivateOutputError):
                    output.write_bytes("giant", b"12345")

    def test_rejects_git_checkout_and_worktree_marker(self):
        checkout = self.root / "repo"
        checkout.mkdir()
        (checkout / ".git").mkdir()
        (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaisesRegex(PrivateOutputError, "Git checkout"):
            create_private_directory(checkout / "private")
        (checkout / ".git" / "HEAD").unlink()
        (checkout / ".git").rmdir()
        (checkout / ".git").write_text("gitdir: /other/location/worktrees/repo\n")
        with self.assertRaisesRegex(PrivateOutputError, "Git checkout"):
            create_private_directory(checkout / "private")

    def test_rejects_symlinked_parent_and_world_writable_nonsticky_parent(self):
        target = self.root / "target"
        target.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            create_private_directory(linked / "run")
        unsafe = self.root / "unsafe"
        unsafe.mkdir()
        unsafe.chmod(0o777)
        with self.assertRaisesRegex(PrivateOutputError, "unsafe replacement"):
            create_private_directory(unsafe / "run")

    def test_descriptor_pinning_survives_pathname_replacement(self):
        destination = self.root / "run"
        with create_private_directory(destination) as output:
            moved = self.root / "moved"
            destination.rename(moved)
            destination.mkdir(mode=0o700)
            output.write_bytes("receipt", b"pinned inode")
            self.assertEqual((moved / "receipt").read_bytes(), b"pinned inode")
            self.assertFalse((destination / "receipt").exists())

    def test_windows_is_fail_closed_even_when_version_supports_0700(self):
        with patch("aeonith.private_output._is_windows", return_value=True):
            with self.assertRaisesRegex(PrivateOutputError, "Windows private output"):
                create_private_directory(self.root / "run")
        self.assertFalse((self.root / "run").exists())


if __name__ == "__main__":
    unittest.main()
