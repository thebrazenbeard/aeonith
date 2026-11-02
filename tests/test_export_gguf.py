"""Offline source-only GGUF handoff; all model and converter bytes are fake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.export_gguf import HandoffError, _require_private_directory_permissions, inspect_handoff, prepare_handoff


REVISION = "b" * 40


def fp(path: Path) -> dict:
    data = path.read_bytes()
    return {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class GGUFHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "config.json").write_text('{"model_type":"qwen3_5"}', encoding="utf-8")
        (self.base / "model.safetensors").write_bytes(b"synthetic only base")
        (self.base / "tokenizer.json").write_text('{"version":"1"}', encoding="utf-8")
        files = [fp(self.base / name) for name in ("config.json", "model.safetensors", "tokenizer.json")]
        self.expected = self.root / "upstream-files.json"
        self.expected.write_text(json.dumps({
            "schema_version": "aeonith.expected_base_files.v1",
            "upstream_model_id": "Qwen/Qwen3.5-0.8B", "upstream_revision": REVISION,
            "files": files,
        }), encoding="utf-8")
        self.adapter = self.root / "adapter"
        self.adapter.mkdir()
        (self.adapter / "adapter_config.json").write_text(
            '{"peft_type":"LORA","task_type":"CAUSAL_LM"}', encoding="utf-8")
        (self.adapter / "adapter_model.safetensors").write_bytes(b"synthetic only adapter")
        self.receipt = self.root / "training_receipt.json"
        self.receipt.write_text(json.dumps({
            "schema_version": "aeonith.adapter_receipt.v1",
            "status": "trained_not_literary_quality_qualified",
            "gradient_update_observed": True, "changed_trainable_tensor_count": 2,
            "global_step": 1,
            "preflight": {"schema_version": "aeonith.training_preflight.v1",
                          "base_model": {"id": "Qwen/Qwen3.5-0.8B",
                                         "revision_declared_not_remote_verified": REVISION,
                                         "files": files}},
            "adapter_files": [{"path": file.name, "bytes": file.stat().st_size,
                               "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                              for file in (self.adapter / "adapter_config.json", self.adapter / "adapter_model.safetensors")],
        }), encoding="utf-8")
        self.script = self.root / "convert_lora_to_gguf.py"
        self.script.write_text("raise AssertionError('converter must never execute during source-only tests')\n", encoding="utf-8")
        self.script_hash = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.out = self.root / "gguf-recipe"

    def inspect(self):
        return inspect_handoff(self.base, self.adapter, self.receipt,
                               self.expected, self.script, self.script_hash)[0]

    def test_report_is_truthful_and_contains_no_private_paths(self):
        report = self.inspect()
        self.assertEqual(report["status"], "matching_local_artifacts_recipe_only_not_converted")
        self.assertTrue(report["adapter_fingerprints_match_receipt"])
        self.assertFalse(report["gguf_artifact_created"])
        self.assertFalse(report["upstream_origin_authenticated"])
        self.assertFalse(report["qwen35_lora_gguf_conversion_compatibility_qualified"])
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertFalse(self.out.exists())

    def test_private_plan_contains_explicit_offline_unexecuted_argv(self):
        report = prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                                 self.script, self.script_hash, self.out)
        self.assertEqual(report["status"], "private_recipe_prepared_not_executed")
        plan = json.loads((self.out / "handoff_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["conversion_env"]["HF_HUB_OFFLINE"], "1")
        self.assertIn("--base", plan["conversion_argv_not_executed"])
        self.assertIn("--outtype", plan["conversion_argv_not_executed"])
        # Windows CI may create its temp root through an 8.3 alias while the
        # guarded planner intentionally resolves to the canonical long path.
        self.assertIn(str(self.adapter.resolve()), plan["conversion_argv_not_executed"])
        self.assertTrue(plan["conversion_operator_approval_required"])
        self.assertFalse(any(self.out.glob("*.gguf")))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_output_refuses_overwrite(self):
        self.out.mkdir()
        marker = self.out / "keep.txt"
        marker.write_text("don't overwrite", encoding="utf-8")
        with self.assertRaisesRegex(HandoffError, "new directory"):
            prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                            self.script, self.script_hash, self.out)
        self.assertEqual(marker.read_text(encoding="utf-8"), "don't overwrite")

    def test_windows_legacy_python_refuses_private_plan_before_creation(self):
        with patch("training.export_gguf.sys.platform", "win32"):
            with patch("training.export_gguf.sys.version_info", (3, 12, 9)):
                with self.assertRaisesRegex(HandoffError, "Python 3.13\\+"):
                    prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                                    self.script, self.script_hash, self.out)
            with patch("training.export_gguf.sys.version_info", (3, 13, 0)):
                _require_private_directory_permissions()
        self.assertFalse(self.out.exists())

    def test_bad_converter_digest_rejected(self):
        with self.assertRaisesRegex(HandoffError, "fingerprint mismatch"):
            inspect_handoff(self.base, self.adapter, self.receipt, self.expected,
                            self.script, "0" * 64)
        self.assertFalse(self.out.exists())

    def test_adapter_tamper_fails_before_output(self):
        (self.adapter / "adapter_model.safetensors").write_bytes(b"tampered")
        with self.assertRaisesRegex(HandoffError, "receipts"):
            prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                            self.script, self.script_hash, self.out)
        self.assertFalse(self.out.exists())

    def test_independent_manifest_and_training_receipt_must_agree(self):
        expected = json.loads(self.expected.read_text(encoding="utf-8"))
        expected["upstream_revision"] = "c" * 40
        self.expected.write_text(json.dumps(expected), encoding="utf-8")
        with self.assertRaisesRegex(HandoffError, "receipts"):
            self.inspect()

    def test_checkout_outputs_are_rejected(self):
        checkout = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(HandoffError, "outside"):
            prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                            self.script, self.script_hash, checkout / "dont-create-gguf-plan")

    def test_output_cannot_modify_checkpoint_or_adapter_directories(self):
        with self.assertRaisesRegex(HandoffError, "overlap"):
            prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                            self.script, self.script_hash, self.base / "recipe")
        with self.assertRaisesRegex(HandoffError, "overlap"):
            prepare_handoff(self.base, self.adapter, self.receipt, self.expected,
                            self.script, self.script_hash, self.adapter / "recipe")
        self.assertFalse((self.base / "recipe").exists())
        self.assertFalse((self.adapter / "recipe").exists())

    def test_symlink_converter_is_rejected(self):
        sym = self.root / "link"
        try:
            sym.symlink_to(self.script)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not available")
        with self.assertRaisesRegex(HandoffError, "symlinks"):
            inspect_handoff(self.base, self.adapter, self.receipt, self.expected, sym, self.script_hash)

    def test_cli_inspection_offline_with_no_output_directory(self):
        proc = subprocess.run([
            sys.executable, "-m", "training.export_gguf", "--base", str(self.base),
            "--adapter", str(self.adapter), "--receipt", str(self.receipt),
            "--base-manifest", str(self.expected), "--converter", str(self.script),
            "--converter-sha256", self.script_hash,
        ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "matching_local_artifacts_recipe_only_not_converted")
        self.assertFalse(self.out.exists())
        self.assertNotIn(str(self.root), proc.stdout)

    def test_cli_prepare_is_explicit_and_never_runs_converter(self):
        invocation = [
            sys.executable, "-m", "training.export_gguf", "--base", str(self.base),
            "--adapter", str(self.adapter), "--receipt", str(self.receipt),
            "--base-manifest", str(self.expected), "--converter", str(self.script),
            "--converter-sha256", self.script_hash,
        ]
        blocked = subprocess.run(invocation + ["--output", str(self.out)],
                                 cwd=Path(__file__).resolve().parents[1],
                                 capture_output=True, text=True, check=False)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertFalse(self.out.exists())
        prepared = subprocess.run(invocation + ["--prepare", "--output", str(self.out)],
                                  cwd=Path(__file__).resolve().parents[1],
                                  capture_output=True, text=True, check=False)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertTrue((self.out / "handoff_plan.json").is_file())
        self.assertFalse(any(self.out.glob("*.gguf")))
        self.assertEqual(json.loads(prepared.stdout)["status"], "private_recipe_prepared_not_executed")
        self.assertNotIn(str(self.root), prepared.stdout)


if __name__ == "__main__":
    unittest.main()
