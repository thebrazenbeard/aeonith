"""Opt-in, offline Qwen3.5-0.8B CUDA NF4 adapter-training experiment.

The base checkpoint must already exist locally. This source is unqualified on
the target 4 GiB host, performs no implicit download, and never publishes data,
weights, adapters, or evaluation results.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from .corpus import CorpusError, inspect_plan
from .train_lora import _output_path, _version_at_least, fingerprint_adapter
from .verify_base import BaseVerificationError, verify_checkpoint


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_BASE = "Qwen/Qwen3.5-0.8B"
MAX_EXPERIMENT_STEPS = 64
MAX_EXPERIMENT_LENGTH = 512
MIN_FREE_CUDA_MIB = 3072
MIN_AFTER_LOAD_MIB = 1536
MIN_AFTER_PREP_MIB = 1024


def _private(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise CorpusError(f"{label} must remain outside the Aeonith Git checkout")
    return resolved


def _preflight(plan: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    plan = _private(plan, "training plan")
    receipt, records = inspect_plan(plan)
    if receipt["base_model"]["id"] != SUPPORTED_BASE:
        raise CorpusError("the experimental 4-bit lane permits only official Qwen3.5-0.8B")
    settings = receipt["training"]
    if settings["max_steps"] > MAX_EXPERIMENT_STEPS or settings["max_length"] > MAX_EXPERIMENT_LENGTH:
        raise CorpusError("experimental QLoRA plan exceeds 64 steps or 512 tokens")
    raw = json.loads(plan.read_text(encoding="utf-8"))
    for split in ("train", "validation", "holdout"):
        corpus_path = Path(raw["corpus"][split]).expanduser()
        _private(corpus_path if corpus_path.is_absolute() else plan.parent / corpus_path, f"{split} corpus")
    base_dir = Path(raw["base_model"]["local_dir"]).expanduser()
    _private(base_dir if base_dir.is_absolute() else plan.parent / base_dir, "base checkpoint")
    return receipt, records


def _offline() -> None:
    for key, value in {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "WANDB_DISABLED": "true",
        "WANDB_MODE": "disabled", "DO_NOT_TRACK": "1", "TOKENIZERS_PARALLELISM": "false",
    }.items():
        os.environ[key] = value


def _fingerprint_tensor(parameter: Any) -> str:
    # LoRA parameters are small. Do not hash the quantized base or copy it to CPU.
    data = parameter.detach().to(device="cpu").float().contiguous()
    return hashlib.sha256(data.numpy().tobytes()).hexdigest()


def _headroom(cuda: Any, *, minimum_mib: int, phase: str) -> tuple[int, int]:
    """Bound a CUDA allocation phase; refuses unknown memory readback."""
    try:
        free_bytes, total_bytes = cuda.mem_get_info()
    except (AttributeError, RuntimeError) as exc:
        raise CorpusError(f"{phase}: CUDA free-memory readback unavailable") from exc
    if free_bytes < minimum_mib * 1024 * 1024:
        raise CorpusError(f"{phase}: insufficient free CUDA memory (minimum {minimum_mib} MiB)")
    return free_bytes, total_bytes


def _verify_local_base(plan: Path, expected_manifest: Path) -> dict[str, Any]:
    """Bind a separately supplied local hash list to the exact train plan.

    This establishes *local file equality only*, never publisher authenticity.
    """
    manifest_path = _private(expected_manifest, "base expected-file manifest")
    raw = json.loads(plan.read_text(encoding="utf-8"))
    base = Path(raw["base_model"]["local_dir"]).expanduser()
    if not base.is_absolute():
        base = plan.parent / base
    try:
        return verify_checkpoint(
            _private(base, "base checkpoint"), manifest_path,
            expected_model=raw["base_model"]["id"],
            expected_revision=raw["base_model"]["revision"],
        )
    except (BaseVerificationError, OSError) as exc:
        raise CorpusError("local base bytes do not match an independently supplied expected-file manifest") from exc


def _train(plan: Path, destination: Path, expected_base_manifest: Path) -> dict[str, Any]:
    _offline()
    receipt, records = _preflight(plan)
    base_verification = _verify_local_base(plan, expected_base_manifest)
    if not _version_at_least(metadata.version("transformers"), (5, 2)):
        raise CorpusError("Transformers >=5.2 is required for Qwen3.5")
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise CorpusError("local CUDA torch, transformers, accelerate, bitsandbytes, datasets, peft and trl required") from exc
    # An ordinary CPU environment must never attempt a 4-bit GPU training job.
    if not torch.cuda.is_available():
        raise CorpusError("4-bit QLoRA requires an available CUDA GPU; no CPU fallback")
    free_bytes, total_bytes = _headroom(torch.cuda, minimum_mib=MIN_FREE_CUDA_MIB,
                                        phase="before model loading")

    raw = json.loads(plan.read_text(encoding="utf-8"))
    base_dir = Path(raw["base_model"]["local_dir"]).expanduser()
    if not base_dir.is_absolute():
        base_dir = plan.parent / base_dir
    base_dir = base_dir.resolve()
    settings = receipt["training"]
    quantization = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(base_dir), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float16,
        quantization_config=quantization, device_map={"": torch.cuda.current_device()},
        attn_implementation="sdpa",
    )
    if getattr(model, "is_loaded_in_4bit", False) is not True:
        raise CorpusError("loader did not attest actual 4-bit weight loading")
    embeddings = model.get_input_embeddings()
    if embeddings is None or embeddings.weight.dtype != torch.float16:
        raise CorpusError("text embeddings did not load in the requested float16 dtype")
    parameter_devices = {parameter.device.type for parameter in model.parameters()}
    if parameter_devices != {"cuda"}:
        raise CorpusError("4-bit model did not load exclusively on CUDA; automatic offload refused")
    # Official Transformers has had 4-bit device-placement and dtype regressions.
    # Inspect the *real* loaded placement before creating optimizer state.
    after_load_free, _ = _headroom(torch.cuda, minimum_mib=MIN_AFTER_LOAD_MIB,
                                   phase="after 4-bit model loading")
    try:
        allocated_after_load = torch.cuda.memory_allocated()
    except (AttributeError, RuntimeError) as exc:
        raise CorpusError("loaded CUDA allocated-memory readback unavailable") from exc
    tokenizer = AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Never silently trim an approved answer or adapt from the blind holdout.
    for split in ("train", "validation"):
        for item in records[split]:
            token_ids = tokenizer.apply_chat_template(
                [{"role": "user", "content": item["prompt"]},
                 {"role": "assistant", "content": item["completion"]}],
                tokenize=True, add_generation_prompt=False,
            )
            if len(token_ids) > settings["max_length"]:
                raise CorpusError(f"{split} row exceeds configured context; truncation forbidden")

    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    after_prep_free, _ = _headroom(torch.cuda, minimum_mib=MIN_AFTER_PREP_MIB,
                                   phase="after k-bit preparation")
    adapter_config = LoraConfig(
        r=4, lora_alpha=8, lora_dropout=0.05, bias="none",
        target_modules="all-linear", task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, adapter_config)
    after_adapter_free, _ = _headroom(torch.cuda, minimum_mib=MIN_AFTER_PREP_MIB,
                                      phase="after LoRA insertion")
    args = SFTConfig(
        output_dir=str(destination / "runtime"),
        max_steps=settings["max_steps"], max_length=settings["max_length"],
        seed=settings["seed"], data_seed=settings["seed"],
        learning_rate=2e-4, per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=4, gradient_checkpointing=True,
        completion_only_loss=True, packing=False,
        fp16=True, bf16=False, optim="paged_adamw_8bit",
        eval_strategy="no", save_strategy="no", logging_strategy="no",
        disable_tqdm=True, report_to="none", push_to_hub=False,
    )

    def examples(split: str) -> Any:
        return Dataset.from_list([
            {"prompt": [{"role": "user", "content": row["prompt"]}],
             "completion": [{"role": "assistant", "content": row["completion"]}]}
            for row in records[split]
        ])

    trainer = SFTTrainer(
        model=model, args=args,
        train_dataset=examples("train"), eval_dataset=examples("validation"),
        processing_class=tokenizer,
    )
    initial = {name: _fingerprint_tensor(param) for name, param in trainer.model.named_parameters()
               if param.requires_grad}
    if not initial:
        raise CorpusError("no trainable LoRA parameters found")
    train_result = trainer.train()
    changed = [name for name, param in trainer.model.named_parameters()
               if name in initial and _fingerprint_tensor(param) != initial[name]]
    if not changed or train_result.global_step < 1 or not math.isfinite(float(train_result.training_loss)):
        raise CorpusError("no verified finite gradient-based adapter update")
    eval_loss = float(trainer.evaluate().get("eval_loss", float("nan")))
    if not math.isfinite(eval_loss):
        raise CorpusError("validation loss is not finite")
    adapter_dir = destination / "adapter"
    trainer.model.save_pretrained(str(adapter_dir), safe_serialization=True)
    adapter_files = fingerprint_adapter(adapter_dir)
    result = {
        "schema_version": "aeonith.adapter_receipt.v1",
        "status": "trained_not_literary_quality_qualified",
        "preflight": receipt, "adapter_files": adapter_files,
        "local_base_file_verification": base_verification,
        "gradient_update_observed": True,
        "changed_trainable_tensor_count": len(changed),
        "global_step": train_result.global_step,
        "training_loss": float(train_result.training_loss), "validation_loss": eval_loss,
        "holdout_used_by_trainer": False,
        "training_runtime": {name: metadata.version(name) for name in
                             ("torch", "transformers", "bitsandbytes", "accelerate", "peft", "trl", "datasets")},
        "model_loading": "offline_cuda_qwen35_text_tower_nf4_double_quant",
        "quantization": {"algorithm": "nf4", "bits": 4, "double_quantization": True,
                         "compute_dtype": "float16", "lora_rank": 4, "target_modules": "all-linear"},
        "free_cuda_mib_before_load": free_bytes // (1024 * 1024),
        "free_cuda_mib_after_load_before_optimizer": after_load_free // (1024 * 1024),
        "allocated_cuda_mib_after_load_before_optimizer": allocated_after_load // (1024 * 1024),
        "free_cuda_mib_after_kbit_preparation": after_prep_free // (1024 * 1024),
        "free_cuda_mib_after_lora_insertion": after_adapter_free // (1024 * 1024),
        "total_cuda_mib": total_bytes // (1024 * 1024),
        "limitations": [
            "a gradient update does not prove literary generalization or meaningful skill",
            "per-row rights declarations require actual independent human verification",
            "base revision was declared, not authenticated against the publisher",
            "fresh-process adapter reload, heldout controls, and publication review remain separate",
        ],
    }
    (destination / "training_receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experimental offline Qwen3.5-0.8B NF4 LoRA; not host-qualified")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Validate plan and corpus; never load ML packages")
    inspect.add_argument("--plan", type=Path, required=True)
    train = commands.add_parser("train", help="Explicit local 4-bit CUDA experiment")
    train.add_argument("--plan", type=Path, required=True)
    train.add_argument("--expected-base-manifest", type=Path, required=True,
                       help="independently obtained expected hashes; NOT publisher authentication")
    train.add_argument("--output", type=str, required=True)
    train.add_argument("--execute", action="store_true")
    parsed = parser.parse_args(argv)
    try:
        if parsed.command == "inspect":
            output, _ = _preflight(parsed.plan)
        else:
            if not parsed.execute:
                parser.error("train requires explicit --execute")
            destination = _output_path(parsed.output)
            output = _train(parsed.plan.resolve(), destination, parsed.expected_base_manifest)
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except (CorpusError, OSError, ImportError, metadata.PackageNotFoundError) as exc:
        print(f"Experimental 4-bit training unavailable: {exc}", file=sys.stderr)
        return 2
    except (RuntimeError, MemoryError, TypeError) as exc:
        # Optional runtimes can fail from CUDA OOM or incompatible kernels.
        # Do not emit local model paths, manuscript content, or partial tensors.
        print(f"Experimental 4-bit runtime failed ({type(exc).__name__}); no training receipt issued", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
