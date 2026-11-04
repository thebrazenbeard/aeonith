"""Regress actual Qwen3.5 CPU parameter dtype checks before LoRA training."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from training.corpus import CorpusError
from training.train_lora import require_actual_cpu_float32_model


class FakeModel:
    def __init__(self, *parameters):
        self._parameters = parameters

    def named_parameters(self):
        return iter((f"layer.{idx}", param)
                    for idx, param in enumerate(self._parameters))


class ModelDtypeReadbackTests(unittest.TestCase):
    def setUp(self):
        self.torch = SimpleNamespace(float32="torch.float32", bfloat16="torch.bfloat16")

    def param(self, dtype="torch.float32", device="cpu"):
        return SimpleNamespace(dtype=dtype, device=SimpleNamespace(type=device))

    def test_true_cpu_float32_readback_passes(self):
        receipt = require_actual_cpu_float32_model(FakeModel(self.param(), self.param()), self.torch)
        self.assertEqual(receipt, {"cpu_float32_parameter_count": 2})

    def test_silent_bfloat16_load_refused(self):
        with self.assertRaisesRegex(CorpusError, "not CPU float32"):
            require_actual_cpu_float32_model(FakeModel(self.param("torch.bfloat16")), self.torch)

    def test_one_hidden_non_cpu_or_bf16_parameter_refused(self):
        for mismatch in [self.param("torch.bfloat16"), self.param(device="cuda")]:
            with self.subTest(mismatch=mismatch), self.assertRaisesRegex(CorpusError, "not CPU float32"):
                require_actual_cpu_float32_model(FakeModel(self.param(), mismatch), self.torch)

    def test_empty_and_malformed_model_refused(self):
        with self.assertRaisesRegex(CorpusError, "no verifiable"):
            require_actual_cpu_float32_model(FakeModel(), self.torch)
        with self.assertRaisesRegex(CorpusError, "could not be verified"):
            require_actual_cpu_float32_model(FakeModel(SimpleNamespace(dtype="torch.float32")), self.torch)


if __name__ == "__main__":
    unittest.main()
