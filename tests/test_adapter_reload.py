"""Offline, read-only checks for a fresh-process adapter verifier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from training.verify_adapter import (
    VerificationError, _require_cpu_smoke, inspect_adapter_receipt,
    smoke_reload, write_report_exclusive,
)


def _fingerprint(path: Path) -> dict[str, object]:
    contents = path.read_bytes()
    return {"name": path.name, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


class AdapterReloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "config.json").write_text('{"model_type":"qwen3_5"}', encoding="utf-8")
        (self.base / "model.safetensors").write_bytes(b"base weights fixture")
        (self.base / "tokenizer.json").write_text('{"version":"1"}', encoding="utf-8")
        self.adapter = self.root / "adapter"
        self.adapter.mkdir()
        (self.adapter / "adapter_config.json").write_text(
            '{"peft_type":"LORA","task_type":"CAUSAL_LM"}', encoding="utf-8"
        )
        (self.adapter / "adapter_model.safetensors").write_bytes(b"adapter weights fixture")
        self.receipt = self.root / "training_receipt.json"
        self.payload = {
            "schema_version": "aeonith.adapter_receipt.v1",
            "status": "trained_not_literary_quality_qualified",
            "gradient_update_observed": True,
            "changed_trainable_tensor_count": 2,
            "global_step": 1,
            "preflight": {
                "schema_version": "aeonith.training_preflight.v1",
                "base_model": {
                    "id": "Qwen/Qwen3.5-0.8B",
                    "revision_declared_not_remote_verified": "a" * 40,
                    "files": [_fingerprint(self.base / name) for name in
                              ("config.json", "model.safetensors", "tokenizer.json")],
                },
            },
            "adapter_files": [
                {"path": file.name, "bytes": file.stat().st_size,
                 "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                for file in (self.adapter / "adapter_config.json", self.adapter / "adapter_model.safetensors")
            ],
        }
        self.write_receipt()

    def write_receipt(self) -> None:
        self.receipt.write_text(json.dumps(self.payload), encoding="utf-8")

    def test_matching_files_are_only_verified_not_quality_qualified(self) -> None:
        result = inspect_adapter_receipt(self.base, self.adapter, self.receipt)
        self.assertEqual(result["status"], "fingerprints_verified_not_model_qualified")
        self.assertTrue(result["adapter_files_match_receipt"])
        self.assertTrue(result["base_files_match_receipt"])
        self.assertFalse(result["literary_quality_qualified"])
        self.assertNotIn(str(self.base), json.dumps(result))
        self.assertNotIn("adapter weights fixture", json.dumps(result))

    def test_tampered_adapter_rejected(self) -> None:
        (self.adapter / "adapter_model.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(VerificationError, "fingerprint mismatch"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_tampered_base_rejected(self) -> None:
        (self.base / "model.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(VerificationError, "fingerprint mismatch"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_receipt_must_include_tokenizer_provenance(self) -> None:
        self.payload["preflight"]["base_model"]["files"] = [
            item for item in self.payload["preflight"]["base_model"]["files"]
            if item["name"] != "tokenizer.json"
        ]
        self.write_receipt()
        with self.assertRaisesRegex(VerificationError, "base manifest"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_tampered_chat_template_rejected_when_in_receipt(self) -> None:
        template = self.base / "chat_template.jinja"
        template.write_text("{{ messages }}", encoding="utf-8")
        self.payload["preflight"]["base_model"]["files"].append(_fingerprint(template))
        self.write_receipt()
        inspect_adapter_receipt(self.base, self.adapter, self.receipt)
        template.write_text("{{ malicious_change }}", encoding="utf-8")
        with self.assertRaisesRegex(VerificationError, "fingerprint mismatch"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_rejects_unverified_weight_update_claim(self) -> None:
        self.payload["gradient_update_observed"] = False
        self.write_receipt()
        with self.assertRaisesRegex(VerificationError, "gradient"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_rejects_path_traversal_or_duplicate_receipt_files(self) -> None:
        self.payload["adapter_files"][0]["path"] = "../secret.json"
        self.write_receipt()
        with self.assertRaisesRegex(VerificationError, "adapter manifest"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)
        self.payload["adapter_files"][0]["path"] = "adapter_config.json"
        self.payload["adapter_files"].append(self.payload["adapter_files"][0])
        self.write_receipt()
        with self.assertRaisesRegex(VerificationError, "adapter manifest"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_rejects_invalid_adapter_config(self) -> None:
        (self.adapter / "adapter_config.json").write_text('{"peft_type":"PREFIX_TUNING"}', encoding="utf-8")
        changed = (self.adapter / "adapter_config.json").read_bytes()
        self.payload["adapter_files"][0]["bytes"] = len(changed)
        self.payload["adapter_files"][0]["sha256"] = hashlib.sha256(changed).hexdigest()
        self.write_receipt()
        with self.assertRaisesRegex(VerificationError, "adapter configuration"):
            inspect_adapter_receipt(self.base, self.adapter, self.receipt)

    def test_report_is_exclusive_and_outside_checkout(self) -> None:
        destination = self.root / "report.json"
        write_report_exclusive(destination, {"status": "fingerprints_verified_not_model_qualified"})
        self.assertTrue(destination.is_file())
        with self.assertRaises(FileExistsError):
            write_report_exclusive(destination, {"status": "collision"})

    def test_cli_check_does_not_load_ml_packages(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "training.verify_adapter", "check", "--base", str(self.base),
             "--adapter", str(self.adapter), "--receipt", str(self.receipt)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "fingerprints_verified_not_model_qualified")
        self.assertNotIn("adapter weights fixture", result.stdout)

    def test_cli_smoke_requires_explicit_execute(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "training.verify_adapter", "smoke", "--base", str(self.base),
             "--adapter", str(self.adapter), "--receipt", str(self.receipt)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--execute", result.stderr)

    def test_cuda_smoke_rejected_before_loading_model_or_creating_output(self) -> None:
        destination = self.root / "smoke.json"
        result = subprocess.run(
            [sys.executable, "-m", "training.verify_adapter", "smoke", "--base", str(self.base),
             "--adapter", str(self.adapter), "--receipt", str(self.receipt),
             "--device", "cuda", "--execute", "--output", str(destination)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("CUDA smoke verification is disabled", result.stderr)
        self.assertFalse(destination.exists())
        self.assertNotIn("adapter weights fixture", result.stdout + result.stderr)

    def test_direct_smoke_api_cannot_bypass_cuda_prohibition(self) -> None:
        with self.assertRaisesRegex(VerificationError, "CUDA smoke verification is disabled"):
            _require_cpu_smoke("cuda")
        with self.assertRaisesRegex(VerificationError, "CUDA smoke verification is disabled"):
            smoke_reload(self.base, self.adapter, {}, device="cuda", max_new_tokens=1)
        self.assertIsNone(_require_cpu_smoke("cpu"))


if __name__ == "__main__":
    unittest.main()
