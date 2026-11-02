"""Read-only corpus rights, separation, and provenance preflight.

The validator cannot independently establish copyright or ownership. It
requires a specific per-record attestation and rejects unknown provenance.
No manuscript text is included in its returned receipt.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any


class CorpusError(ValueError):
    """Invalid or insufficiently authorized local training material."""


ALLOWED_MODELS = frozenset({"Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B"})
RIGHTS_BASIS = frozenset({"self_authored", "public_domain", "cc0", "licensed"})
SPLITS = ("train", "validation", "holdout")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_PLAN_BYTES = 64 * 1024
MAX_SPLIT_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 48 * 1024
MAX_ROWS_PER_SPLIT = 50000


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise CorpusError("duplicate JSON key in plan or corpus")
        out[key] = value
    return out


def _read_json(path: Path, max_bytes: int) -> Any:
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise CorpusError("missing or oversized local JSON file")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as exc:
        raise CorpusError("invalid UTF-8 JSON") from exc


def _exact_keys(obj: Any, required: set[str], optional: set[str], context: str) -> dict:
    if not isinstance(obj, dict) or not required.issubset(obj) or set(obj) - required - optional:
        raise CorpusError(f"invalid {context} fields")
    return obj


def _local_path(path: Any, base: Path) -> Path:
    if not isinstance(path, str) or not path.strip() or "://" in path or path.startswith("\\\\"):
        raise CorpusError("only explicit local paths are permitted")
    candidate = Path(path).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_row(raw: Any, split: str, number: int) -> dict[str, str]:
    fields = {"id", "prompt", "completion", "source_id", "rights_basis", "permission_to_train", "permission_to_publish_adapter"}
    obj = _exact_keys(raw, fields, {"license_id"}, f"{split} row {number}")
    for name in ("id", "source_id"):
        if not isinstance(obj[name], str) or not NAME.fullmatch(obj[name]):
            raise CorpusError(f"invalid {name} at {split} row {number}")
    for name in ("prompt", "completion"):
        if not isinstance(obj[name], str) or not obj[name].strip() or len(obj[name]) > 12000:
            raise CorpusError(f"invalid {name} at {split} row {number}")
    if not isinstance(obj["rights_basis"], str) or obj["rights_basis"] not in RIGHTS_BASIS:
        raise CorpusError(f"unknown rights basis at {split} row {number}")
    if obj["permission_to_train"] is not True or obj["permission_to_publish_adapter"] is not True:
        raise CorpusError(f"missing permission at {split} row {number}")
    if obj["rights_basis"] == "licensed" and not (isinstance(obj.get("license_id"), str) and obj["license_id"].strip()):
        raise CorpusError(f"licensed data requires license_id at {split} row {number}")
    return obj


def _read_split(path: Path, split: str) -> list[dict[str, str]]:
    if not path.is_file() or not (0 < path.stat().st_size <= MAX_SPLIT_BYTES):
        raise CorpusError(f"missing, empty, or oversized {split} corpus")
    records = []
    try:
        with path.open("rb") as source:
            for number, line in enumerate(source, 1):
                if number > MAX_ROWS_PER_SPLIT or len(line) > MAX_LINE_BYTES:
                    raise CorpusError(f"oversized {split} corpus")
                try:
                    raw = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
                except (UnicodeError, ValueError) as exc:
                    raise CorpusError(f"invalid {split} JSONL row {number}") from exc
                records.append(_check_row(raw, split, number))
    except OSError as exc:
        raise CorpusError(f"unable to read {split} corpus") from exc
    if not records:
        raise CorpusError(f"empty {split} corpus")
    return records


def _check_isolation(dataset: dict[str, list[dict[str, str]]]) -> None:
    # A single source can have multiple examples, but it cannot cross splits.
    seen_ids: set[str] = set()
    for split in SPLITS:
        rows = dataset[split]
        for record in rows:
            if record["id"] in seen_ids:
                raise CorpusError("record id overlap across splits")
            seen_ids.add(record["id"])
    for field in ("prompt", "source_id"):
        observed: dict[str, str] = {}
        for split in SPLITS:
            for record in dataset[split]:
                value = record[field].strip().casefold() if field == "prompt" else record[field]
                fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()
                prior_split = observed.get(fingerprint)
                if prior_split is not None and prior_split != split:
                    raise CorpusError(f"{field} overlap across train/validation/holdout")
                observed[fingerprint] = split


def inspect_plan(plan_path: str | Path) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    """Validate an opt-in local plan and return text-free receipt and datasets.

    The returned datasets are intended ONLY for the explicit local training
    subcommand. The holdout must never be passed into the trainer.
    """
    path = Path(plan_path).expanduser().resolve()
    plan = _exact_keys(_read_json(path, MAX_PLAN_BYTES), {"schema_version", "base_model", "corpus", "training"}, set(), "plan")
    if plan["schema_version"] != "aeonith.training_plan.v1":
        raise CorpusError("unsupported training plan schema")
    model = _exact_keys(plan["base_model"], {"id", "revision", "local_dir"}, set(), "base_model")
    if model["id"] not in ALLOWED_MODELS:
        raise CorpusError("unsupported base model (official Qwen3.5 2B/4B only)")
    if not isinstance(model["revision"], str) or not HEX40.fullmatch(model["revision"]):
        raise CorpusError("base revision must be an immutable 40-character SHA")
    base_dir = _local_path(model["local_dir"], path.parent)
    if not base_dir.is_dir():
        raise CorpusError("local base model directory missing; automatic downloads are forbidden")
    config = _read_json(base_dir / "config.json", MAX_PLAN_BYTES)
    if not isinstance(config, dict) or config.get("model_type") not in {"qwen3_5", "qwen3_5_text"}:
        raise CorpusError("local base is not a Qwen3.5 Transformers checkpoint")
    weights = sorted(base_dir.glob("*.safetensors"))
    if not weights:
        raise CorpusError("local base must contain safetensors weights")
    tokenizer_files = [base_dir / name for name in ("tokenizer.json", "tokenizer.model", "vocab.json") if (base_dir / name).is_file()]
    if not tokenizer_files:
        raise CorpusError("local base must contain local tokenizer assets")
    related = [base_dir / name for name in (
        "model.safetensors.index.json", "tokenizer_config.json", "special_tokens_map.json",
        "generation_config.json", "merges.txt",
    ) if (base_dir / name).is_file()]
    base_files = [base_dir / "config.json", *weights, *tokenizer_files, *related]
    base_fingerprints = [{"name": item.name, "bytes": item.stat().st_size, "sha256": _sha256(item)} for item in base_files]
    settings = _exact_keys(plan["training"], {"max_steps", "max_length", "seed"}, set(), "training")
    for name, minimum, maximum in (("max_steps", 1, 10000), ("max_length", 128, 4096), ("seed", 0, 2**32 - 1)):
        val = settings[name]
        if type(val) is not int or not minimum <= val <= maximum:
            raise CorpusError(f"invalid training {name}")
    paths = _exact_keys(plan["corpus"], set(SPLITS), set(), "corpus")
    resolved = {split: _local_path(paths[split], path.parent) for split in SPLITS}
    if len(set(resolved.values())) != len(SPLITS):
        raise CorpusError("train/validation/holdout paths overlap")
    dataset = {split: _read_split(resolved[split], split) for split in SPLITS}
    _check_isolation(dataset)
    receipt = {
        "schema_version": "aeonith.training_preflight.v1",
        "status": "validated_not_trained",
        "plan_sha256": _sha256(path),
        "base_model": {"id": model["id"], "revision_declared_not_remote_verified": model["revision"], "files": base_fingerprints},
        "training": settings,
        "split_counts": {split: len(dataset[split]) for split in SPLITS},
        "split_files": {split: {"bytes": resolved[split].stat().st_size, "sha256": _sha256(resolved[split])} for split in SPLITS},
        "rights_basis_counts": dict(sorted(Counter(item["rights_basis"] for split in SPLITS for item in dataset[split]).items())),
        "rights_provenance": "operator_attested_not_independently_verified",
    }
    return receipt, dataset
