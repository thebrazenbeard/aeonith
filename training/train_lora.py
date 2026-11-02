"""Explicit, offline Qwen3.5 (0.8B/2B/4B) text-only LoRA training and receipt CLI.

Optional third-party dependencies are loaded ONLY for ``train --execute``.
This is a reproducible path, not a claim that any adapter has been trained.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

from .corpus import CorpusError, inspect_plan


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def fingerprint_adapter(directory: str | Path) -> list[dict[str, Any]]:
    """Fingerprint genuine PEFT-format files; never infer training from files."""
    root = Path(directory)
    files = [root / "adapter_config.json", root / "adapter_model.safetensors"]
    if not all(path.is_file() and path.stat().st_size for path in files):
        raise CorpusError("adapter_config.json and adapter_model.safetensors are required")
    return [{"path": item.name, "bytes": item.stat().st_size, "sha256": _digest(item)} for item in files]


def _output_path(value: str) -> Path:
    destination = Path(value).expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if destination == repo or repo in destination.parents:
        raise CorpusError("training outputs must be outside the Aeonith Git checkout")
    if destination.exists() or destination.parent == destination:
        raise CorpusError("output directory already exists or is unsafe; never overwrite training artifacts")
    if not destination.parent.is_dir():
        raise CorpusError("output parent must exist; create it intentionally before training")
    return destination


def _version_at_least(version: str, minimum: tuple[int, int]) -> bool:
    match = re.match(r"^(\d+)\.(\d+)", version)
    return bool(match and (int(match[1]), int(match[2])) >= minimum)


def _train(plan_path: Path, output: Path) -> dict[str, Any]:
    # None of these options may trigger a Hub download, phone home, or paid call.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["WANDB_DISABLED"] = "true"

    preflight, dataset = inspect_plan(plan_path)
    if not _version_at_least(metadata.version("transformers"), (5, 2)):
        raise CorpusError("Transformers >=5.2 is required for Qwen3.5 text-only loading")
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise CorpusError("optional local torch, datasets, peft, transformers, trl packages required") from exc

    raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base_dir = Path(raw_plan["base_model"]["local_dir"]).expanduser()
    if not base_dir.is_absolute():
        base_dir = plan_path.parent / base_dir
    base_dir = base_dir.resolve()
    config = raw_plan["training"]

    # The TRL Qwen3.5 regression tests explicitly exercise this mapping:
    # AutoModelForCausalLM loads the *text tower* from a multimodal checkpoint.
    # It does not train the vision encoder. No trust_remote_code or network access.
    device_is_cuda = torch.cuda.is_available()
    model = AutoModelForCausalLM.from_pretrained(
        str(base_dir), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float16 if device_is_cuda else torch.float32,
    )
    tokenizer = AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # The local corpus must fit the chosen training context exactly; silently
    # losing the completion would create apparent training with no target.
    for split in ("train", "validation"):
        for example in dataset[split]:
            tokens = tokenizer.apply_chat_template(
                [{"role": "user", "content": example["prompt"]},
                 {"role": "assistant", "content": example["completion"]}],
                tokenize=True, add_generation_prompt=False,
            )
            if len(tokens) > config["max_length"]:
                raise CorpusError(f"{split} record exceeds max_length; no silent truncation")

    def records(split: str) -> Any:
        return Dataset.from_list([
            {
                "prompt": [{"role": "user", "content": example["prompt"]}],
                "completion": [{"role": "assistant", "content": example["completion"]}],
            }
            for example in dataset[split]
        ])

    training_args = SFTConfig(
        output_dir=str(output / "runtime"),
        max_steps=config["max_steps"],
        max_length=config["max_length"],
        seed=config["seed"],
        data_seed=config["seed"],
        learning_rate=2e-4,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=4,
        gradient_checkpointing=True,
        completion_only_loss=True,
        packing=False,
        fp16=device_is_cuda,
        bf16=False,
        eval_strategy="no",
        save_strategy="no",
        logging_strategy="no",
        disable_tqdm=True,
        report_to="none",
        push_to_hub=False,
    )
    lora_config = LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM",
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=records("train"),
        eval_dataset=records("validation"),
        processing_class=tokenizer,
        peft_config=lora_config,
    )

    def parameter_fingerprint(parameter: Any) -> str:
        tensor = parameter.detach().to(device="cpu", dtype=torch.float32).contiguous()
        return hashlib.sha256(tensor.numpy().tobytes()).hexdigest()

    # A successful API return with zero updated parameters is not a trained adapter.
    initial = {name: parameter_fingerprint(param) for name, param in trainer.model.named_parameters() if param.requires_grad}
    if not initial:
        raise CorpusError("LoRA did not expose trainable parameters")
    train_result = trainer.train()
    changed = [name for name, param in trainer.model.named_parameters()
               if name in initial and parameter_fingerprint(param) != initial[name]]
    if not changed or train_result.global_step < 1 or not math.isfinite(float(train_result.training_loss)):
        raise CorpusError("training produced no verified finite gradient-based weight update")
    eval_result = trainer.evaluate()
    eval_loss = float(eval_result.get("eval_loss", float("nan")))
    if not math.isfinite(eval_loss):
        raise CorpusError("validation loss is not finite")

    adapter_dir = output / "adapter"
    trainer.model.save_pretrained(str(adapter_dir), safe_serialization=True)
    files = fingerprint_adapter(adapter_dir)
    result = {
        "schema_version": "aeonith.adapter_receipt.v1",
        "status": "trained_not_literary_quality_qualified",
        "preflight": preflight,
        "adapter_files": files,
        "gradient_update_observed": True,
        "changed_trainable_tensor_count": len(changed),
        "global_step": train_result.global_step,
        "training_loss": float(train_result.training_loss),
        "validation_loss": eval_loss,
        "holdout_used_by_trainer": False,
        "training_runtime": {name: metadata.version(name) for name in ("torch", "transformers", "peft", "trl", "datasets")},
        "model_loading": "local_only_text_tower_no_remote_code",
        "limitations": [
            "base revision is operator-declared and not independently matched to the remote publisher",
            "copyright and consent attestations require human verification",
            "adapter needs a separate fresh-process reload and blind literary evaluation",
        ],
    }
    # Manifest is written only after a real, observed weight update and save.
    (output / "training_receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optional offline Qwen3.5 0.8B/2B/4B LoRA/SFT pipeline")
    command = parser.add_subparsers(dest="command", required=True)
    inspect = command.add_parser("inspect", help="Validate local corpus and fingerprints, with no ML dependencies")
    inspect.add_argument("--plan", type=Path, required=True)
    train = command.add_parser("train", help="Actually train from already-present local weights")
    train.add_argument("--plan", type=Path, required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--execute", action="store_true", help="Explicitly permit local training and output creation")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            receipt, _ = inspect_plan(args.plan)
        else:
            if not args.execute:
                parser.error("train requires explicit --execute")
            destination = _output_path(args.output)
            receipt = _train(args.plan.resolve(), destination)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (CorpusError, FileNotFoundError, ImportError, OSError) as exc:
        print(f"Training unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
