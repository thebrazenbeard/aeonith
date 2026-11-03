"""Experimental in-memory CPU LoRA step on an already-loaded PEFT model.

This module is deliberately not connected to ``train_lora train``.  It does
not authorize source rights, authenticate a checkpoint, reserve host RAM, or
qualify third-party library I/O.  The production gate remains fail-closed.

The narrow goal is to replace TRL's path-based Trainer/checkpoint writes with
an explicit PyTorch optimizer loop and the existing pinned adapter-byte sink.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from aeonith.private_output import PrivateOutputError
from .peft_memory_export import export_peft_adapter_to_broker
from .private_artifact_broker import PinnedTrainingArtifacts


class CandidateStepError(ValueError):
    """The experimental loaded-model CPU step is not safe to execute."""


MAX_STEPS = 8
MAX_TOKENS = 512
MAX_TRAINABLE_PARAMETERS = 4_000_000


def _require_cpu_step_runtime_qualification() -> None:
    """Fail closed until input/base/host/runtime security is proven.

    A caller's flag cannot replace host authority. Synthetic unit tests patch
    this guard solely to inspect the candidate's otherwise-unreachable flow.
    """
    raise CandidateStepError(
        "loaded-model CPU optimizer is not qualified: protected source input, "
        "immutable checkpoint custody and host-owned resource authority missing"
    )


def _examples(rows: Sequence[Mapping[str, Any]], label: str) -> list[tuple[str, str]]:
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 1024:
        raise CandidateStepError(f"{label} must contain 1-1024 admitted in-memory rows")
    out: list[tuple[str, str]] = []
    for item in rows:
        if not isinstance(item, Mapping) or not {"prompt", "completion"}.issubset(item):
            raise CandidateStepError(f"invalid {label} row fields")
        prompt, completion = item["prompt"], item["completion"]
        if (not isinstance(prompt, str) or not isinstance(completion, str)
                or not prompt.strip() or not completion.strip()
                or len(prompt) > 12000 or len(completion) > 12000):
            raise CandidateStepError(f"invalid {label} prompt/completion")
        out.append((prompt, completion))
    return out


def _encode_completion(tokenizer: Any, prompt: str, completion: str,
                       *, max_tokens: int) -> tuple[list[int], list[int]]:
    """Require a true template prefix so loss never silently includes prompt."""
    user = [{"role": "user", "content": prompt}]
    full = [*user, {"role": "assistant", "content": completion}]
    try:
        prefix = tokenizer.apply_chat_template(user, tokenize=True, add_generation_prompt=True)
        sequence = tokenizer.apply_chat_template(full, tokenize=True, add_generation_prompt=False)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CandidateStepError("tokenizer cannot encode the exact chat template") from exc
    if (not isinstance(prefix, list) or not isinstance(sequence, list)
            or not prefix or len(prefix) >= len(sequence)
            or len(sequence) > max_tokens or sequence[:len(prefix)] != prefix
            or any(type(token) is not int or token < 0 for token in sequence)):
        raise CandidateStepError("chat template is not prefix-stable or exceeds context")
    return sequence, ([-100] * len(prefix)) + sequence[len(prefix):]


def _parameter_fingerprint(parameter: Any) -> str:
    try:
        tensor = parameter.detach().to(device="cpu").contiguous()
        return hashlib.sha256(tensor.numpy().tobytes()).hexdigest()
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise CandidateStepError("cannot fingerprint the trainable adapter tensor") from exc


def experimental_loaded_cpu_lora_step(model: Any, tokenizer: Any,
                                      train: Sequence[Mapping[str, Any]],
                                      validation: Sequence[Mapping[str, Any]],
                                      broker: PinnedTrainingArtifacts, *,
                                      max_steps: int = 1, max_tokens: int = 256,
                                      learning_rate: float = 2e-4) -> dict[str, Any]:
    """Run bounded in-memory PyTorch CPU LoRA steps, then export pinned bytes.

    The caller supplies a *separately admitted* in-memory dataset, an already
    loaded and authenticated PEFT model, and host-owned private broker.  This
    function deliberately cannot establish those preconditions independently;
    it is an experimental primitive, not a public CLI or training authority.
    """
    _require_cpu_step_runtime_qualification()
    if (type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS
            or type(max_tokens) is not int or not 16 <= max_tokens <= MAX_TOKENS
            or type(learning_rate) is not float or not 0 < learning_rate <= 1e-3
            or not math.isfinite(learning_rate)):
        raise CandidateStepError("invalid bounded CPU step settings")
    if not isinstance(broker, PinnedTrainingArtifacts):
        raise CandidateStepError("a pinned private training artifact broker is required")
    train_rows = _examples(train, "training")
    validation_rows = _examples(validation, "validation")
    if {p.strip().casefold() for p, _ in train_rows} & {p.strip().casefold() for p, _ in validation_rows}:
        raise CandidateStepError("training and validation prompts overlap")
    if getattr(getattr(model, "config", None), "model_type", None) not in {"qwen3_5", "qwen3_5_text"}:
        raise CandidateStepError("loaded model is not identified as a Qwen3.5 text tower")
    configs = getattr(model, "peft_config", None)
    if not isinstance(configs, Mapping) or "default" not in configs:
        raise CandidateStepError("loaded model lacks the default PEFT adapter")
    try:
        peft_data = configs["default"].to_dict()
    except (AttributeError, TypeError, ValueError) as exc:
        raise CandidateStepError("invalid loaded PEFT configuration") from exc
    peft_type = peft_data.get("peft_type") if isinstance(peft_data, Mapping) else None
    if getattr(peft_type, "value", peft_type) != "LORA":
        raise CandidateStepError("only LoRA adapters are supported")

    # Validate every row before an optimizer exists; no silent truncation.
    encoded_train = [_encode_completion(tokenizer, p, c, max_tokens=max_tokens)
                     for p, c in train_rows]
    encoded_val = [_encode_completion(tokenizer, p, c, max_tokens=max_tokens)
                   for p, c in validation_rows]
    try:
        broker.verify_live()
        params = list(model.named_parameters())
    except (PrivateOutputError, AttributeError, OSError) as exc:
        raise CandidateStepError("private output or loaded-model parameter custody unavailable") from exc
    if not params or any(getattr(p, "device", None) is None or p.device.type != "cpu"
                         for _, p in params):
        raise CandidateStepError("all model parameters must be resident on CPU")
    trainable = [(name, p) for name, p in params if getattr(p, "requires_grad", False)]
    if (not trainable or any("lora_" not in name.lower() for name, _ in trainable)
            or sum(p.numel() for _, p in trainable) > MAX_TRAINABLE_PARAMETERS):
        raise CandidateStepError("only a bounded pure-LoRA trainable parameter set is allowed")
    initial = {name: _parameter_fingerprint(p) for name, p in trainable}
    try:
        import torch
    except ImportError as exc:
        raise CandidateStepError("real local PyTorch is required for CPU autograd") from exc
    optimizer = torch.optim.AdamW([p for _, p in trainable], lr=learning_rate)
    losses = []
    gradient_l1_sums = []
    model.train()
    for step in range(max_steps):
        ids, labels = encoded_train[step % len(encoded_train)]
        inputs = torch.tensor([ids], dtype=torch.long, device="cpu")
        targets = torch.tensor([labels], dtype=torch.long, device="cpu")
        mask = torch.ones_like(inputs)
        output = model(input_ids=inputs, attention_mask=mask, labels=targets)
        loss = output.loss
        try:
            value = float(loss.detach().item())
        except (AttributeError, TypeError, ValueError) as exc:
            raise CandidateStepError("invalid CPU training loss") from exc
        if not math.isfinite(value):
            raise CandidateStepError("non-finite CPU training loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradients = [p.grad for _, p in trainable if getattr(p, "grad", None) is not None]
        if not gradients:
            raise CandidateStepError("CPU loss backward produced no LoRA gradients")
        try:
            finite_gradients = all(bool(torch.isfinite(grad).all().item()) for grad in gradients)
            gradient_l1 = sum(float(grad.detach().float().abs().sum().item())
                              for grad in gradients)
        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            raise CandidateStepError("cannot verify LoRA gradients") from exc
        if not finite_gradients or not math.isfinite(gradient_l1) or gradient_l1 <= 0:
            raise CandidateStepError("LoRA gradient is zero or non-finite")
        optimizer.step()
        losses.append(value)
        gradient_l1_sums.append(gradient_l1)
    try:
        finite_adapter = all(bool(torch.isfinite(parameter.detach()).all().item())
                             for _, parameter in trainable)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise CandidateStepError("cannot verify LoRA tensor finiteness") from exc
    if not finite_adapter:
        raise CandidateStepError("non-finite LoRA parameter after optimizer step")
    changed = [name for name, p in trainable if _parameter_fingerprint(p) != initial[name]]
    if not changed:
        raise CandidateStepError("no LoRA parameter changed during optimizer steps")
    model.eval()
    val_losses = []
    with torch.no_grad():
        for ids, labels in encoded_val:
            inputs = torch.tensor([ids], dtype=torch.long, device="cpu")
            targets = torch.tensor([labels], dtype=torch.long, device="cpu")
            loss = model(input_ids=inputs, attention_mask=torch.ones_like(inputs), labels=targets).loss
            value = float(loss.detach().item())
            if not math.isfinite(value):
                raise CandidateStepError("non-finite CPU validation loss")
            val_losses.append(value)
    # Pinned export is invoked only after a witnessed numerical update.
    adapter = export_peft_adapter_to_broker(model, broker)
    receipt: dict[str, Any] = {
        "schema_version": "aeonith.loaded_cpu_step_candidate.v1",
        "status": "experimental_update_not_host_qualified",
        "steps": max_steps,
        "finite_nonzero_lora_gradient_l1_min": min(gradient_l1_sums),
        "changed_lora_tensor_count": len(changed),
        "training_loss_mean": sum(losses) / len(losses),
        "validation_loss_mean": sum(val_losses) / len(val_losses),
        "adapter_export": adapter,
        "holdout_not_supplied_by_interface": True,
        "holdout_contamination_verified": False,
        "loaded_checkpoint_authenticity_verified": False,
        "input_rights_verified": False,
        "trainer_filesystem_custody_qualified": False,
        "fresh_process_reload_qualified": False,
    }
    broker.write_receipt((json.dumps(receipt, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    return receipt
