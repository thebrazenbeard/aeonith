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
import stat
import sys
from typing import Any

from .corpus import CorpusError, MAX_PLAN_BYTES, inspect_plan
from .corpus_admission import AdmissionError, verify_admission
from .verify_base import BaseVerificationError, verify_checkpoint


def _require_chat_context(tokenizer: Any, messages: list[dict[str, str]], *,
                          max_length: int, split: str) -> list[int]:
    """Count actual token IDs, never BatchEncoding mapping keys, before training.

    Transformers 5.20 defaults ``apply_chat_template`` to return_dict=True,
    whose ``len`` reports mapping fields rather than encoded context length.
    Request a flat sequence explicitly and reject any unexpected representation.
    """
    try:
        tokens = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False,
            return_dict=False,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise CorpusError("chat template token length cannot be verified") from exc
    if (not isinstance(tokens, list) or not tokens
            or any(type(token) is not int or token < 0 for token in tokens)):
        raise CorpusError("chat template did not return a flat token ID sequence")
    if len(tokens) > max_length:
        raise CorpusError(f"{split} record exceeds max_length; no silent truncation")
    return tokens


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
    # Private adapters must not enter *any* checkout, not merely this source
    # tree. Git worktrees and submodules use a .git file instead of a directory.
    if not value or not value.strip() or "\x00" in value or "://" in value:
        raise CorpusError("output must be a nonempty local filesystem path")
    if value.startswith(("\\", "//")):
        raise CorpusError("UNC and device output paths are unsafe for private training artifacts")
    if ":" in value and (os.name != "nt" or not re.match(r"^[A-Za-z]:[\\/]", value)
                         or ":" in value[2:]):
        raise CorpusError("drive-relative and alternate-stream output paths are unsafe")
    raw = Path(value).expanduser()
    if ".." in raw.parts:
        raise CorpusError("output paths containing parent traversal are unsafe")

    # Do not follow symlinks, Windows junctions, or other reparse points into
    # an uninspected filesystem. The final output leaf must not exist.
    lexical = raw.absolute()
    cursor = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise CorpusError("cannot inspect output path components safely") from exc
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or
                (hasattr(cursor, "is_junction") and cursor.is_junction())):
            raise CorpusError("symlinks and reparse points are unsafe output paths")

    destination = raw.resolve()
    for ancestor in (destination, *destination.parents):
        marker = ancestor / ".git"
        try:
            if (marker.is_symlink() or marker.is_file()
                    or (marker.is_dir() and (marker / "HEAD").is_file())):
                raise CorpusError("training outputs must be outside Git checkouts")
            # Bare Git repositories have HEAD/objects/refs at their root.
            if ((ancestor / "HEAD").is_file() and (ancestor / "objects").is_dir()
                    and (ancestor / "refs").is_dir()):
                raise CorpusError("training outputs must be outside Git checkouts")
        except OSError as exc:
            raise CorpusError("cannot inspect Git ancestry of training output safely") from exc
    if destination.exists() or destination.parent == destination:
        raise CorpusError("output directory already exists or is unsafe; never overwrite training artifacts")
    if not destination.parent.is_dir():
        raise CorpusError("output parent must exist; create it intentionally before training")
    return destination


def _version_at_least(version: str, minimum: tuple[int, int]) -> bool:
    match = re.match(r"^(\d+)\.(\d+)", version)
    return bool(match and (int(match[1]), int(match[2])) >= minimum)


def _require_cpu_training(device: str) -> None:
    """Refuse GPU use until a real host-owned allocation gate exists.

    A caller's --execute flag is consent to start this one job, not evidence
    that a shared GPU has available capacity or an exclusive resource lease.
    """
    if device != "cpu":
        raise CorpusError(
            "CUDA training is disabled: no host-owned GPU allocation gate is "
            "implemented; use --device cpu after checking host RAM and workload"
        )


