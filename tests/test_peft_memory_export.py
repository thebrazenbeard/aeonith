"""Synthetic boundary tests; no claim of a real PEFT optimizer or reload."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError
from training.peft_memory_export import export_peft_adapter_to_broker
from training.private_artifact_broker import PinnedTrainingArtifacts


class _PeftKind(str, Enum):
    LORA = "LORA"


class _Config:
    def __init__(self, **replacements):
        self.data = {
            "peft_type": _PeftKind.LORA,
            "task_type": "CAUSAL_LM",
            "inference_mode": False,
            "target_modules": {"q_proj", "v_proj"},
            **replacements,
        }

    def to_dict(self):
        return self.data


class _Model:
    def __init__(self, config=None):
        self.peft_config = {"default": config or _Config()}


class _Tensor:
    def __init__(self):
        self.device = "cuda"

    def detach(self):
        return self

    def to(self, *, device):
        self.device = device
        return self

    def contiguous(self):
        return self


@unittest.skipUnless(sys.platform == "linux", "Linux descriptor-pin tests")
class PeftMemoryExportTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.fake_weights = b"synthetic-safetensors-like-payload"

    def _modules(self, *, state=None, weights=None):
        tensor = _Tensor()
        peft = types.ModuleType("peft")
        peft.get_peft_model_state_dict = lambda _model, adapter_name: (
            {"lora_A.default.weight": tensor} if state is None else state
        )
        safetensors = types.ModuleType("safetensors")
        torch_stub = types.ModuleType("safetensors.torch")

        def save(tensors):
            self.assertEqual(list(tensors), ["lora_A.default.weight"])
            self.assertEqual(tensor.device, "cpu")
            return self.fake_weights if weights is None else weights

        torch_stub.save = save
        safetensors.torch = torch_stub
        return {"peft": peft, "safetensors": safetensors, "safetensors.torch": torch_stub}

    def test_pinned_export_is_private_and_contains_exact_hashed_payloads(self):
        parent = self.root / "parent"
        parent.mkdir(mode=0o700)
        decoy = self.root / "decoy"
        decoy.mkdir(mode=0o700)
        with PinnedTrainingArtifacts.create(parent / "run") as broker:
            parent.rename(self.root / "moved")
            parent.symlink_to(decoy, target_is_directory=True)
            with patch.dict(sys.modules, self._modules()):
                result = export_peft_adapter_to_broker(_Model(), broker)
        adapter = self.root / "moved" / "run" / "adapter"
        self.assertFalse((decoy / "run").exists())
        self.assertEqual(result["status"], "adapter_bytes_exported_not_training_qualified")
        self.assertFalse(result["gradient_update_verified"])
        self.assertFalse(result["fresh_process_reload_qualified"])
        self.assertFalse(result["optimizer_start_authorized"])
        self.assertEqual((adapter / "adapter_model.safetensors").read_bytes(), self.fake_weights)
        config = json.loads((adapter / "adapter_config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["target_modules"], ["q_proj", "v_proj"])
        self.assertEqual(config["peft_type"], "LORA")
        self.assertTrue(config["inference_mode"])
        for record in result["files"]:
            target = adapter / record["path"]
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), record["sha256"])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.stat().st_uid, os.geteuid())

    def test_invalid_adapter_name_or_type_refuses_before_writes(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                with self.assertRaisesRegex(PrivateOutputError, "default"):
                    export_peft_adapter_to_broker(_Model(), broker, adapter_name="other")
                with self.assertRaisesRegex(PrivateOutputError, "only causal LM LoRA"):
                    export_peft_adapter_to_broker(_Model(_Config(peft_type="PREFIX_TUNING")), broker)
            self.assertEqual(list(broker.adapter_path.iterdir()), [])

    def test_oversize_serialized_weights_do_not_create_output(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                with patch("training.peft_memory_export.MAX_PRIVATE_FILE_BYTES", 5):
                    with self.assertRaisesRegex(PrivateOutputError, "exceeds"):
                        export_peft_adapter_to_broker(_Model(), broker)
            self.assertEqual(list(broker.adapter_path.iterdir()), [])

    def test_unsupported_config_and_invalid_state_fail_before_writes(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules(state={})):
                with self.assertRaisesRegex(PrivateOutputError, "empty"):
                    export_peft_adapter_to_broker(_Model(), broker)
            with patch.dict(sys.modules, self._modules()):
                with self.assertRaisesRegex(PrivateOutputError, "field type"):
                    export_peft_adapter_to_broker(_Model(_Config(extra=object())), broker)
            self.assertEqual(list(broker.adapter_path.iterdir()), [])

    def test_duplicate_export_is_exclusive_and_never_overwrites(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                export_peft_adapter_to_broker(_Model(), broker)
                old = (broker.adapter_path / "adapter_model.safetensors").read_bytes()
                with self.assertRaises(PrivateOutputError):
                    export_peft_adapter_to_broker(_Model(), broker)
                self.assertEqual((broker.adapter_path / "adapter_model.safetensors").read_bytes(), old)

    def test_missing_peft_dependency_refuses_without_files(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, {"peft": None}):
                with self.assertRaisesRegex(PrivateOutputError, "local PEFT"):
                    export_peft_adapter_to_broker(_Model(), broker)
            self.assertEqual(list(broker.adapter_path.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
