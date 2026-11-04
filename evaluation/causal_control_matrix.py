"""Strict, offline accounting for *declared* multi-arm held-out outcomes.

This is an observation/experiment-custody validator, NOT a model runner,
randomization attestor, human-quality evaluator, or causal-effect proof.
It intentionally never opens private files, loads models, or contacts a host.
"""

from __future__ import annotations

from collections import Counter
import math
from typing import Any

from .paired_model_bench import BenchError, HEX64, MAX_SEEDS, NAME, _split_inventory
from .quality_eval import digest


SCHEMA = "aeonith.causal_control_matrix.v1"
REQUIRED_ARMS = ("frozen_base", "trained_adapter", "shuffled_feedback_adapter")
OPTIONAL_ARMS = ("disabled_head_adapter",)
MAX_CELLS = 512


class ControlMatrixError(ValueError):
    """The experiment has a missing, inconsistent, or confounded declared cell."""


def _object(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ControlMatrixError(f"{name} has invalid fields")
    return value


def inspect_control_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    """Audit a complete work × seed × arm grid, including failed attempts.

    Numeric outcomes remain caller-declared and only descriptive paired
    differences are returned. Different arm hashes are *not* proof of real
    model identity, independent initialization, randomized training or outcome.
    """
    _object(bundle, {"schema_version", "experiment_id", "outcome_origin",
                     "outcome_metric", "split_inventory", "arms", "seeds", "runs"},
            "control matrix")
    if bundle["schema_version"] != SCHEMA:
        raise ControlMatrixError("unsupported control matrix schema")
    if not isinstance(bundle["experiment_id"], str) or not NAME.fullmatch(bundle["experiment_id"]):
        raise ControlMatrixError("invalid experiment ID")
    if bundle["outcome_origin"] not in ("synthetic", "operator_declared"):
        raise ControlMatrixError("outcomes must declare synthetic or operator-declared origin")
    if not isinstance(bundle["outcome_metric"], str) or not NAME.fullmatch(bundle["outcome_metric"]):
        raise ControlMatrixError("invalid outcome metric name")
    try:
        inventory = _split_inventory(bundle["split_inventory"])
    except BenchError as exc:
        raise ControlMatrixError(str(exc)) from exc

    arms = bundle["arms"]
    if (not isinstance(arms, dict) or not set(REQUIRED_ARMS).issubset(arms)
            or set(arms) - set(REQUIRED_ARMS) - set(OPTIONAL_ARMS)):
        raise ControlMatrixError("frozen, trained and shuffled-feedback arms are required")
    hashes: set[str] = set()
    identities: set[str] = set()
    for name, raw in arms.items():
        arm = _object(raw, {"artifact_id", "sha256"}, name)
        if (not isinstance(arm["artifact_id"], str)
                or not NAME.fullmatch(arm["artifact_id"])
                or not isinstance(arm["sha256"], str) or not HEX64.fullmatch(arm["sha256"])):
            raise ControlMatrixError("invalid declared arm identity")
        if arm["sha256"] in hashes or arm["artifact_id"] in identities:
            raise ControlMatrixError("declared arm artifact identities must differ")
        hashes.add(arm["sha256"])
        identities.add(arm["artifact_id"])

    seeds = bundle["seeds"]
    if (not isinstance(seeds, list) or not 2 <= len(seeds) <= MAX_SEEDS
            or any(type(s) is not int or not 0 <= s <= 2**32 - 1 for s in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ControlMatrixError("two or more distinct integer seeds must be pre-registered")
    holdout_ids = set(inventory["holdout"])
    expected_count = len(holdout_ids) * len(seeds) * len(arms)
    if expected_count > MAX_CELLS:
        raise ControlMatrixError("experiment exceeds bounded control matrix")
    rows = bundle["runs"]
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ControlMatrixError("all attempted arm/work/seed cells, including failures, are required")

    observed: dict[tuple[str, int, str], float | None] = {}
    requests: dict[tuple[str, int], str] = {}
    statuses: Counter[str] = Counter()
    for raw in rows:
        row = _object(raw, {"source_id", "seed", "arm", "request_sha256", "status", "outcome"}, "run")
        source, seed, arm = row["source_id"], row["seed"], row["arm"]
        if (not isinstance(source, str) or source not in holdout_ids
                or type(seed) is not int or seed not in seeds
                or not isinstance(arm, str) or arm not in arms):
            raise ControlMatrixError("run references undeclared arm, holdout, or seed")
        key = (source, seed, arm)
        if key in observed:
            raise ControlMatrixError("duplicate control matrix cell")
        request_hash = row["request_sha256"]
        if not isinstance(request_hash, str) or not HEX64.fullmatch(request_hash):
            raise ControlMatrixError("invalid request fingerprint")
        request_key = (source, seed)
        if request_key in requests and requests[request_key] != request_hash:
            raise ControlMatrixError("arms did not receive identical declared request bytes")
        requests[request_key] = request_hash
        status = row["status"]
        outcome = row["outcome"]
        if status == "observed":
            if type(outcome) not in (float, int) or not math.isfinite(outcome) or not 0 <= outcome <= 1:
                raise ControlMatrixError("observed outcome must be a finite normalized score")
            observed[key] = float(outcome)
        elif status == "unavailable":
            if outcome is not None:
                raise ControlMatrixError("unavailable runs cannot contain invented scores")
            observed[key] = None
        else:
            raise ControlMatrixError("run status must be observed or unavailable")
        statuses[status] += 1

    reference = "trained_adapter"
    paired_deltas: dict[str, list[float]] = {arm: [] for arm in arms if arm != reference}
    complete = 0
    for source in sorted(holdout_ids):
        for seed in sorted(seeds):
            values = {arm: observed[(source, seed, arm)] for arm in arms}
            if any(value is None for value in values.values()):
                continue
            complete += 1
            for arm in paired_deltas:
                paired_deltas[arm].append(values[reference] - values[arm])
    expected_pairs = len(holdout_ids) * len(seeds)
    return {
        "schema_version": "aeonith.causal_control_matrix_receipt.v1",
        "status": "complete_declared_descriptive_not_causal" if complete == expected_pairs
                  else "incomplete_declared_descriptive_not_causal",
        "experiment_id": bundle["experiment_id"],
        "input_sha256": digest(bundle),
        "outcome_origin": bundle["outcome_origin"],
        "holdout_works": len(holdout_ids),
        "seeds": len(seeds),
        "declared_arm_count": len(arms),
        "attempted_cells": expected_count,
        "observed_cells": statuses["observed"],
        "unavailable_cells": statuses["unavailable"],
        "complete_paired_work_seed_cells": complete,
        "expected_paired_work_seed_cells": expected_pairs,
        "trained_minus_control_mean": {
            arm: (sum(deltas) / len(deltas) if deltas else None)
            for arm, deltas in sorted(paired_deltas.items())
        },
        "causal_effect_qualified": False,
        "model_execution_verified": False,
        "human_literary_quality_qualified": False,
        "note": "Caller-declared numbers and artifacts; no model, randomization, holdout novelty or independent ratings authenticated.",
    }