def require_actual_cpu_float32_model(model: Any, torch: Any) -> dict[str, int]:
    """Verify observed loaded parameters, not a requested ``dtype`` argument.

    Certain Transformers/Qwen3.5 releases ignored the caller's requested
    float32 dtype while unwrapping a multimodal checkpoint to the text tower.
    A version threshold alone cannot establish the real loaded CPU dtype.
    This check must precede LoRA wrapping and any optimizer construction.
    """
    try:
        parameters = iter(model.named_parameters())
        count = 0
        for name, parameter in parameters:
            if not isinstance(name, str) or not name:
                raise CorpusError("loaded model contains an unnamed parameter")
            if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
                raise CorpusError("loaded model parameter is not CPU float32; optimizer refused")
            count += 1
        if count == 0:
            raise CorpusError("loaded model contains no verifiable parameters")
        return {"cpu_float32_parameter_count": count}
    except CorpusError:
        raise
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise CorpusError("loaded model dtype/device could not be verified") from exc


def inspect_admitted_plan(plan_path: str | Path, audit_manifest: str | Path,
                          approval: str | Path,
                          admission_receipt: str | Path) -> tuple[dict[str, Any], dict[str, list[dict]], dict[str, Any]]:
    """Bind exact training split bytes to an independently rechecked audit receipt.

    This rechecks operator-attested approval claims. It cannot authenticate
    human identities, permission provenance or the remote Qwen revision.
    """
    preflight, dataset = inspect_plan(plan_path)
    try:
        admitted = verify_admission(audit_manifest, approval, admission_receipt)
    except AdmissionError as exc:
        raise CorpusError(f"corpus admission verification refused: {exc}") from exc
    if (admitted["split_sha256"] != {
            split: preflight["split_files"][split]["sha256"] for split in ("train", "validation", "holdout")
        } or admitted["split_counts"] != preflight["split_counts"]):
        raise CorpusError("training plan does not match exact admitted corpus split bytes")
    return preflight, dataset, admitted


