"""Text-free split inventory for the *visible*, unadmitted synthetic pilot.

This is a compatibility bridge to the existing paired-bench/control-matrix
accounting schemas. It never generates outcomes, loads models, admits training
data, writes a file, or asserts that the source-visible holdout is blind.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .paired_model_bench import BenchError, _split_inventory
from .quality_eval import digest
from training.corpus import SPLITS
from training.synthetic_pilot import _serialized, build_candidate, validate_candidate


class SyntheticInventoryError(ValueError):
    """A proposed synthetic inventory could not be verified."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def inspect_synthetic_inventory(
    candidate: dict[str, Any] | None = None,
    *,
    expected_candidate_sha256: str,
) -> dict[str, Any]:
    """Return hash-only split inventory with explicit non-blind caveats.

    The expected digest must come from the operator's separately observed
    candidate bytes. It is *not* proof of authorship, novelty, or custody.
    """
    if not isinstance(expected_candidate_sha256, str) or not _SHA256.fullmatch(expected_candidate_sha256):
        raise SyntheticInventoryError("a pinned candidate SHA-256 is required")
    if candidate is None:
        candidate = build_candidate()
    try:
        validate_candidate(candidate)
        actual_sha = hashlib.sha256(_serialized(candidate)).hexdigest()
        if actual_sha != expected_candidate_sha256:
            raise SyntheticInventoryError("candidate fingerprint differs from the pinned proposal")
        inventory = {
            split: [
                {"source_id": row["source_id"], "work_sha256": digest(row["passage"])}
                for row in candidate["examples"] if row["split"] == split
            ]
            for split in SPLITS
        }
        _split_inventory(inventory)
    except SyntheticInventoryError:
        raise
    except (ValueError, TypeError, KeyError, BenchError) as exc:
        raise SyntheticInventoryError("synthetic split inventory verification failed") from exc
    return {
        "schema_version": "aeonith.synthetic_holdout_inventory.v1",
        "status": "source_visible_synthetic_inventory_not_blind_qualified",
        "candidate_sha256": actual_sha,
        "split_inventory": inventory,
        "split_counts": {split: len(inventory[split]) for split in SPLITS},
        "passes_declared_hash_inventory_contract": True,
        "model_executions_authenticated": False,
        "holdout_custody_protected": False,
        "holdout_blind_qualified": False,
        "independent_holdout_novelty_established": False,
        "genuine_unseen_outcome_tasks_established": False,
        "synthetic_targets_accessible_in_source": True,
        "operator_admission_authorized": False,
        "actual_optimizer_steps": 0,
        "causal_learning_qualified": False,
        "note": (
            "Hash-only inventory is usable for declared run accounting; "
            "the synthetic passage texts and targets exist in accessible source, "
            "so it cannot attest blind or genuinely unseen evaluation."
        ),
    }
