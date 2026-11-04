"""Offline contract tests for the optional, local-only model-training lane."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.corpus import CorpusError, inspect_plan
from training.train_lora import (_require_chat_context, _require_cpu_training, _train, fingerprint_adapter,
                                 verify_declared_base_checkpoint)


REVISION = "a" * 40


def row(identifier: str, prompt: str, *, rights: str = "self_authored") -> dict:
    return {
        "id": identifier,
        "prompt": prompt,
        "completion": f"A grounded reading of {identifier}.",
        "source_id": f"source-{identifier}",
        "rights_basis": rights,
        "permission_to_train": True,
        "permission_to_publish_adapter": True,
    }


class FakeDictDefaultTokenizer:
    """Models Transformers 5.20's default structured chat result."""

    def __init__(self, ids):
        self.ids = ids
        self.calls = []

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt,
                            return_dict=True):
        self.calls.append((tokenize, add_generation_prompt, return_dict))
        if return_dict:
            return {"input_ids": self.ids, "attention_mask": [1] * len(self.ids)}
        return self.ids


class ChatTemplateContextTests(unittest.TestCase):
    def setUp(self):
        self.messages = [{"role": "user", "content": "private"},
                         {"role": "assistant", "content": "private answer"}]

    def test_actual_flat_ids_not_structured_mapping_key_count(self):
        tokenizer = FakeDictDefaultTokenizer([1] * 128)
        self.assertEqual(len(_require_chat_context(tokenizer, self.messages,
                                                   max_length=128, split="train")), 128)
        self.assertEqual(tokenizer.calls, [(True, False, False)])

    def test_context_overflow_refused_even_when_mapping_has_two_fields(self):
        tokenizer = FakeDictDefaultTokenizer([1] * 129)
        with self.assertRaisesRegex(CorpusError, "exceeds max_length"):
            _require_chat_context(tokenizer, self.messages, max_length=128, split="validation")
        self.assertEqual(tokenizer.calls, [(True, False, False)])

    def test_nonflat_or_invalid_token_results_refused(self):
        for ids in ([], [[1, 2]], [True], [1.2], [-1], {"input_ids": [1]}):
            with self.subTest(ids=ids), self.assertRaisesRegex(CorpusError, "flat token ID"):
                _require_chat_context(FakeDictDefaultTokenizer(ids), self.messages,
                                      max_length=128, split="train")


class TrainingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        (self.base / "config.json").write_text(
            json.dumps({"model_type": "qwen3_5", "architectures": ["Qwen3_5ForConditionalGeneration"]}),
            encoding="utf-8",
        )
        (self.base / "weights.safetensors").write_bytes(b"fixture-weights")
        (self.base / "tokenizer.json").write_text('{"version":"1.0"}', encoding="utf-8")
        self.splits = {}
        for split, prompt in [("train", "The rain fell"), ("validation", "A silent street"), ("holdout", "One last letter")]:
            path = self.root / f"{split}.jsonl"
            path.write_text(json.dumps(row(split, prompt)) + "\n", encoding="utf-8")
            self.splits[split] = path.name
        self.plan = {
            "schema_version": "aeonith.training_plan.v1",
            "base_model": {
                "id": "Qwen/Qwen3.5-2B", "revision": REVISION, "local_dir": str(self.base)
            },
            "corpus": self.splits,
            "training": {"max_steps": 2, "max_length": 512, "seed": 17},
        }
        self.plan_path = self.root / "plan.json"
        self.write_plan()

    def write_plan(self) -> None:
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def write_split(self, split: str, *items: dict) -> None:
        (self.root / f"{split}.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
        )

    def test_inspect_is_offline_and_records_only_hashes_counts(self) -> None:
        receipt, dataset = inspect_plan(self.plan_path)
        self.assertEqual(receipt["status"], "validated_not_trained")
        self.assertEqual(receipt["split_counts"], {"train": 1, "validation": 1, "holdout": 1})
        self.assertEqual(set(dataset), {"train", "validation", "holdout"})
        self.assertIn("sha256", receipt["split_files"]["holdout"])
        self.assertNotIn("The rain fell", json.dumps(receipt))
        self.assertNotIn("A grounded reading", json.dumps(receipt))

    def test_official_qwen35_checkpoint_sizes_are_supported(self) -> None:
        # Acceptance of a smaller checkpoint does not prove host training.
        for model_id in ("Qwen/Qwen3.5-0.8B", "Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B"):
            with self.subTest(model_id=model_id):
                self.plan["base_model"]["id"] = model_id
                self.write_plan()
                receipt, _ = inspect_plan(self.plan_path)
                self.assertEqual(receipt["base_model"]["id"], model_id)
                self.assertEqual(receipt["status"], "validated_not_trained")

    def test_rejects_unapproved_qwen35_variant(self) -> None:
        self.plan["base_model"]["id"] = "Qwen/Qwen3.5-0.8B-Base"
        self.write_plan()
        with self.assertRaisesRegex(CorpusError, "unsupported base model"):
            inspect_plan(self.plan_path)

    def test_chat_template_framing_is_fingerprinted(self) -> None:
        template = self.base / "chat_template.jinja"
        template.write_text("{{ messages }}", encoding="utf-8")
        first, _ = inspect_plan(self.plan_path)
        first_files = {item["name"]: item["sha256"] for item in first["base_model"]["files"]}
        self.assertIn("chat_template.jinja", first_files)
        self.assertNotIn("{{ messages }}", json.dumps(first))
        template.write_text("{{ messages | tojson }}", encoding="utf-8")
        second, _ = inspect_plan(self.plan_path)
        second_files = {item["name"]: item["sha256"] for item in second["base_model"]["files"]}
        self.assertNotEqual(first_files["chat_template.jinja"], second_files["chat_template.jinja"])

    def test_rejects_duplicate_prompt_across_splits(self) -> None:
        self.write_split("holdout", row("different-id", "The rain fell"))
        with self.assertRaisesRegex(CorpusError, "overlap"):
            inspect_plan(self.plan_path)

    def test_rejects_unknown_or_unpermitted_rights(self) -> None:
        self.write_split("train", row("train", "The rain fell", rights="unknown"))
        with self.assertRaisesRegex(CorpusError, "rights"):
            inspect_plan(self.plan_path)
        item = row("train", "The rain fell")
        item["permission_to_train"] = False
        self.write_split("train", item)
        with self.assertRaisesRegex(CorpusError, "permission"):
            inspect_plan(self.plan_path)

    def test_private_local_training_does_not_require_adapter_publication_permission(self) -> None:
        # Train consent and adapter-publication consent are independent decisions.
        # Only the latter is withheld here; the corpus remains authorized for
        # local experimentation under the per-record training flags.
        private = row("train", "The rain fell")
        private["permission_to_publish_adapter"] = False
        self.write_split("train", private)

        receipt, _ = inspect_plan(self.plan_path)
        self.assertEqual(receipt["status"], "validated_not_trained")
        self.assertIs(receipt["adapter_publication_record_permissions_complete"], False)
        self.assertEqual(receipt["adapter_publication_status"], "not_permitted_by_corpus")
        self.assertNotIn("The rain fell", json.dumps(receipt))

    def test_publication_policy_requires_every_record_to_opt_in(self) -> None:
        receipt, _ = inspect_plan(self.plan_path)
        self.assertIs(receipt["adapter_publication_record_permissions_complete"], True)
        self.assertEqual(receipt["adapter_publication_status"], "record_permissions_attested_review_required")

        validation = row("validation", "A silent street")
        validation["permission_to_publish_adapter"] = False
        self.write_split("validation", validation)
        receipt, _ = inspect_plan(self.plan_path)
        self.assertIs(receipt["adapter_publication_record_permissions_complete"], False)
        self.assertEqual(receipt["adapter_publication_status"], "not_permitted_by_corpus")

    def test_rejects_non_boolean_publication_permission(self) -> None:
        for invalid in (None, "false", 0, 1):
            with self.subTest(invalid=invalid):
                item = row("train", "The rain fell")
                item["permission_to_publish_adapter"] = invalid
                self.write_split("train", item)
                with self.assertRaisesRegex(CorpusError, "permission"):
                    inspect_plan(self.plan_path)

    def test_rejects_reused_source_id_in_holdout(self) -> None:
        item = row("holdout", "One last letter")
        item["source_id"] = "source-train"
        self.write_split("holdout", item)
        with self.assertRaisesRegex(CorpusError, "source"):
            inspect_plan(self.plan_path)

    def test_rejects_remote_paths_and_unpinned_model(self) -> None:
        self.plan["corpus"]["holdout"] = "https://example.org/data.jsonl"
        self.write_plan()
        with self.assertRaises(CorpusError):
            inspect_plan(self.plan_path)
        self.plan["corpus"]["holdout"] = "holdout.jsonl"
        self.plan["base_model"]["revision"] = "main"
        self.write_plan()
        with self.assertRaisesRegex(CorpusError, "revision"):
            inspect_plan(self.plan_path)

    def test_rejects_empty_split_and_fake_weight_file(self) -> None:
        self.write_split("validation")
        with self.assertRaisesRegex(CorpusError, "empty"):
            inspect_plan(self.plan_path)
        self.write_split("validation", row("validation", "A silent street"))
        (self.base / "weights.safetensors").unlink()
        with self.assertRaisesRegex(CorpusError, "safetensors"):
            inspect_plan(self.plan_path)

    def test_rejects_missing_tokenizer_asset(self) -> None:
        (self.base / "tokenizer.json").unlink()
        with self.assertRaisesRegex(CorpusError, "tokenizer"):
            inspect_plan(self.plan_path)

    def test_cli_dry_run_has_no_training_deps_or_secret_text(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "training.train_lora", "inspect", "--plan", str(self.plan_path)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["status"], "validated_not_trained")
        self.assertNotIn("The rain fell", result.stdout)

    def test_training_requires_explicit_execute(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "training.train_lora", "train", "--plan", str(self.plan_path),
             "--output", str(self.root / "adapter")],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--execute", result.stderr)
        self.assertFalse((self.root / "adapter").exists())

    def test_training_cuda_is_fail_closed_before_loading_optional_dependencies(self) -> None:
        # Even explicit --execute is not proof of an available/exclusive GPU.
        result = subprocess.run(
            [sys.executable, "-m", "training.train_lora", "train", "--plan", str(self.plan_path),
             "--output", str(self.root / "adapter"), "--device", "cuda", "--execute"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("CUDA training is disabled", result.stderr)
        self.assertFalse((self.root / "adapter").exists())
        self.assertNotIn("The rain fell", result.stdout + result.stderr)

    def test_direct_training_api_cannot_bypass_gpu_prohibition(self) -> None:
        with self.assertRaisesRegex(CorpusError, "CUDA training is disabled"):
            _require_cpu_training("cuda")
        with self.assertRaisesRegex(CorpusError, "CUDA training is disabled"):
            _train(self.plan_path, self.root / "adapter", device="cuda")
        self.assertFalse((self.root / "adapter").exists())
        self.assertIsNone(_require_cpu_training("cpu"))

    def test_cpu_train_refuses_unqualified_output_before_expensive_preflight(self) -> None:
        # An unavailable output broker must not waste time hashing a multi-GB
        # model or reading private corpora just to refuse the launch afterward.
        with patch("training.train_lora.inspect_admitted_plan",
                   side_effect=AssertionError("admission/model bytes read before broker gate")):
            with self.assertRaisesRegex(CorpusError, "output custody broker"):
                _train(self.plan_path, self.root / "new-adapter", device="cpu",
                       audit_manifest=self.root / "missing-manifest.json",
                       approval=self.root / "missing-approval.json",
                       admission_receipt=self.root / "missing-receipt.json")
        self.assertFalse((self.root / "new-adapter").exists())

    def test_cpu_training_base_identity_binds_exact_model_revision_and_weights(self) -> None:
        # A small synthetic fixture proves local equality, never publisher origin.
        (self.base / "weights.safetensors").rename(self.base / "model.safetensors")
        expected = self.root / "expected-base.json"
        manifest = {
            "schema_version": "aeonith.expected_base_files.v1",
            "upstream_model_id": self.plan["base_model"]["id"],
            "upstream_revision": REVISION,
            "files": [{"name": path.name, "bytes": path.stat().st_size,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                      for path in sorted(self.base.iterdir())],
        }
        expected.write_text(json.dumps(manifest), encoding="utf-8")
        binding, _ = inspect_plan(self.plan_path)
        receipt = verify_declared_base_checkpoint(self.plan_path, binding, expected)
        self.assertEqual(receipt["status"], "local_bytes_match_supplied_manifest_not_origin_authenticated")
        self.assertIs(receipt["upstream_origin_authenticated"], False)
        (self.base / "model.safetensors").write_bytes(b"substituted")
        with self.assertRaisesRegex(CorpusError, "separately supplied"):
            verify_declared_base_checkpoint(self.plan_path, binding, expected)
        (self.base / "model.safetensors").write_bytes(b"fixture-weights")
        binding["base_model"]["id"] = "Qwen/Qwen3.5-4B"
        with self.assertRaisesRegex(CorpusError, "base identity changed"):
            verify_declared_base_checkpoint(self.plan_path, binding, expected)

    def test_changed_plan_after_preflight_is_rejected_before_base_verifier(self) -> None:
        binding, _ = inspect_plan(self.plan_path)
        # Even a valid-looking plan with a different training seed is a
        # different authorized execution; do not verify/load using its path.
        self.plan["training"]["seed"] += 1
        self.write_plan()
        with patch("training.train_lora.verify_checkpoint",
                   side_effect=AssertionError("base verifier must not run against changed plan")):
            with self.assertRaisesRegex(CorpusError, "plan changed since admitted preflight"):
                verify_declared_base_checkpoint(self.plan_path, binding,
                                                self.root / "expected-base.json")

    def test_train_direct_api_requires_base_manifest_when_other_gates_are_stubbed(self) -> None:
        admitted = {"operator_attested": True}
        preflight = {"base_model": {"id": self.plan["base_model"]["id"], "revision": REVISION}}
        with patch("training.train_lora._require_private_output_broker", return_value=None), \
             patch("training.train_lora.inspect_admitted_plan", return_value=(preflight, {}, admitted)):
            with self.assertRaisesRegex(CorpusError, "expected-base-manifest"):
                _train(self.plan_path, self.root / "adapter", device="cpu",
                       audit_manifest=self.root / "not-present-audit.json",
                       approval=self.root / "not-present-approval.json",
                       admission_receipt=self.root / "not-present-receipt.json")
        self.assertFalse((self.root / "adapter").exists())

    def test_train_cli_keeps_output_custody_gate_first_even_without_base_manifest(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "training.train_lora", "train", "--plan", str(self.plan_path),
             "--output", str(self.root / "adapter"), "--execute",
             "--audit-manifest", str(self.root / "not-present-audit.json"),
             "--approval", str(self.root / "not-present-approval.json"),
             "--admission-receipt", str(self.root / "not-present-receipt.json")],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("output custody broker", result.stderr)
        self.assertFalse((self.root / "adapter").exists())

    def test_fingerprint_adapter_hashes_bytes_without_claiming_quality(self) -> None:
        adapter = self.root / "adapter"
        adapter.mkdir()
        (adapter / "adapter_config.json").write_text('{"peft_type":"LORA"}', encoding="utf-8")
        (adapter / "adapter_model.safetensors").write_bytes(b"an-adapter-fixture")
        files = fingerprint_adapter(adapter)
        self.assertEqual([item["path"] for item in files], ["adapter_config.json", "adapter_model.safetensors"])
        self.assertEqual(files[1]["bytes"], 18)
        self.assertEqual(len(files[1]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