def _verified_base_context(plan_path: str | Path, preflight: dict[str, Any],
                           expected_manifest: str | Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Bind the checked preflight plan to one model-loading path and snapshot.

    This eliminates a needless second mutable plan read before model loading;
    it does *not* protect a model directory against concurrent hostile writes.
    """
    try:
        plan_bytes = Path(plan_path).read_bytes()
        if (len(plan_bytes) > MAX_PLAN_BYTES or not isinstance(preflight.get("plan_sha256"), str)
                or hashlib.sha256(plan_bytes).hexdigest() != preflight["plan_sha256"]):
            raise CorpusError("training plan changed since admitted preflight; optimizer refused")
        raw = json.loads(plan_bytes.decode("utf-8"))
        expected_id = preflight["base_model"]["id"]
        expected_revision = preflight["base_model"]["revision_declared_not_remote_verified"]
        if (raw["base_model"]["id"] != expected_id
                or raw["base_model"]["revision"] != expected_revision):
            raise CorpusError("training base identity changed since admitted preflight")
        local_dir = Path(raw["base_model"]["local_dir"]).expanduser()
        if not local_dir.is_absolute():
            local_dir = Path(plan_path).parent / local_dir
        verified = verify_checkpoint(
            local_dir, expected_manifest, expected_model=expected_id,
            expected_revision=expected_revision,
        )
        return verified, raw, local_dir.resolve()
    except CorpusError:
        raise
    except (BaseVerificationError, OSError, ValueError, KeyError, TypeError) as exc:
        raise CorpusError("local base weights/tokenizer did not match the separately supplied expected-file manifest") from exc


def verify_declared_base_checkpoint(plan_path: str | Path, preflight: dict[str, Any],
                                    expected_manifest: str | Path) -> dict[str, Any]:
    """Return local byte-equality receipt, never authenticated publisher origin."""
    return _verified_base_context(plan_path, preflight, expected_manifest)[0]


def _require_private_output_broker() -> None:
    """Fail closed until a host-owned private output creation boundary exists.

    The existing Trainer/runtime/adapter writes follow an output *path* after
    a lexical check. An adversary controlling an ancestor could replace it
    between checks and writes. Neither POSIX nor Windows path checks establish
    the requisite handle-pinned, owner-qualified custody here.
    """
    raise CorpusError("private training output custody broker is unqualified; optimizer start refused")


def _train(plan_path: Path, output: Path, *, device: str = "cpu",
           audit_manifest: Path | None = None,
           approval: Path | None = None,
           admission_receipt: Path | None = None,
           expected_base_manifest: Path | None = None) -> dict[str, Any]:
    _require_cpu_training(device)
    if audit_manifest is None or approval is None or admission_receipt is None:
        raise CorpusError("exact corpus audit manifest, approval and admission receipt are required")
    # Fail before hashing model/corpus bytes: no portable host-owned private
    # output broker currently protects runtime, adapter, and receipt writes.
    _require_private_output_broker()
    preflight, dataset, admitted = inspect_admitted_plan(
        plan_path, audit_manifest, approval, admission_receipt)
    if expected_base_manifest is None:
        raise CorpusError("separately supplied expected-base-manifest is required before training")
    base_verification, raw_plan, base_dir = _verified_base_context(
        plan_path, preflight, expected_base_manifest)
    # None of these options may trigger a Hub download, phone home, or paid call.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["WANDB_DISABLED"] = "true"
    # Must be set before importing torch or Accelerate. The explicit SFTConfig
    # CPU setting below is a second guard against Trainer's auto device choice.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

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

    config = raw_plan["training"]

    # The TRL Qwen3.5 regression tests explicitly exercise this mapping:
    # AutoModelForCausalLM loads the *text tower* from a multimodal checkpoint.
    # It does not train the vision encoder. No trust_remote_code or network access.
    model = AutoModelForCausalLM.from_pretrained(
        str(base_dir), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float32,
    )
    # Real dtype readback is essential: affected Transformers releases have
    # silently loaded Qwen3.5 text towers in BF16 despite dtype=float32.
    require_actual_cpu_float32_model(model, torch)
    tokenizer = AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # The local corpus must fit the chosen training context exactly; silently
    # losing the completion would create apparent training with no target.
    for split in ("train", "validation"):
        for example in dataset[split]:
            _require_chat_context(tokenizer,
                [{"role": "user", "content": example["prompt"]},
                 {"role": "assistant", "content": example["completion"]}],
                max_length=config["max_length"], split=split,
            )

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
        fp16=False,
        bf16=False,
        use_cpu=True,
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
        "operator_attested_admission": admitted,
        "local_base_file_verification": base_verification,
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
            "local base bytes matched a supplied manifest; its issuer and revision are not authenticated",
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
    inspect_admission = command.add_parser("inspect-admission", help="Read-only binding of plan, approval and saved admission receipt")
    inspect_admission.add_argument("--plan", type=Path, required=True)
    train = command.add_parser("train", help="Actually train from already-present local weights")
    train.add_argument("--plan", type=Path, required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--execute", action="store_true", help="Explicitly permit local training and output creation")
    train.add_argument("--device", choices=("cpu", "cuda"), default="cpu",
                       help="CPU only; CUDA is rejected until host-owned GPU allocation is implemented")
    train.add_argument("--expected-base-manifest", type=Path,
                       help="separately obtained model/tokenizer SHA-256 manifest; does not authenticate its issuer")
    for target in (inspect_admission, train):
        target.add_argument("--audit-manifest", type=Path)
        target.add_argument("--approval", type=Path)
        target.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            receipt, _ = inspect_plan(args.plan)
        elif args.command == "inspect-admission":
            if not (args.audit_manifest and args.approval and args.admission_receipt):
                parser.error("inspect-admission requires --audit-manifest, --approval and --admission-receipt")
            receipt, _, admitted = inspect_admitted_plan(
                args.plan, args.audit_manifest, args.approval, args.admission_receipt)
            receipt = {**receipt, "admission": admitted}
        else:
            if not args.execute:
                parser.error("train requires explicit --execute")
            _require_cpu_training(args.device)
            if not (args.audit_manifest and args.approval and args.admission_receipt):
                parser.error("train requires --audit-manifest, --approval and --admission-receipt")
            destination = _output_path(args.output)
            receipt = _train(args.plan.resolve(), destination, device=args.device,
                             audit_manifest=args.audit_manifest, approval=args.approval,
                             admission_receipt=args.admission_receipt,
                             expected_base_manifest=args.expected_base_manifest)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (CorpusError, FileNotFoundError, ImportError, OSError) as exc:
        print(f"Training unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
