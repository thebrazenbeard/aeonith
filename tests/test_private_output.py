"""Adversarial tests for the optional private artifact directory boundary."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aeonith.private_output import (
    PrivateOutputDirectory, PrivateOutputError, create_private_directory, reserve_private_file,
)


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

    def test_attacker_owned_sticky_parent_cannot_host_private_outputs(self):
        """Sticky alone cannot protect a child from the parent directory owner.

        CI may run as root; simulate the parent owner's UID without requiring
        root-owned test setup or making real changes to system accounts.
        """
        sticky = self.root / "attacker-owned-sticky"
        sticky.mkdir(mode=0o700)
        sticky.chmod(0o1777)
        real_fstat = os.fstat
        parent = sticky.stat()
        foreign_uid = 4242 if os.geteuid() != 4242 else 4243

        def alternate_owner(fd):
            attrs = real_fstat(fd)
            if (attrs.st_dev, attrs.st_ino) == (parent.st_dev, parent.st_ino):
                return SimpleNamespace(st_mode=attrs.st_mode, st_uid=foreign_uid)
            return attrs

        with patch("aeonith.private_output.os.fstat", side_effect=alternate_owner):
            with self.assertRaisesRegex(PrivateOutputError, "unsafe replacement"):
                create_private_directory(sticky / "run")
            with self.assertRaisesRegex(PrivateOutputError, "unsafe replacement"):
                reserve_private_file(sticky / "private.json")
        self.assertFalse((sticky / "run").exists())
        self.assertFalse((sticky / "private.json").exists())

    def test_owner_controlled_sticky_parent_remains_allowed(self):
        sticky = self.root / "owner-sticky"
        sticky.mkdir(mode=0o700)
        sticky.chmod(0o1777)
        with create_private_directory(sticky / "run") as output:
            output.write_bytes("receipt", b"allowed")
        self.assertEqual((sticky / "run" / "receipt").read_bytes(), b"allowed")

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

    def test_linux_mount_fstype_is_bound_to_fd_mount_id(self):
        from aeonith.private_output import _parse_linux_mount_type
        fdinfo = "pos:\t0\nflags:\t0100000\nmnt_id:\t37\n"
        mountinfo = ("12 1 0:1 / / rw - ext4 /dev/root rw\n"
                     "37 12 0:2 / /mnt/d rw - 9p C:\\ rw\n")
        self.assertEqual(_parse_linux_mount_type(fdinfo, mountinfo), "9p")
        with self.assertRaisesRegex(PrivateOutputError, "mount identity"):
            _parse_linux_mount_type("flags:\t00\n", mountinfo)
        with self.assertRaisesRegex(PrivateOutputError, "mount identity"):
            _parse_linux_mount_type("mnt_id:\t999\n", mountinfo)

    def test_wsl_drvfs_and_remote_mounts_fail_before_file_creation(self):
        for kind in ("9p", "drvfs", "cifs", "nfs4", "fuseblk", "ntfs3"):
            with self.subTest(kind=kind), patch(
                "aeonith.private_output._linux_mount_type_for_fd", return_value=kind
            ):
                with self.assertRaisesRegex(PrivateOutputError, "filesystem is not qualified"):
                    create_private_directory(self.root / "run")
                with self.assertRaisesRegex(PrivateOutputError, "filesystem is not qualified"):
                    reserve_private_file(self.root / "private.json")
            self.assertFalse((self.root / "run").exists())
            self.assertFalse((self.root / "private.json").exists())

    def test_native_ext4_mock_keeps_posix_private_output_enabled(self):
        with patch("aeonith.private_output._linux_mount_type_for_fd", return_value="ext4"):
            with create_private_directory(self.root / "native") as output:
                output.write_bytes("report", b"data")
        self.assertEqual((self.root / "native" / "report").read_bytes(), b"data")

    def test_direct_child_directory_constructor_cannot_skip_mount_check(self):
        child = self.root / "child"
        child.mkdir(mode=0o700)
        fd = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with patch("aeonith.private_output._linux_mount_type_for_fd", return_value="9p"):
                with self.assertRaisesRegex(PrivateOutputError, "filesystem is not qualified"):
                    PrivateOutputDirectory(child, fd)
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
