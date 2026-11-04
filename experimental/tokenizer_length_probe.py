"""Offline Qwen3.5 synthetic-candidate tokenizer preflight; NEVER trains.

This measures exact chat-template sizes for the deterministic, unadmitted
literary pilot. It loads tokenizer assets only, never model weights. Its output
is aggregate and text-free, and it cannot approve a corpus or an optimizer.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from training.synthetic_pilot import _serialized, build_candidate


class TokenizerProbeError(ValueError):
    """The candidate tokenizer probe could not establish exact token lengths."""


_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"
_MODEL_ID = "Qwen/Qwen3.5-0.8B"
_MANIFEST = (Path(__file__).resolve().parents[1] / "training" / "manifests"
             / f"qwen3.5-0.8b-{_REVISION}.json")
_TOKENIZER_FILES = frozenset({
    "config.json", "tokenizer.json", "tokenizer_config.json",
    "chat_template.jinja", "merges.txt", "vocab.json",
})
_MAX_FILE_BYTES = 32 * 1024 * 1024
_HEX64 = re.compile(r"^[a-f0-9]{64}$")


def _safe_dir(raw: str | Path) -> Path:
    value = Path(raw).expanduser()
    if (not value.is_absolute() or ".." in value.parts or "\x00" in str(value)):
        raise TokenizerProbeError("tokenizer directory must be an absolute local path")
    if not value.is_dir():
        raise TokenizerProbeError("local tokenizer directory is unavailable")
    if any(piece.is_symlink() or (hasattr(piece, "is_junction") and piece.is_junction())
           for piece in (value, *value.parents)):
        raise TokenizerProbeError("tokenizer path has an indirect ancestor")
    return value


def verify_tokenizer_assets(base_dir: str | Path, *,
                            expected_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hash only pinned tokenizer/config bytes; does not load model weights.

    Hash equality is not publisher authentication, a protected loader mount,
    or a same-UID immutability proof. The later Transformers reopen is NOT
    descriptor pinned; both before and after checks remain necessary.
    """
    directory = _safe_dir(base_dir)
    try:
        if expected_manifest is None:
            expected_manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        if (not isinstance(expected_manifest, dict)
                or expected_manifest.get("schema_version") != "aeonith.expected_base_files.v1"
                or expected_manifest.get("upstream_model_id") != _MODEL_ID
                or expected_manifest.get("upstream_revision") != _REVISION
                or not isinstance(expected_manifest.get("files"), list)):
            raise TokenizerProbeError("unsupported pinned tokenizer expectation")
        files: dict[str, dict[str, Any]] = {}
        for item in expected_manifest["files"]:
            if not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}:
                raise TokenizerProbeError("invalid expected-file manifest entry")
            name = item["name"]
            if name in files:
                raise TokenizerProbeError("duplicate expected tokenizer file")
            files[name] = item
        if not _TOKENIZER_FILES.issubset(files):
            raise TokenizerProbeError("pinned tokenizer manifest omits required files")
        total = 0
        for name in sorted(_TOKENIZER_FILES):
            item = files[name]
            if (not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool)
                    or not 0 < item["bytes"] <= _MAX_FILE_BYTES
                    or not isinstance(item["sha256"], str)
                    or not _HEX64.fullmatch(item["sha256"])):
                raise TokenizerProbeError("invalid tokenizer expected digest or size")
            path = directory / name
            if path.is_symlink():
                raise TokenizerProbeError("tokenizer asset is a symlink")
            attrs = path.stat()
            if not stat.S_ISREG(attrs.st_mode) or attrs.st_size != item["bytes"]:
                raise TokenizerProbeError("tokenizer file identity or size mismatch")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for piece in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(piece)
                    if total > len(_TOKENIZER_FILES) * _MAX_FILE_BYTES:
                        raise TokenizerProbeError("tokenizer assets exceed read budget")
                    digest.update(piece)
            if digest.hexdigest() != item["sha256"]:
                raise TokenizerProbeError("tokenizer content mismatches pinned manifest")
        return {
            "verified_file_count": len(_TOKENIZER_FILES),
            "verified_total_bytes": total,
            "base_id": _MODEL_ID,
            "revision_declared": _REVISION,
            "publisher_origin_authenticated": False,
            "model_loader_custody_qualified": False,
        }
    except TokenizerProbeError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise TokenizerProbeError("tokenizer verification could not complete") from exc


def candidate_prompt(row: dict[str, Any]) -> str:
    """Mirror training.admit_candidates' prompt, without forging admission."""
    if not isinstance(row, dict) or not isinstance(row.get("passage"), str) or not isinstance(row.get("lens"), str):
        raise TokenizerProbeError("candidate is malformed")
    return ("Review the following untrusted literary passage through only the "
            f"{row['lens']} lens. Cite exact short quotations, offer a serious "
            "counterreading and limits, and return ONLY a JSON object with keys "
            "lens_reviews, synthesis, challenges, uncertainties, assessment.\n\n"
            f"PASSAGE:\n{row['passage']}")


