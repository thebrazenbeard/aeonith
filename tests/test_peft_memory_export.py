"""Synthetic boundary tests; no claim of a real PEFT optimizer or reload."""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError
from training.peft_memory_export import export_peft_adapter_to_broker
from training.private_artifact_broker import PinnedTrainingArtifacts


def _expect_readback_refusal_in_child(broker, manifest):
    """Separate-process check so a regressed blocking FIFO open cannot hang CI."""
    try:
        broker.verify_adapter_bundle(manifest)
    except PrivateOutputError:
        return
    raise AssertionError("non-regular adapter object was accepted")


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
        self.assertEqual(result["pinned_bytes_readback"]["status"],
                         "point_in_time_private_adapter_readback_not_training_qualified")
        self.assertEqual(result["pinned_bytes_readback"]["files"], result["files"])
        self.assertFalse(result["pinned_bytes_readback"]["atomic_bundle"])
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

    def test_pinned_bundle_readback_refuses_mutation_mode_and_surplus(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                expected = export_peft_adapter_to_broker(_Model(), broker)["files"]
            config = broker.adapter_path / "adapter_config.json"
            original = config.read_bytes()
            config.write_bytes(original + b" ")
            with self.assertRaisesRegex(PrivateOutputError, "identity|readback"):
                broker.verify_adapter_bundle(expected)
            config.write_bytes(original)
            config.chmod(0o644)
            with self.assertRaisesRegex(PrivateOutputError, "access mode"):
                broker.verify_adapter_bundle(expected)
            config.chmod(0o600)
            (broker.adapter_path / "unexpected.json").write_bytes(b"untrusted")
            with self.assertRaisesRegex(PrivateOutputError, "extra files"):
                broker.verify_adapter_bundle(expected)

    def test_interrupted_bundle_never_promotes_partial_bytes(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            original_write = broker.write_adapter_bytes

            def fail_config(name, payload):
                if name == "adapter_config.json":
                    raise PrivateOutputError("injected interruption")
                return original_write(name, payload)

            with patch.dict(sys.modules, self._modules()):
                with patch.object(broker, "write_adapter_bytes", side_effect=fail_config):
                    with self.assertRaisesRegex(PrivateOutputError, "injected interruption"):
                        export_peft_adapter_to_broker(_Model(), broker)
            self.assertEqual(set(os.listdir(broker.adapter_path)), {"adapter_model.safetensors"})
            expected = [
                {"path": "adapter_model.safetensors", "bytes": len(self.fake_weights),
                 "sha256": hashlib.sha256(self.fake_weights).hexdigest()},
                {"path": "adapter_config.json", "bytes": 1,
                 "sha256": "0" * 64},
            ]
            with self.assertRaisesRegex(PrivateOutputError, "incomplete"):
                broker.verify_adapter_bundle(expected)

    def test_readback_requires_exact_bounded_manifest(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                expected = export_peft_adapter_to_broker(_Model(), broker)["files"]
            altered = [dict(item) for item in expected]
            altered[0]["bytes"] = True
            with self.assertRaisesRegex(PrivateOutputError, "digest or size"):
                broker.verify_adapter_bundle(altered)
            altered = [dict(item) for item in expected]
            altered[1]["sha256"] = "F" * 64
            with self.assertRaisesRegex(PrivateOutputError, "digest or size"):
                broker.verify_adapter_bundle(altered)
            altered = [dict(item) for item in expected]
            altered[1]["path"] = ["adapter_config.json"]
            with self.assertRaisesRegex(PrivateOutputError, "expected artifacts"):
                broker.verify_adapter_bundle(altered)

    def test_replaced_adapter_fifo_refuses_without_hanging(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                manifest = export_peft_adapter_to_broker(_Model(), broker)["files"]
            config = broker.adapter_path / "adapter_config.json"
            config.unlink()
            os.mkfifo(config, 0o600)
            child = multiprocessing.get_context("fork").Process(
                target=_expect_readback_refusal_in_child, args=(broker, manifest))
            child.start()
            child.join(2.0)
            try:
                self.assertFalse(child.is_alive(), "readback blocked on attacker FIFO")
                self.assertEqual(child.exitcode, 0)
            finally:
                if child.is_alive():
                    child.terminate()
                    child.join(2.0)

    def test_replaced_adapter_directory_and_symlink_refuse(self):
        with PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                manifest = export_peft_adapter_to_broker(_Model(), broker)["files"]
            config = broker.adapter_path / "adapter_config.json"
            config.unlink()
            config.mkdir(mode=0o700)
            with self.assertRaises(PrivateOutputError):
                broker.verify_adapter_bundle(manifest)
            config.rmdir()
            config.symlink_to(broker.adapter_path / "adapter_model.safetensors")
            with self.assertRaises(PrivateOutputError):
                broker.verify_adapter_bundle(manifest)

    def test_replaced_adapter_socket_refuses_if_socket_creation_permitted(self):
        try:
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except PermissionError:
            self.skipTest("sandbox disallows AF_UNIX socket creation")
        with endpoint, PinnedTrainingArtifacts.create(self.root / "run") as broker:
            with patch.dict(sys.modules, self._modules()):
                manifest = export_peft_adapter_to_broker(_Model(), broker)["files"]
            config = broker.adapter_path / "adapter_config.json"
            config.unlink()
            endpoint.bind(str(config))
            with self.assertRaises(PrivateOutputError):
                broker.verify_adapter_bundle(manifest)


if __name__ == "__main__":
    unittest.main()
