"""Synthetic, read-only Linux private-input file-descriptor custody tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError
from training.private_input import PinnedPrivateInput, PrivateInputError


@unittest.skipUnless(sys.platform == "linux", "Linux pinned filesystem boundary only")
class PinnedPrivateInputTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.parent = self.root / "private"
        self.parent.mkdir(mode=0o700)
        self.source = self.parent / "train.jsonl"
        self.data = b'{"synthetic":"not a private manuscript"}\n'
        self.source.write_bytes(self.data)
        self.source.chmod(0o600)

    def test_native_pinned_read_hashes_exact_bytes_without_path_leak(self) -> None:
        with PinnedPrivateInput.open(self.source, max_bytes=1024) as opened:
            self.assertEqual(opened.read_bytes(), self.data)
            self.assertEqual(opened.fingerprint(), {
                "bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest(),
            })
        with self.assertRaisesRegex(PrivateInputError, "closed"):
            opened.read_bytes()

    def test_ancestor_swap_cannot_redirect_already_open_input(self) -> None:
        decoy_dir = self.root / "decoy"
        decoy_dir.mkdir(mode=0o700)
        decoy = decoy_dir / self.source.name
        decoy.write_bytes(b"decoy source")
        decoy.chmod(0o600)
        with PinnedPrivateInput.open(self.source, max_bytes=1024) as opened:
            self.parent.rename(self.root / "pinned")
            self.parent.symlink_to(decoy_dir, target_is_directory=True)
            self.assertEqual(opened.read_bytes(), self.data)
        self.assertEqual(decoy.read_bytes(), b"decoy source")

    def test_shared_dup_seeks_cannot_change_snapshot_byte_order(self) -> None:
        # os.read shares the open-file description's seek pointer with dup().
        # Force a competing consumer to move it between two 1 MiB reads.
        payload = b"A" * (1024 * 1024) + b"distinct-tail"
        self.source.write_bytes(payload)
        self.source.chmod(0o600)
        with PinnedPrivateInput.open(self.source, max_bytes=len(payload)) as opened:
            duplicate = os.dup(opened._fd)
            self.addCleanup(lambda: os.close(duplicate))
            actual_pread = os.pread
            reads = 0

            def competing_pread(fd: int, count: int, offset: int) -> bytes:
                nonlocal reads
                block = actual_pread(fd, count, offset)
                reads += 1
                if reads == 1:
                    os.lseek(duplicate, 0, os.SEEK_END)
                return block

            with patch("training.private_input.os.pread", side_effect=competing_pread):
                self.assertEqual(opened.read_bytes(), payload)
            self.assertGreaterEqual(reads, 2)

    def test_refuses_leaf_and_ancestor_symlinks(self) -> None:
        leaf = self.parent / "link.jsonl"
        leaf.symlink_to(self.source)
        with self.assertRaises(PrivateInputError):
            PinnedPrivateInput.open(leaf, max_bytes=1024)
        ancestor = self.root / "alias"
        ancestor.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(PrivateInputError):
            PinnedPrivateInput.open(ancestor / self.source.name, max_bytes=1024)

    def test_refuses_nonprivate_and_multilink_input(self) -> None:
        self.source.chmod(0o644)
        with self.assertRaises(PrivateInputError):
            PinnedPrivateInput.open(self.source, max_bytes=1024)
        self.source.chmod(0o600)
        os.link(self.source, self.parent / "another-name")
        with self.assertRaises(PrivateInputError):
            PinnedPrivateInput.open(self.source, max_bytes=1024)

    def test_refuses_changed_opened_inode_even_when_path_still_valid(self) -> None:
        with PinnedPrivateInput.open(self.source, max_bytes=1024) as opened:
            with self.source.open("ab") as writer:
                writer.write(b"mutation")
            with self.assertRaisesRegex(PrivateInputError, "changed"):
                opened.read_bytes()

    def test_refuses_unsafe_mount_with_owner_bits_present(self) -> None:
        with patch("training.private_input._require_local_posix_mount",
                   side_effect=PrivateOutputError("9p/DrvFS")):
            with self.assertRaisesRegex(PrivateInputError, "mount"):
                PinnedPrivateInput.open(self.source, max_bytes=1024)

    def test_refuses_unbounded_and_traversal_input(self) -> None:
        with self.assertRaisesRegex(PrivateInputError, "size limit"):
            PinnedPrivateInput.open(self.source, max_bytes=0)
        with self.assertRaisesRegex(PrivateInputError, "traversal-free"):
            PinnedPrivateInput.open(self.parent / ".." / "private" / "train.jsonl", max_bytes=1024)
        with self.assertRaisesRegex(PrivateInputError, "exceeds"):
            PinnedPrivateInput.open(self.source, max_bytes=2)


if __name__ == "__main__":
    unittest.main()
