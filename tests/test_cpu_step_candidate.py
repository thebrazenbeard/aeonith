"""Synthetic contract tests only; no real torch, PEFT or Qwen inference."""

from __future__ import annotations

from contextlib import nullcontext
from unittest import TestCase
from unittest.mock import patch
import json
import math
import struct
import sys
from types import SimpleNamespace

from training.cpu_step_candidate import CandidateStepError, experimental_loaded_cpu_lora_step
from training.private_artifact_broker import PinnedTrainingArtifacts


TRAIN = [{"prompt": "example-private-a", "completion": "answer-private-a"}]
VALIDATION = [{"prompt": "example-private-b", "completion": "answer-private-b"}]


class Parameter:
    def __init__(self, value: float, trainable: bool = True, device: str = "cpu") -> None:
        self.value = value
        self.requires_grad = trainable
        self.device = SimpleNamespace(type=device)
        self.grad = None

    def numel(self):
        return 1

    def detach(self):
        return self

    def to(self, **_):
        return self

    def contiguous(self):
        return self

    def float(self):
        return self

    def abs(self):
        return Parameter(abs(self.value))

    def sum(self):
        return self

    def item(self):
        return self.value

    def numpy(self):
        return self

    def tobytes(self):
        return struct.pack("<f", self.value)


class FakeLoss:
    def __init__(self, value: float, model: "FakeModel") -> None:
        self.value = value
        self.model = model

    def detach(self):
        return self

    def item(self):
        return self.value

    def backward(self):
        self.model.lora.grad = Parameter(self.model.grad_value)


class FakeModel:
    def __init__(self, *, loss: float = 1.0, device: str = "cpu", grad_value: float = 0.1) -> None:
        self.config = SimpleNamespace(model_type="qwen3_5")
        self.peft_config = {"default": SimpleNamespace(to_dict=lambda: {"peft_type": "LORA", "task_type": "CAUSAL_LM"})}
        self.base = Parameter(1.0, trainable=False, device=device)
        self.lora = Parameter(0.0, device=device)
        self.loss = loss
        self.grad_value = grad_value

    def named_parameters(self):
        return [("base.weight", self.base), ("base.lora_A.default.weight", self.lora)]

    def train(self):
        pass

    def eval(self):
        pass

    def __call__(self, **_):
        return SimpleNamespace(loss=FakeLoss(self.loss, self))


class FakeTokenizer:
    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        if add_generation_prompt:
            return [5, 6]
        return [7 if self.broken else 5, 6, 8]


class FakeBroker(PinnedTrainingArtifacts):
    def __init__(self) -> None:
        self.contents = []

    def verify_live(self):
        pass

    def write_receipt(self, value):
        self.contents.append(value)


def fake_torch(*, changes: bool = True, nonfinite_update: bool = False):
    class AdamW:
        def __init__(self, params, lr):
            self.params = params
            self.lr = lr

        def zero_grad(self, *, set_to_none):
            for parameter in self.params:
                parameter.grad = None

        def step(self):
            if changes:
                for parameter in self.params:
                    parameter.value = math.inf if nonfinite_update else parameter.value + self.lr

    return SimpleNamespace(
        optim=SimpleNamespace(AdamW=AdamW),
        long="long", tensor=lambda rows, **_: rows,
        ones_like=lambda rows: [[1 for _ in r] for r in rows],
        isfinite=lambda parameter: SimpleNamespace(
            all=lambda: SimpleNamespace(item=lambda: math.isfinite(parameter.value))),
        no_grad=nullcontext,
    )


