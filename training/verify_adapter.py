"""Read-only offline receipt checks and opt-in fresh-process LoRA reload smoke.

This is deliberately separate from training and cannot establish literary
quality. The optional ML imports are delayed until ``smoke --execute``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


class VerificationError(ValueError):
    """The supplied local artifacts do not match their training receipt."""


_HASH = re.compile(r"^[a-f0-9]{64}$")
_EXPECTED_ADAPTER = {"adapter_config.json", "adapter_model.safetensors"}
_ALLOWED_MODELS = {"Qwen/Qwen3.5-0.8B", "Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B"}
_SAMPLE = "The lantern went out when the letter arrived."


def _unique_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        if key in result:
            raise VerificationError("duplicate JSON key")
        result[key] = value
    return result


def _load_json(path: Path, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    if not path.is_file() or not (0 < path.stat().st_size <= max_bytes):
        raise VerificationError("missing or oversized local JSON")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, ValueError) as exc:
        raise VerificationError("invalid local JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError("expected JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint_entries(raw: Any, *, adapter: bool) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not (2 <= len(raw) <= 256):
        raise VerificationError("invalid adapter manifest" if adapter else "invalid base manifest")
    accepted = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise VerificationError("invalid fingerprint entry")
        name = item.get("path" if adapter else "name")
        size, digest = item.get("bytes"), item.get("sha256")
        if (not isinstance(name, str) or not name or name in {".", ".."}
                or Path(name).name != name or "/" in name or "\\" in name
                or ":" in name or name in seen or type(size) is not int or size <= 0
                or not isinstance(digest, str) or not _HASH.fullmatch(digest)):
            raise VerificationError("invalid adapter manifest" if adapter else "invalid base manifest")
        seen.add(name)
        accepted.append({"name": name, "bytes": size, "sha256": digest})
    if adapter and seen != _EXPECTED_ADAPTER:
        raise VerificationError("invalid adapter manifest")
    if not adapter and not {"config.json"}.issubset(seen):
        raise VerificationError("invalid base manifest")
    if not adapter and not any(name.endswith(".safetensors") for name in seen):
        raise VerificationError("invalid base manifest")
    if not adapter and not seen.intersection({"tokenizer.json", "tokenizer.model", "vocab.json"}):
        raise VerificationError("invalid base manifest")
    return accepted


def _check_files(directory: Path, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        target = directory / entry["name"]
        if not target.is_file() or target.stat().st_size != entry["bytes"] or _sha256(target) != entry["sha256"]:
            raise VerificationError("local artifact fingerprint mismatch")


def inspect_adapter_receipt(base: str | Path, adapter: str | Path, receipt: str | Path) -> dict[str, Any]:
    """Match local files to a *self-reported* receipt; do not validate training claims."""
    base_dir = Path(base).expanduser().resolve()
    adapter_dir = Path(adapter).expanduser().resolve()
    receipt_path = Path(receipt).expanduser().resolve()
    if not base_dir.is_dir() or not adapter_dir.is_dir():
        raise VerificationError("local base and adapter directories are required")
    raw = _load_json(receipt_path)
    if (raw.get("schema_version") != "aeonith.adapter_receipt.v1"
            or raw.get("status") != "trained_not_literary_quality_qualified"):
        raise VerificationError("unsupported training receipt")
    if (raw.get("gradient_update_observed") is not True
            or type(raw.get("changed_trainable_tensor_count")) is not int
            or raw["changed_trainable_tensor_count"] < 1
            or type(raw.get("global_step")) is not int or raw["global_step"] < 1):
        raise VerificationError("receipt lacks a valid gradient-update declaration")
    preflight = raw.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("schema_version") != "aeonith.training_preflight.v1":
        raise VerificationError("missing training preflight")
    model = preflight.get("base_model")
    if not isinstance(model, dict) or model.get("id") not in _ALLOWED_MODELS:
        raise VerificationError("unsupported checkpoint in training receipt")
    revision = model.get("revision_declared_not_remote_verified")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise VerificationError("invalid declared checkpoint revision")
    adapter_entries = _fingerprint_entries(raw.get("adapter_files"), adapter=True)
    base_entries = _fingerprint_entries(model.get("files"), adapter=False)
    _check_files(adapter_dir, adapter_entries)
    _check_files(base_dir, base_entries)
    config = _load_json(adapter_dir / "adapter_config.json", max_bytes=64 * 1024)
    if config.get("peft_type") != "LORA" or config.get("task_type") != "CAUSAL_LM":
        raise VerificationError("unsupported adapter configuration")
    base_config = _load_json(base_dir / "config.json", max_bytes=64 * 1024)
    if base_config.get("model_type") not in {"qwen3_5", "qwen3_5_text"}:
        raise VerificationError("unsupported base configuration")
    return {
        "schema_version": "aeonith.adapter_reload_check.v1",
        "status": "fingerprints_verified_not_model_qualified",
        "base_model_id": model["id"],
        "base_revision_declared_not_remote_verified": revision,
        "adapter_files_match_receipt": True,
        "base_files_match_receipt": True,
        "receipt_sha256": _sha256(receipt_path),
        "literary_quality_qualified": False,
        "limitations": [
            "file hashes match a locally supplied receipt; this does not authenticate who trained it",
            "declared upstream revision and data permissions were not independently verified",
            "literary quality and weight improvement remain unassessed",
        ],
    }


def write_report_exclusive(path: str | Path, result: dict[str, Any]) -> None:
    destination = Path(path).expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if destination == repo or repo in destination.parents:
        raise VerificationError("report output must remain outside the Aeonith checkout")
    with destination.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")


def _offline_environment() -> None:
    for key, value in {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "WANDB_DISABLED": "true", "CUDA_VISIBLE_DEVICES": "-1",
    }.items():
        os.environ[key] = value


def _require_cpu_smoke(device: str) -> None:
    """An opt-in smoke test is not a host-owned allocation of a shared GPU."""
    if device != "cpu":
        raise VerificationError(
            "CUDA smoke verification is disabled: no host-owned GPU allocation "
            "gate is implemented; use --device cpu after checking host resources"
        )


def _token_digest(tokens: list[int]) -> str:
    return hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode("ascii")).hexdigest()


def _require_generation_tokens(value: Any, torch: Any) -> Any:
    """Require a single token-ID tensor, not a BatchEncoding mapping."""
    if (not torch.is_tensor(value) or value.dtype != torch.long
            or value.ndim != 2 or value.shape[0] != 1 or value.shape[1] < 1):
        raise VerificationError("chat tokenizer did not return a single token-ID tensor")
    return value


def smoke_reload(base: Path, adapter: Path, verification: dict[str, Any], *,
                 device: str, max_new_tokens: int) -> dict[str, Any]:
    """Reload the base and adapter in this new CLI process, then generate no prose logs."""
    _require_cpu_smoke(device)
    _offline_environment()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = AutoModelForCausalLM.from_pretrained(
        str(base), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float32,
    ).to(device)
    tokenizer = AutoTokenizer.from_pretrained(str(base), local_files_only=True, trust_remote_code=False)
    inputs = _require_generation_tokens(tokenizer.apply_chat_template(
        [{"role": "user", "content": "Read one original sentence closely: " + _SAMPLE}],
        tokenize=True, add_generation_prompt=True, return_tensors="pt",
        return_dict=False,
    ), torch).to(device)
    model.eval()
    with torch.inference_mode():
        plain = model.generate(input_ids=inputs, do_sample=False, max_new_tokens=max_new_tokens,
                               pad_token_id=tokenizer.eos_token_id)[0][inputs.shape[-1]:].tolist()
    loaded = PeftModel.from_pretrained(model, str(adapter), is_trainable=False, local_files_only=True)
    loaded.eval()
    with torch.inference_mode():
        adapted = loaded.generate(input_ids=inputs, do_sample=False, max_new_tokens=max_new_tokens,
                                  pad_token_id=tokenizer.eos_token_id)[0][inputs.shape[-1]:].tolist()
    if not plain or not adapted:
        raise VerificationError("model returned no new tokens during smoke")
    return {
        **verification,
        "status": "fresh_process_reload_smoke_completed_not_quality_qualified",
        "adapter_reloaded_in_process": True,
        "smoke_device": device,
        "max_new_tokens": max_new_tokens,
        "base_output_token_count": len(plain),
        "adapter_output_token_count": len(adapted),
        "base_output_token_ids_sha256": _token_digest(plain),
        "adapter_output_token_ids_sha256": _token_digest(adapted),
        "outputs_differ": plain != adapted,
        "literary_quality_qualified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Aeonith PEFT receipt/reload verifier; not a quality gate")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "smoke"):
        command = commands.add_parser(name)
        command.add_argument("--base", type=Path, required=True)
        command.add_argument("--adapter", type=Path, required=True)
        command.add_argument("--receipt", type=Path, required=True)
        command.add_argument("--output", type=Path)
        if name == "smoke":
            command.add_argument("--execute", action="store_true")
            command.add_argument("--device", choices=("cpu", "cuda"), default="cpu",
                                 help="CPU only; CUDA is refused until host-owned allocation exists")
            command.add_argument("--max-new-tokens", type=int, default=48)
    args = parser.parse_args(argv)
    if args.command == "smoke":
        if not args.execute:
            parser.error("smoke requires explicit --execute")
        if not 1 <= args.max_new_tokens <= 128:
            parser.error("--max-new-tokens must be between 1 and 128")
    try:
        if args.command == "smoke":
            _require_cpu_smoke(args.device)
        result = inspect_adapter_receipt(args.base, args.adapter, args.receipt)
        if args.command == "smoke":
            try:
                result = smoke_reload(args.base.resolve(), args.adapter.resolve(), result,
                                      device=args.device, max_new_tokens=args.max_new_tokens)
            except (ImportError, RuntimeError, OSError, ValueError, TypeError) as exc:
                raise VerificationError(f"fresh reload smoke unavailable ({type(exc).__name__})") from exc
        if args.output:
            write_report_exclusive(args.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (VerificationError, OSError, FileExistsError) as exc:
        print(f"Adapter verification unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
