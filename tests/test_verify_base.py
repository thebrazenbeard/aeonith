"""Synthetic, offline checkpoint-manifest verification contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from training.verify_base import BaseVerificationError, verify_checkpoint


MODEL = "Qwen/Qwen3.5-0.8B"
REVISION = "b" * 40


class BaseVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.base = self.root / "model"
        self.base.mkdir()
        self.manifest_path = self.root / "upstream.json"
        (self.base / "config.json").write_text('{"model_type":"qwen3_5"}', encoding="utf-8")
        (self.base / "tokenizer.json").write_text('{"version":"1"}', encoding="utf-8")
        (self.base / "tokenizer_config.json").write_text('{"chat_template":"{{ messages }}"}', encoding="utf-8")
        (self.base / "model.safetensors").write_bytes(b"synthetic-not-real-weights")
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest = {
            "schema_version": "aeonith.expected_base_files.v1",
            "upstream_model_id": MODEL,
            "upstream_revision": REVISION,
            "files": [
                {"name": path.name, "bytes": path.stat().st_size,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(self.base.iterdir()) if path.is_file()
            ],
        }
        self.dump_manifest()

    def dump_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def verify(self) -> dict:
        return verify_checkpoint(self.base, self.manifest_path,
                                 expected_model=MODEL, expected_revision=REVISION)

    def test_local_byte_exact_match_is_not_claimed_as_upstream_authentication(self) -> None:
        receipt = self.verify()
        self.assertEqual(receipt["status"], "local_bytes_match_supplied_manifest_not_origin_authenticated")
        self.assertEqual(receipt["files_verified"], 4)
        self.assertEqual(receipt["weight_shards_verified"], 1)
        self.assertFalse(receipt["upstream_origin_authenticated"])
        self.assertFalse(receipt["host_training_qualified"])
        self.assertNotIn(str(self.root), json.dumps(receipt))
        self.assertNotIn("synthetic-not-real-weights", json.dumps(receipt))

    def test_tampered_weights_or_tokenizer_are_rejected(self) -> None:
        for name in ("model.safetensors", "tokenizer.json", "tokenizer_config.json"):
            with self.subTest(name=name):
                path = self.base / name
                original = path.read_bytes()
                path.write_bytes(original + b"X")
                with self.assertRaisesRegex(BaseVerificationError, "fingerprint mismatch"):
                    self.verify()
                path.write_bytes(original)

    def test_forged_revision_and_model_claims_rejected(self) -> None:
        self.manifest["upstream_revision"] = "a" * 40
        self.dump_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "revision"):
            self.verify()
        self.manifest["upstream_revision"] = REVISION
        self.manifest["upstream_model_id"] = "Attacker/Untrusted"
        self.dump_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "model"):
            self.verify()

    def test_extra_unfingerprinted_runtime_file_rejected(self) -> None:
        (self.base / "chat_template.jinja").write_text("{{ malicious }}", encoding="utf-8")
        with self.assertRaisesRegex(BaseVerificationError, "manifest does not cover"):
            self.verify()

    def test_missing_manifest_fingerprint_rejected(self) -> None:
        self.manifest["files"] = [row for row in self.manifest["files"] if row["name"] != "tokenizer.json"]
        self.dump_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "manifest does not cover"):
            self.verify()

    def test_rejects_non_filename_traversal_or_duplicate_manifest(self) -> None:
        self.manifest["files"][0]["name"] = "../config.json"
        self.dump_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "filename"):
            self.verify()
        self.write_manifest()
        self.manifest["files"].append(dict(self.manifest["files"][0]))
        self.dump_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "duplicate"):
            self.verify()

    def test_duplicate_json_keys_rejected(self) -> None:
        self.manifest_path.write_text('{"schema_version":"a","schema_version":"b"}', encoding="utf-8")
        with self.assertRaisesRegex(BaseVerificationError, "duplicate"):
            self.verify()

    def test_symlinked_weight_rejected_without_following(self) -> None:
        original = self.base / "model.safetensors"
        external = self.root / "external.safetensors"
        external.write_bytes(original.read_bytes())
        original.unlink()
        try:
            original.symlink_to(external)
        except (NotImplementedError, OSError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaisesRegex(BaseVerificationError, "symlink"):
            self.verify()

    def test_sharded_index_must_reference_every_exact_shard(self) -> None:
        (self.base / "model.safetensors").unlink()
        (self.base / "model-00001-of-00002.safetensors").write_bytes(b"part-one")
        (self.base / "model-00002-of-00002.safetensors").write_bytes(b"part-two")
        index = {"metadata": {"total_size": 16}, "weight_map": {
            "model.foo": "model-00001-of-00002.safetensors",
            "model.bar": "model-00002-of-00002.safetensors"}}
        (self.base / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
        self.write_manifest()
        self.assertEqual(self.verify()["weight_shards_verified"], 2)
        # An index that silently omits a shard must not pass even if all files hash.
        index["weight_map"].pop("model.bar")
        (self.base / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
        self.write_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "shard"):
            self.verify()

    def test_missing_indexed_shard_is_rejected(self) -> None:
        index = {"weight_map": {"foo": "model-00001-of-00002.safetensors"}}
        (self.base / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
        self.write_manifest()
        with self.assertRaisesRegex(BaseVerificationError, "shard"):
            self.verify()

    def test_cli_inspect_offline_does_not_print_local_paths(self) -> None:
        run = subprocess.run([sys.executable, "-m", "training.verify_base", "--base", str(self.base),
                              "--manifest", str(self.manifest_path), "--expected-model", MODEL,
                              "--expected-revision", REVISION],
                             cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                             check=False, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn(str(self.root), run.stdout)
        self.assertEqual(json.loads(run.stdout)["files_verified"], 4)


if __name__ == "__main__":
    unittest.main()
