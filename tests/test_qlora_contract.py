"""Offline source-only contract tests for the experimental 4-bit training lane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.corpus import CorpusError
from training.train_qlora import (
    _headroom, _preflight, _require_host_owned_gpu_allocation, _train,
    _verify_local_base,
)


REPO = Path(__file__).resolve().parents[1]


def item(name: str) -> dict:
    return {
        "id": name, "source_id": f"work-{name}",
        "prompt": f"A private and authorized short original passage {name}.",
        "completion": f"An evidence-grounded private answer {name}.",
        "rights_basis": "self_authored", "permission_to_train": True,
        "permission_to_publish_adapter": False,
    }


class LowMemoryContractTests(unittest.TestCase):
    def test_cuda_phase_gates_require_real_readback_and_conservative_free_space(self) -> None:
        class FakeCUDA:
            def __init__(self, free_mib: int):
                self.free_mib = free_mib

            def mem_get_info(self) -> tuple[int, int]:
                return self.free_mib * 1024 * 1024, 4096 * 1024 * 1024

        for phase, minimum in (("before model loading", 3072),
                               ("after 4-bit model loading", 1536),
                               ("after k-bit preparation", 1024),
                               ("after LoRA insertion", 1024)):
            with self.subTest(phase=phase):
                with self.assertRaisesRegex(CorpusError, "insufficient free CUDA"):
                    _headroom(FakeCUDA(minimum - 1), minimum_mib=minimum, phase=phase)
                available, total = _headroom(FakeCUDA(minimum), minimum_mib=minimum, phase=phase)
                self.assertEqual(available, minimum * 1024 * 1024)
                self.assertEqual(total, 4096 * 1024 * 1024)
        with self.assertRaisesRegex(CorpusError, "readback unavailable"):
            _headroom(object(), minimum_mib=1024, phase="missing sensor")

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "config.json").write_text('{"model_type":"qwen3_5"}', encoding="utf-8")
        (self.base / "model.safetensors").write_bytes(b"synthetic not real weights")
        (self.base / "tokenizer.json").write_text('{"version":"1"}', encoding="utf-8")
        for name in ("train", "validation", "holdout"):
            (self.root / f"{name}.jsonl").write_text(json.dumps(item(name)) + "\n", encoding="utf-8")
        self.plan = {
            "schema_version": "aeonith.training_plan.v1",
            "base_model": {"id": "Qwen/Qwen3.5-0.8B", "revision": "a" * 40,
                           "local_dir": str(self.base)},
            "corpus": {name: f"{name}.jsonl" for name in ("train", "validation", "holdout")},
            "training": {"max_steps": 2, "max_length": 256, "seed": 17},
        }
        self.plan_path = self.root / "plan.json"
        self.write_plan()
        self.expected_base_manifest = self.root / "expected-base.json"
        expected_files = []
        for path in sorted(self.base.iterdir()):
            raw = path.read_bytes()
            expected_files.append({"name": path.name, "bytes": len(raw),
                                   "sha256": hashlib.sha256(raw).hexdigest()})
        self.expected_base_manifest.write_text(json.dumps({
            "schema_version": "aeonith.expected_base_files.v1",
            "upstream_model_id": "Qwen/Qwen3.5-0.8B", "upstream_revision": "a" * 40,
            "files": expected_files,
        }), encoding="utf-8")

    def write_plan(self) -> None:
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def test_private_preflight_validates_and_reports_no_training(self) -> None:
        receipt, splits = _preflight(self.plan_path)
        self.assertEqual(receipt["status"], "validated_not_trained")
        self.assertEqual(receipt["base_model"]["id"], "Qwen/Qwen3.5-0.8B")
        self.assertFalse(receipt["adapter_publication_record_permissions_complete"])
        self.assertEqual([len(splits[name]) for name in ("train", "validation", "holdout")], [1, 1, 1])
        self.assertNotIn("A private and authorized", json.dumps(receipt))

    def test_separately_supplied_base_hashes_are_bound_to_plan(self) -> None:
        check = _verify_local_base(self.plan_path, self.expected_base_manifest)
        self.assertFalse(check["upstream_origin_authenticated"])
        self.assertEqual(check["files_verified"], 3)
        (self.base / "model.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(CorpusError, "do not match"):
            _verify_local_base(self.plan_path, self.expected_base_manifest)

    def test_mismatched_expected_model_revision_is_refused(self) -> None:
        self.plan["base_model"]["revision"] = "b" * 40
        self.write_plan()
        with self.assertRaisesRegex(CorpusError, "do not match"):
            _verify_local_base(self.plan_path, self.expected_base_manifest)

    def test_only_the_small_pinned_qwen_model_is_allowed(self) -> None:
        for model in ("Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B"):
            with self.subTest(model=model):
                self.plan["base_model"]["id"] = model
                self.write_plan()
                with self.assertRaisesRegex(CorpusError, "only official Qwen3.5-0.8B"):
                    _preflight(self.plan_path)

    def test_experimental_steps_and_context_are_bounded(self) -> None:
        self.plan["training"]["max_steps"] = 65
        self.write_plan()
        with self.assertRaisesRegex(CorpusError, "64 steps"):
            _preflight(self.plan_path)
        self.plan["training"]["max_steps"] = 2
        self.plan["training"]["max_length"] = 1024
        self.write_plan()
        with self.assertRaisesRegex(CorpusError, "512 tokens"):
            _preflight(self.plan_path)

    def test_no_training_without_per_record_authorization(self) -> None:
        row = item("train")
        row["permission_to_train"] = False
        (self.root / "train.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(CorpusError, "training permission"):
            _preflight(self.plan_path)

    def test_preflight_rejects_inputs_inside_public_checkout(self) -> None:
        # Cannot write fixture into repo; a source path string is enough.
        self.plan["corpus"]["train"] = str(REPO / "tests" / "fixtures" / "literary_cases.json")
        self.write_plan()
        with self.assertRaises(CorpusError):
            _preflight(self.plan_path)

    def test_inspect_cli_never_requests_execute_or_loads_model(self) -> None:
        output = subprocess.run(
            [sys.executable, "-m", "training.train_qlora", "inspect", "--plan", str(self.plan_path)],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(json.loads(output.stdout)["status"], "validated_not_trained")
        self.assertNotIn("A private and authorized", output.stdout)

    def test_train_is_opt_in_and_does_not_create_output_without_execute(self) -> None:
        dest = self.root / "adapter-run"
        output = subprocess.run(
            [sys.executable, "-m", "training.train_qlora", "train", "--plan", str(self.plan_path),
             "--expected-base-manifest", str(self.expected_base_manifest),
             "--output", str(dest)], cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(output.returncode, 0)
        self.assertIn("--execute", output.stderr)
        self.assertFalse(dest.exists())

    def test_execute_fails_closed_before_cuda_imports_or_output_creation(self) -> None:
        destination = self.root / "never-allocate-cuda"
        output = subprocess.run(
            [sys.executable, "-m", "training.train_qlora", "train", "--plan", str(self.plan_path),
             "--expected-base-manifest", str(self.expected_base_manifest),
             "--output", str(destination), "--execute"],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        self.assertEqual(output.returncode, 2, output.stderr)
        self.assertIn("no host-owned GPU allocation gate", output.stderr)
        self.assertFalse(destination.exists())
        self.assertNotIn("A private and authorized", output.stdout + output.stderr)

    def test_direct_python_api_cannot_bypass_host_allocation_boundary(self) -> None:
        destination = self.root / "never-allocate-cuda-api"
        with self.assertRaisesRegex(CorpusError, "host-owned GPU allocation gate"):
            _require_host_owned_gpu_allocation()
        with self.assertRaisesRegex(CorpusError, "host-owned GPU allocation gate"):
            _train(self.plan_path, destination, self.expected_base_manifest)
        self.assertFalse(destination.exists())

    def test_future_gpu_lease_alone_cannot_bypass_private_output_gate(self) -> None:
        destination = self.root / "still-not-qualified"
        with patch("training.train_qlora._require_host_owned_gpu_allocation"):
            with self.assertRaisesRegex(CorpusError, "private training output custody broker"):
                _train(self.plan_path, destination, self.expected_base_manifest)
        self.assertFalse(destination.exists())

    def test_future_output_qualification_alone_cannot_bypass_admission(self) -> None:
        destination = self.root / "still-no-admission"
        with (patch("training.train_qlora._require_host_owned_gpu_allocation"),
              patch("training.train_qlora._require_private_output_broker"),
              patch("training.train_qlora._offline") as offline,
              patch("training.train_qlora._verify_local_base") as verify_base):
            with self.assertRaisesRegex(CorpusError, "exact corpus audit manifest"):
                _train(self.plan_path, destination, self.expected_base_manifest)
            offline.assert_not_called()
            verify_base.assert_not_called()
        self.assertFalse(destination.exists())

    def test_partial_admission_is_never_accepted_as_verified(self) -> None:
        with self.assertRaisesRegex(CorpusError, "all exact corpus audit"):
            _preflight(self.plan_path, audit_manifest=self.root / "manifest.json")

    def test_future_both_gates_still_require_real_receipt_validation(self) -> None:
        destination = self.root / "no-false-verified-bundle"
        with (patch("training.train_qlora._require_host_owned_gpu_allocation"),
              patch("training.train_qlora._require_private_output_broker"),
              patch("training.train_qlora._offline"),
              patch("training.train_qlora._verify_local_base") as verify_base):
            with self.assertRaisesRegex(CorpusError, "corpus admission verification refused"):
                _train(self.plan_path, destination, self.expected_base_manifest,
                       audit_manifest=self.root / "nonexistent-audit.json",
                       approval=self.root / "nonexistent-approval.json",
                       admission_receipt=self.root / "nonexistent-receipt.json")
            verify_base.assert_not_called()
        self.assertFalse(destination.exists())

    def test_train_destination_rejects_repo_root(self) -> None:
        from training.train_lora import _output_path
        with self.assertRaisesRegex(CorpusError, "outside"):
            _output_path(str(REPO / "training-output" / "trial"))


if __name__ == "__main__":
    unittest.main()