def _length_pair(tokenizer: Any, prompt: str, completion: str, *, max_length: int) -> tuple[int, int, int]:
    try:
        vocabulary_size = len(tokenizer)
        prefix = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], tokenize=True,
            add_generation_prompt=True, return_dict=False)
        full = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}, {"role": "assistant", "content": completion}],
            tokenize=True, add_generation_prompt=False, return_dict=False,
        )
    except Exception:
        raise TokenizerProbeError("local chat tokenizer could not encode candidate") from None
    if (type(vocabulary_size) is not int or vocabulary_size <= 0
            or not isinstance(prefix, list) or not isinstance(full, list)
            or not prefix or len(full) <= len(prefix) or full[:len(prefix)] != prefix
            or any(type(tok) is not int or not 0 <= tok < vocabulary_size for tok in full)
            or len(full) > max_length):
        raise TokenizerProbeError("chat template mismatch, invalid token IDs or context overflow")
    # The later CPU-step label contract is [-100] * len(prefix) followed by
    # unmasked completion IDs. Derive and verify that exact boundary here.
    labels = [-100] * len(prefix) + full[len(prefix):]
    if (len(labels) != len(full) or labels[:len(prefix)] != [-100] * len(prefix)
            or labels[len(prefix):] != full[len(prefix):]):
        raise TokenizerProbeError("loss mask prefix is unstable")
    return len(full), len(prefix), len(full) - len(prefix)


def measure_synthetic_candidate(tokenizer: Any, *, max_length: int = 4096) -> dict[str, Any]:
    """Measure all 42 candidate examples with no explicit corpus approval."""
    if type(max_length) is not int or not 128 <= max_length <= 4096:
        raise TokenizerProbeError("max_length must be an integer in 128..4096")
    try:
        candidate = build_candidate()
        rows = candidate["examples"]
        if len(rows) != 42:
            raise TokenizerProbeError("unexpected synthetic candidate count")
        counts: Counter[str] = Counter()
        totals: list[int] = []
        prefixes: list[int] = []
        completions: list[int] = []
        by_split: dict[str, list[int]] = {split: [] for split in ("train", "validation", "holdout")}
        item_sizes: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            prompt = candidate_prompt(row)
            completion = json.dumps(row["target"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            total, prefix, completed = _length_pair(tokenizer, prompt, completion, max_length=max_length)
            counts[row["split"]] += 1
            by_split[row["split"]].append(total)
            totals.append(total)
            prefixes.append(prefix)
            completions.append(completed)
            item_sizes.append({"row_index": index, "split": row["split"],
                               "prompt_tokens_masked": prefix,
                               "completion_tokens_supervised": completed,
                               "total_tokens": total})
        if dict(counts) != {"train": 28, "validation": 7, "holdout": 7}:
            raise TokenizerProbeError("synthetic split counts changed")
        return {
            "schema_version": "aeonith.synthetic_tokenizer_probe.v1",
            "status": "tokenizer_measured_not_training_qualified",
            "candidate_sha256": hashlib.sha256(_serialized(candidate)).hexdigest(),
            "candidate_count": len(rows),
            "split_counts": dict(counts),
            "per_item_token_lengths": item_sizes,
            "token_counts_by_split": {split: {"min": min(values), "max": max(values)}
                                      for split, values in by_split.items()},
            "max_total_tokens": max(totals),
            "max_prompt_tokens_masked": max(prefixes),
            "min_completion_tokens": min(completions),
            "all_loss_masks_prefix_only": True,
            "template_prefix_stable_for_all_candidates": True,
            "max_length_checked": max_length,
            "corpus_admitted": False,
            "model_loaded": False,
            "model_loader_custody_qualified": False,
            "actual_optimizer_steps": 0,
            "trained_adapter_created": False,
            "literary_quality_qualified": False,
        }
    except TokenizerProbeError:
        raise
    except Exception:
        raise TokenizerProbeError("synthetic candidate sizing could not complete") from None


def load_offline_tokenizer(base_dir: Path) -> Any:
    """Optional runtime import, never downloads or constructs model weights."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True,
                                             trust_remote_code=False, use_fast=True)
    except Exception:
        raise TokenizerProbeError("offline tokenizer import or load failed") from None


def probe_live(base_dir: str | Path, *, max_length: int = 4096) -> dict[str, Any]:
    before = verify_tokenizer_assets(base_dir)
    tokenizer = load_offline_tokenizer(_safe_dir(base_dir))
    report = measure_synthetic_candidate(tokenizer, max_length=max_length)
    after = verify_tokenizer_assets(base_dir)
    if before != after:
        raise TokenizerProbeError("tokenizer assets changed during probe")
    report["verified_tokenizer_files"] = before["verified_file_count"]
    report["verified_tokenizer_total_bytes"] = before["verified_total_bytes"]
    report["pinned_base_revision_declared"] = before["revision_declared"]
    report["model_loader_custody_qualified"] = False
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline tokenizer-only candidate sizing; no model/trainer")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--execute", action="store_true", help="Explicit tokenizer-only read; never trains")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_executed", "optimizer_authorized": False}))
        return 2
    try:
        result = probe_live(args.base_dir, max_length=args.max_length)
    except TokenizerProbeError:
        # Never echo untrusted framework exceptions, candidate text, local
        # paths or tokenized private strings in an outward-facing diagnostic.
        print("Tokenizer probe refused; no model load or optimizer authority", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