class LoadedCPUBridgeTests(TestCase):
    def run_fake(self, *, model=None, tokenizer=None, train=None, validation=None,
                 changes=True, nonfinite_update=False, max_steps=1):
        target = FakeBroker()
        model = model or FakeModel()
        calls = []
        with patch("training.cpu_step_candidate._require_cpu_step_runtime_qualification"), patch.dict(
            sys.modules, {"torch": fake_torch(changes=changes, nonfinite_update=nonfinite_update)}
        ), patch(
            "training.cpu_step_candidate.export_peft_adapter_to_broker",
            side_effect=lambda model, broker: calls.append((model, broker)) or {"status": "fake_export"},
        ):
            result = experimental_loaded_cpu_lora_step(
                model, tokenizer or FakeTokenizer(),
                train if train is not None else TRAIN,
                validation if validation is not None else VALIDATION,
                target, max_steps=max_steps, learning_rate=0.0002,
            )
        return result, target, calls

    def test_synthetic_witness_and_private_receipt(self):
        result, broker, calls = self.run_fake(max_steps=2)
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["changed_lora_tensor_count"], 1)
        self.assertGreater(result["finite_nonzero_lora_gradient_l1_min"], 0)
        self.assertFalse(result["trainer_filesystem_custody_qualified"])
        self.assertTrue(result["holdout_not_supplied_by_interface"])
        self.assertFalse(result["holdout_contamination_verified"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(broker.contents), 1)
        self.assertNotIn("example-private-a", broker.contents[0].decode())
        self.assertNotIn("answer-private-b", broker.contents[0].decode())
        self.assertEqual(json.loads(broker.contents[0])["schema_version"], "aeonith.loaded_cpu_step_candidate.v1")

    def test_split_overlap_refused(self):
        with self.assertRaisesRegex(CandidateStepError, "overlap"):
            self.run_fake(validation=[{"prompt": " EXAMPLE-PRIVATE-A ", "completion": "different"}])

    def test_non_broker_object_refused(self):
        with patch("training.cpu_step_candidate._require_cpu_step_runtime_qualification"):
            with self.assertRaisesRegex(CandidateStepError, "broker"):
                experimental_loaded_cpu_lora_step(FakeModel(), FakeTokenizer(), TRAIN,
                                                  VALIDATION, object(), learning_rate=0.0002)

    def test_public_optimizer_gate_refuses_before_any_runtime_or_output_effect(self):
        with patch.dict(sys.modules, {"torch": fake_torch()}), patch(
            "training.cpu_step_candidate.export_peft_adapter_to_broker"
        ) as export:
            broker = FakeBroker()
            with self.assertRaisesRegex(CandidateStepError, "not qualified"):
                experimental_loaded_cpu_lora_step(FakeModel(), FakeTokenizer(), TRAIN,
                                                  VALIDATION, broker, learning_rate=0.0002)
            export.assert_not_called()
            self.assertEqual(broker.contents, [])

    def test_invalid_completion_or_missing_field_refused(self):
        with self.assertRaisesRegex(CandidateStepError, "fields"):
            self.run_fake(train=[{"prompt": "one"}])

    def test_nonprefix_template_refused_before_optimizer(self):
        with self.assertRaisesRegex(CandidateStepError, "prefix-stable"):
            self.run_fake(tokenizer=FakeTokenizer(broken=True))

    def test_non_cpu_model_refused(self):
        with self.assertRaisesRegex(CandidateStepError, "CPU"):
            self.run_fake(model=FakeModel(device="cuda"))

    def test_nonfinite_loss_refused(self):
        with self.assertRaisesRegex(CandidateStepError, "non-finite CPU training loss"):
            self.run_fake(model=FakeModel(loss=math.inf))

    def test_zero_parameter_update_refused(self):
        with self.assertRaisesRegex(CandidateStepError, "no LoRA parameter changed"):
            self.run_fake(changes=False)

    def test_zero_gradient_refused_before_optimizer_update(self):
        with self.assertRaisesRegex(CandidateStepError, "gradient is zero"):
            self.run_fake(model=FakeModel(grad_value=0.0))

    def test_nonfinite_parameter_update_refused_before_export(self):
        with self.assertRaisesRegex(CandidateStepError, "non-finite LoRA parameter"):
            self.run_fake(nonfinite_update=True)

    def test_no_base_finetuning(self):
        model = FakeModel()
        model.base.requires_grad = True
        with self.assertRaisesRegex(CandidateStepError, "pure-LoRA"):
            self.run_fake(model=model)

    def test_bounds_reject_unbounded_steps(self):
        with self.assertRaisesRegex(CandidateStepError, "invalid bounded"):
            self.run_fake(max_steps=9)
