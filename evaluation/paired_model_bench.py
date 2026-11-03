"""Offline admission and blinding of *already generated* base/adapter runs.

This module does not invoke, load, or authenticate any model. It validates
caller-declared frozen-base and adapter outputs against held-out work hashes,
checks their run manifests and structural critiques, and creates private A/B
review artifacts. Literary merit is never inferred from a schema check.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from aeonith.private_output import (
    PrivateOutputDirectory, PrivateOutputError, create_private_directory,
)
from .quality_eval import audit_review, build_blind_pair, digest, make_manifest


class BenchError(ValueError):
    """A paired-model study lacks required source, run, or custody evidence."""


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "aeonith.paired_model_bench.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
SPLITS = ("train", "validation", "holdout")
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_RUNS = 500
MAX_WORKS = 200
MAX_SEEDS = 32


def _exact(value: Any, required: set[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise BenchError(f"invalid {name} fields")
    return value


def _unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for name, value in items:
        if name in obj:
            raise BenchError("duplicate JSON keys are not allowed")
        obj[name] = value
    return obj


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise BenchError("non-finite numeric input is forbidden")
    return value


def _forbid_constant(value: str) -> None:
    raise BenchError("non-finite numeric input is forbidden")


def _private_path(value: str | Path, *, must_exist: bool, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise BenchError(f"{label} symlinks are not allowed")
    # Keep the raw output's components intact: .resolve() follows a linked
    # ancestor, hiding it from the descriptor-pinned private-output boundary.
    path = raw.resolve() if must_exist else Path(os.path.abspath(raw))
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise BenchError(f"{label} must be outside Git checkout")
    if must_exist and not path.is_file():
        raise BenchError(f"private {label} file is missing")
    if not must_exist and (raw.exists() or path.exists()):
        raise BenchError("output directory already exists; never overwrite")
    return path


def _read_private_json(path: Path) -> tuple[dict, str]:
    if not 0 < path.stat().st_size <= MAX_INPUT_BYTES:
        raise BenchError("empty or oversized private run bundle")
    raw = path.read_bytes()
    try:
        bundle = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                            parse_constant=_forbid_constant, parse_float=_finite_float)
    except (UnicodeError, ValueError) as exc:
        raise BenchError("invalid UTF-8 JSON run bundle") from exc
    if not isinstance(bundle, dict):
        raise BenchError("run bundle must be an object")
    return bundle, hashlib.sha256(raw).hexdigest()


def _identity(value: Any, label: str) -> dict:
    obj = _exact(value, {"model_id", "weights_sha256"}, label)
    if (not isinstance(obj["model_id"], str) or not MODEL_NAME.fullmatch(obj["model_id"])
            or not isinstance(obj["weights_sha256"], str)
            or not HEX64.fullmatch(obj["weights_sha256"])):
        raise BenchError(f"invalid {label} model identity")
    return obj


def _split_inventory(value: Any) -> dict[str, dict[str, dict]]:
    raw = _exact(value, set(SPLITS), "split inventory")
    inventories: dict[str, dict[str, dict]] = {}
    source_owner: dict[str, str] = {}
    hash_owner: dict[str, str] = {}
    for split in SPLITS:
        items = raw[split]
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_WORKS:
            raise BenchError(f"missing or oversized {split} split inventory")
        indexed: dict[str, dict] = {}
        for item in items:
            item = _exact(item, {"source_id", "work_sha256"}, "split inventory item")
            identifier, work_hash = item["source_id"], item["work_sha256"]
            if (not isinstance(identifier, str) or not NAME.fullmatch(identifier)
                    or not isinstance(work_hash, str) or not HEX64.fullmatch(work_hash)):
                raise BenchError("invalid split source ID or work fingerprint")
            if identifier in source_owner or work_hash in hash_owner:
                raise BenchError("split overlap in source IDs or exact work fingerprints")
            source_owner[identifier] = split
            hash_owner[work_hash] = split
            indexed[identifier] = item
        inventories[split] = indexed
    if len(inventories["holdout"]) < 2:
        raise BenchError("at least two distinct holdout works are required")
    return inventories


def _source_text(request: Any) -> str:
    if (not isinstance(request, dict) or request.get("schema_version") != "aeonith.review.v1"
            or "proposition" in request or not isinstance(request.get("work"), dict)
            or not isinstance(request["work"].get("text"), str)):
        raise BenchError("invalid held-out literary request")
    text = request["work"]["text"]
    if not text.strip() or len(text) > 200_000:
        raise BenchError("invalid held-out work text")
    return text


def _check_manifest(manifest: Any, request: dict, review: dict, *, model_id: str, seed: int) -> None:
    if not isinstance(manifest, dict):
        raise BenchError("missing run manifest")
    try:
        expected = make_manifest(request, review,
                                 provider_id=manifest["provider_id"],
                                 model_id=manifest["model_id"],
                                 code_revision=manifest["code_revision"],
                                 prompt_revision=manifest["prompt_revision"],
                                 parameters=manifest["parameters"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchError("invalid run manifest fields") from exc
    if (manifest != expected or manifest["model_id"] != model_id
            or manifest["parameters"].get("seed") != seed):
        raise BenchError("run manifest provenance/output/seed mismatch")


def _validated_runs(bundle: dict) -> tuple[list[dict], dict[str, Any]]:
    _exact(bundle, {"schema_version", "experiment_id", "model_identities", "split_inventory", "runs"},
           "paired bench bundle")
    if bundle["schema_version"] != SCHEMA or not isinstance(bundle["experiment_id"], str) or not NAME.fullmatch(bundle["experiment_id"]):
        raise BenchError("invalid paired bench schema or experiment ID")
    models = _exact(bundle["model_identities"], {"base", "adapter"}, "model identities")
    base = _identity(models["base"], "base")
    adapter = _identity(models["adapter"], "adapter")
    if base["model_id"] == adapter["model_id"] or base["weights_sha256"] == adapter["weights_sha256"]:
        raise BenchError("frozen base and adapter must have distinct declared identities")
    inventory = _split_inventory(bundle["split_inventory"])
    raw_runs = bundle["runs"]
    if not isinstance(raw_runs, list) or not 2 <= len(raw_runs) <= MAX_RUNS:
        raise BenchError("paired bench requires a bounded set of model runs")
    seen: set[tuple[str, int]] = set()
    seeds_by_source: dict[str, set[int]] = {}
    request_hashes: dict[str, str] = {}
    status_counts: Counter[str] = Counter()
    validated = []
    common_settings: dict | None = None
    for row in raw_runs:
        _exact(row, {"source_id", "seed", "request", "base_review", "adapter_review",
                     "base_manifest", "adapter_manifest"}, "paired run")
        source, seed = row["source_id"], row["seed"]
        if not isinstance(source, str) or source not in inventory["holdout"]:
            raise BenchError("run source is not in the holdout inventory")
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise BenchError("invalid numeric decoding seed")
        identity = (source, seed)
        if identity in seen:
            raise BenchError("duplicate source/seed run")
        seen.add(identity)
        seeds_by_source.setdefault(source, set()).add(seed)
        request = row["request"]
        text = _source_text(request)
        if digest(text) != inventory["holdout"][source]["work_sha256"]:
            raise BenchError("held-out work fingerprint does not match split inventory")
        req_hash = digest(request)
        if source in request_hashes and request_hashes[source] != req_hash:
            raise BenchError("same holdout work has inconsistent requests across seeds")
        request_hashes[source] = req_hash
        observed_statuses: dict[str, str] = {}
        for name, model in (("base", base), ("adapter", adapter)):
            review = row[f"{name}_review"]
            if not isinstance(review, dict):
                raise BenchError("model result must be a JSON object")
            _check_manifest(row[f"{name}_manifest"], request, review,
                            model_id=model["model_id"], seed=seed)
            try:
                audit = audit_review(request, review)
            except (TypeError, ValueError) as exc:
                raise BenchError("model review cannot be structurally audited") from exc
            status_counts[f"{name}_{audit['structural_status']}"] += 1
            observed_statuses[name] = audit["structural_status"]
        base_manifest = row["base_manifest"]
        adapter_manifest = row["adapter_manifest"]
        settings = {
            "provider_id": base_manifest["provider_id"],
            "code_revision": base_manifest["code_revision"],
            "prompt_revision": base_manifest["prompt_revision"],
            "parameters_except_seed": {k: v for k, v in base_manifest["parameters"].items() if k != "seed"},
        }
        compare_settings = {
            "provider_id": adapter_manifest["provider_id"],
            "code_revision": adapter_manifest["code_revision"],
            "prompt_revision": adapter_manifest["prompt_revision"],
            "parameters_except_seed": {k: v for k, v in adapter_manifest["parameters"].items() if k != "seed"},
        }
        if settings != compare_settings or (common_settings is not None and settings != common_settings):
            raise BenchError("base/adapter comparison settings differ across candidates or runs")
        common_settings = settings
        validated.append({"row": row, "base_status": observed_statuses["base"],
                          "adapter_status": observed_statuses["adapter"]})
    if set(seeds_by_source) != set(inventory["holdout"]):
        raise BenchError("missing holdout work in paired seed grid")
    all_seeds = set.union(*seeds_by_source.values())
    if (not 2 <= len(all_seeds) <= MAX_SEEDS
            or any(seeds != all_seeds for seeds in seeds_by_source.values())):
        raise BenchError("inconsistent or insufficient seed grid across holdout works")
    counts = {split: len(inventory[split]) for split in SPLITS}
    return validated, {"split_counts": counts, "seed_count": len(all_seeds),
                       "distinct_holdout_work_count": len(inventory["holdout"]),
                       "base_structural_failures": status_counts["base_fail"],
                       "adapter_structural_failures": status_counts["adapter_fail"],
                       "base_not_evaluable": status_counts["base_not_evaluable"],
                       "adapter_not_evaluable": status_counts["adapter_not_evaluable"]}


def _new_private_subdir(parent: PrivateOutputDirectory, name: str) -> PrivateOutputDirectory:
    """Create/pin one private child under the already-pinned output root."""
    if name not in {"pairs", "keys"}:
        raise BenchError("unexpected private study subdirectory")
    # The boundary object owns a pinned parent descriptor; using its current
    # handle prevents re-resolving a renameable path after creation.
    parent_fd = parent._directory_fd
    if parent_fd is None:
        raise BenchError("private study output root is closed")
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        attrs = os.fstat(child_fd)
        if (not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != os.geteuid()
                or attrs.st_mode & 0o077):
            raise BenchError("private study subdirectory ownership is not verified")
        return PrivateOutputDirectory(parent.path / name, child_fd)
    except BaseException:
        os.close(child_fd)
        raise


def _private_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False) + "\n"


def prepare(input_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Validate caller-supplied runs and write owner-private A/B artifacts.

    No model process is contacted and no data authority is independently
    checked. Repeated identical outputs across seeds remain recorded, not
    reinterpreted as independent critique variation.
    """
    input_file = _private_path(input_path, must_exist=True, label="bundle")
    output = _private_path(output_dir, must_exist=False, label="output")
    if not output.parent.is_dir():
        raise BenchError("private output parent directory must already exist")
    bundle, bundle_hash = _read_private_json(input_file)
    validated, counts = _validated_runs(bundle)
    pairs: list[tuple[str, dict, dict]] = []
    records: list[dict] = []
    original_pair_ids: Counter[str] = Counter()
    distinct_pair_ids: set[str] = set()
    for item in sorted(validated, key=lambda obj: (obj["row"]["source_id"], obj["row"]["seed"])):
        row = item["row"]
        run_id = digest({"source_id": row["source_id"], "seed": row["seed"]})[:24]
        entry = {"run_id": run_id, "seed": row["seed"],
                 "base_structural_status": item["base_status"],
                 "adapter_structural_status": item["adapter_status"],
                 "pair_id": None}
        if item["base_status"] == item["adapter_status"] == "pass":
            pair, key = build_blind_pair(row["request"], row["base_review"], row["adapter_review"],
                                         bundle["model_identities"]["base"]["model_id"],
                                         bundle["model_identities"]["adapter"]["model_id"],
                                         seed=f"{bundle['experiment_id']}:{row['seed']}:{run_id}")
            # The underlying helper assigns a content-only pair ID. Two
            # deterministic generations can have identical contents across
            # seeds but opposite A/B orientations. The human study aggregator
            # rejects duplicate pair IDs; qualify each display by its run.
            original_content_pair_id = pair["pair_id"]
            original_pair_ids[original_content_pair_id] += 1
            run_pair_id = digest({"content_pair_id": original_content_pair_id,
                                  "experiment_id": bundle["experiment_id"],
                                  "run_id": run_id})[:24]
            if run_pair_id in distinct_pair_ids:
                raise BenchError("run-qualified blind pair ID collision")
            distinct_pair_ids.add(run_pair_id)
            pair["pair_id"] = run_pair_id
            key["pair_id"] = run_pair_id
            key["source_content_pair_id"] = original_content_pair_id
            entry["pair_id"] = run_pair_id
            pairs.append((run_id, pair, key))
        records.append(entry)
    receipt = {
        "schema_version": "aeonith.paired_model_bench_receipt.v1",
        "status": "paired_run_validated_not_quality_qualified",
        "experiment_id": bundle["experiment_id"],
        "bundle_sha256": bundle_hash,
        "split_counts": counts["split_counts"],
        "run_count": len(validated),
        "seed_count": counts["seed_count"],
        "distinct_holdout_work_count": counts["distinct_holdout_work_count"],
        "blinded_pair_count": len(pairs),
        "repeated_content_pair_count": sum(c - 1 for c in original_pair_ids.values() if c > 1),
        "base_structural_failures": counts["base_structural_failures"],
        "adapter_structural_failures": counts["adapter_structural_failures"],
        "base_not_evaluable": counts["base_not_evaluable"],
        "adapter_not_evaluable": counts["adapter_not_evaluable"],
        "runs": records,
        "model_execution_authenticated": False,
        "holdout_custody_independently_verified": False,
        "semantic_quality": "UNASSESSED",
        "model_ranking": "NOT_COMPUTED; collect independent blinded human ratings",
        "limitations": [
            "source IDs, model weights hashes and run manifests are caller-declared, not authenticated",
            "exact work hash isolation cannot detect paraphrases or memorized sources",
            "run-qualified pair IDs remain distinct across seeds; repeated content is counted separately and is not independent quality evidence",
            "non-completed reviews and structural failures remain in the run denominator",
            "the A/B display contains private manuscript text and must stay with an authorized reviewer",
        ],
    }
    # Complete admission occurs in memory before any effect. The root and
    # child directories are pinned and every file is exclusively created via
    # their descriptor handles; unqualified Windows ACLs fail closed.
    # Crash leftovers remain visible for owner inspection, never overwritten.
    with create_private_directory(output) as private_root:
        with _new_private_subdir(private_root, "pairs") as pair_dir:
            with _new_private_subdir(private_root, "keys") as key_dir:
                for run_id, pair, key in pairs:
                    pair_dir.write_text(f"{run_id}.json", _private_json(pair))
                    key_dir.write_text(f"{run_id}.json", _private_json(key))
        private_root.write_text("bench_receipt.json", _private_json(receipt))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline audit/blind preparation of caller-generated base/adapter results")
    cmds = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = cmds.add_parser("prepare", help="Validate runs and create private blinded displays/keys")
    prepare_cmd.add_argument("--bundle", type=Path, required=True)
    prepare_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare(args.bundle, args.output)
        print(json.dumps(report, sort_keys=True))
        return 0
    except (BenchError, PrivateOutputError, OSError, UnicodeError) as exc:
        print(f"Paired evaluation unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
