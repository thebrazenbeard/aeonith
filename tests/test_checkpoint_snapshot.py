"""Synthetic adversarial tests, not a real model/host custody qualification."""

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from training.checkpoint_snapshot import (
    CheckpointSnapshotError, materialize_verified_snapshot,
)


REVISION = "f" * 40
MODEL = "Qwen/Qwen3.5-0.8B"


@unittest.skipUnless(os.name == "posix" and os.path.exists("/proc/self/fd"),
                     "requires native Linux descriptors")
class CheckpointSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aeonith-snapshot-custody-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "original"
        self.src.mkdir(mode=0o700)
        self.out = self.root / "snapshot"
        self.manifest = self.root / "expected.json"
        self.files = {
            "config.json": b'{"model_type":"qwen3_5"}',
            "tokenizer.json": b'{"version":"1.0"}',
            "model.safetensors": b"synthetic-not-an-actual-safetensors-file",
        }
        self.write_source()

    def write_source(self):
        for name, content in self.files.items():
            (self.src / name).write_bytes(content)
        self.manifest.write_text(json.dumps({
            "schema_version": "aeonith.expected_base_files.v1",
            "upstream_model_id": MODEL,
            "upstream_revision": REVISION,
            "files": [
                {"name": name, "bytes": len(content),
                 "sha256": hashlib.sha256(content).hexdigest()}
                for name, content in sorted(self.files.items())
            ],
        }), encoding="utf-8")

    def materialize(self):
        return materialize_verified_snapshot(self.src, self.manifest, self.out,
                                              expected_model=MODEL, expected_revision=REVISION,
                                              max_total_bytes=10 * 1024 * 1024)

    def test_exclusive_owner_private_digest_checked_snapshot(self):
        result = self.materialize()
        self.assertEqual(result["status"], "source_bytes_copied_and_digest_checked_not_training_qualified")
        self.assertEqual(result["files_copied"], 3)
        self.assertFalse(result["publisher_origin_authenticated"])
        self.assertFalse(result["model_loader_custody_qualified"])
        self.assertFalse(result["optimizer_authorized"])
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o700)
        for name, value in self.files.items():
            path = self.out / name
            self.assertEqual(path.read_bytes(), value)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)

    def test_rejects_wrong_manifest_hash_with_private_incomplete_preserved(self):
        (self.src / "model.safetensors").write_bytes(b"corrupted-in-flight")
        with self.assertRaises(CheckpointSnapshotError):
            self.materialize()
        self.assertTrue(self.out.is_dir())
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o700)

    def test_rejects_source_symlink_leaf(self):
        (self.src / "model.safetensors").unlink()
        (self.src / "model.safetensors").symlink_to(self.root / "outside")
        with self.assertRaises(CheckpointSnapshotError):
            self.materialize()
        self.assertFalse(self.out.exists())

    def test_rejects_too_small_budget_before_output_side_effect(self):
        with self.assertRaisesRegex(CheckpointSnapshotError, "byte budget"):
            materialize_verified_snapshot(self.src, self.manifest, self.out,
                                          expected_model=MODEL, expected_revision=REVISION,
                                          max_total_bytes=1)
        self.assertFalse(self.out.exists())

    def test_rejects_second_run_without_overwrite(self):
        self.materialize()
        with self.assertRaises((CheckpointSnapshotError, FileExistsError)):
            self.materialize()
        self.assertEqual((self.out / "config.json").read_bytes(), self.files["config.json"])

    def test_rejects_source_ancestor_swap_and_does_not_copy_decoy(self):
        from training import checkpoint_snapshot as module

        original = module._open_source_dir
        moved = self.root / "moved-original"
        decoy = self.root / "decoy"
        decoy.mkdir(mode=0o700)
        (decoy / "config.json").write_bytes(b"decoy")

        def swap_after_pin(path):
            fd = original(path)
            self.src.rename(moved)
            self.src.symlink_to(decoy, target_is_directory=True)
            return fd

        with patch.object(module, "_open_source_dir", side_effect=swap_after_pin):
            with self.assertRaises(CheckpointSnapshotError):
                self.materialize()
        self.assertEqual((decoy / "config.json").read_bytes(), b"decoy")
        self.assertEqual((self.out / "config.json").read_bytes(), self.files["config.json"])

    def test_rejects_destination_ancestor_swap_without_decoy_write(self):
        from training import checkpoint_snapshot as module

        original = module.create_private_directory
        moved = self.root / "moved-snapshot"
        decoy = self.root / "decoy"
        decoy.mkdir(mode=0o700)

        def swap_after_create(path):
            handle = original(path)
            self.out.rename(moved)
            self.out.symlink_to(decoy, target_is_directory=True)
            return handle

        with patch.object(module, "create_private_directory", side_effect=swap_after_create):
            with self.assertRaises(CheckpointSnapshotError):
                self.materialize()
        self.assertEqual(list(decoy.iterdir()), [])
        self.assertEqual((moved / "config.json").read_bytes(), self.files["config.json"])

    def test_rejects_source_mutation_during_streaming(self):
        from training import checkpoint_snapshot as module

        original = module.os.pread
        changed = False

        def mutate_after_read(fd, count, offset):
            nonlocal changed
            block = original(fd, count, offset)
            if not changed and len(block) == len(self.files["model.safetensors"]):
                changed = True
                (self.src / "model.safetensors").write_bytes(b"different checkpoint bytes")
            return block

        with patch.object(module.os, "pread", side_effect=mutate_after_read):
            with self.assertRaises(CheckpointSnapshotError):
                self.materialize()
        self.assertTrue(changed)

    def test_rejects_corrupted_destination_readback(self):
        from training import checkpoint_snapshot as module

        original = module.os.write
        altered = False

        def corrupt_write(fd, data):
            nonlocal altered
            chunk = bytes(data)
            if not altered and chunk == self.files["config.json"]:
                altered = True
                chunk = b"X" + chunk[1:]
            return original(fd, chunk)

        with patch.object(module.os, "write", side_effect=corrupt_write):
            with self.assertRaisesRegex(CheckpointSnapshotError, "output differs"):
                self.materialize()
        self.assertTrue(altered)
        self.assertTrue(self.out.is_dir())

    def test_rejects_unqualified_mount_even_with_owner_bits(self):
        from training import checkpoint_snapshot as module

        with patch.object(module, "_require_local_posix_mount", side_effect=module.PrivateOutputError("9p")):
            with self.assertRaises(CheckpointSnapshotError):
                self.materialize()
        self.assertFalse(self.out.exists())

    def test_refuses_checkpoint_source_inside_a_git_checkout(self):
        marker = self.src / ".git"
        marker.mkdir()
        (marker / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        with self.assertRaises(CheckpointSnapshotError):
            self.materialize()
        self.assertFalse(self.out.exists())

    def test_rejects_wrong_qwen_architecture_after_bounded_copy(self):
        self.files["config.json"] = b'{"model_type":"qwen3"}'
        self.write_source()
        with self.assertRaisesRegex(CheckpointSnapshotError, "not Qwen3.5"):
            self.materialize()
        self.assertTrue(self.out.is_dir())

    def test_rejects_undeclared_runtime_file(self):
        (self.src / "tokenizer_config.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(CheckpointSnapshotError, "exact runtime files"):
            self.materialize()
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
