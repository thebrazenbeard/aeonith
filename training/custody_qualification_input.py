"""Source-only experiment: consume exact pinned corpus bytes into immutable memory.

This narrows one gap between ``PinnedPrivateInput`` and an eventual CPU LoRA
consumer: a lexical path is never reopened after a file descriptor is pinned.
The digest expectations are OPERATOR CLAIMS.  This module establishes neither
rights nor same-UID isolation, independent provenance, host resource authority,
model loader safety, or an optimizer permission.  Do not use its receipt to
override the fail-closed training guards.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from .corpus import (
    CorpusError, MAX_LINE_BYTES, SPLITS, _check_isolation, _check_row,
    _unique_object,
)
from .private_input import PinnedPrivateInput, PrivateInputError


PILOT_MAX_SPLIT_BYTES = 4 * 1024 * 1024
PILOT_MAX_TOTAL_BYTES = 8 * 1024 * 1024
PILOT_MAX_ROWS_PER_SPLIT = 512
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PinnedCorpusError(ValueError):
    """A split's pinned bytes could not meet the source-only pilot contract."""


def _reject_constant(_value: str) -> None:
    raise PinnedCorpusError("non-finite JSON constant in pinned corpus")


@dataclass(frozen=True)
class PinnedCorpusPilot:
    """In-memory snapshot; source-file paths are intentionally not retained."""

    rows: Mapping[str, tuple[Mapping[str, Any], ...]]
    split_sha256: Mapping[str, str]
    split_bytes: Mapping[str, int]

    def source_only_receipt(self) -> dict[str, Any]:
        """Text-free diagnostic, deliberately without a qualification token."""
        return {
            "schema_version": "aeonith.pinned_corpus_pilot.v1",
            "status": "source_only_pinned_in_memory_not_training_qualified",
            "split_sha256_operator_supplied": dict(self.split_sha256),
            "split_bytes": dict(self.split_bytes),
            "split_counts": {split: len(self.rows[split]) for split in SPLITS},
            "input_descriptor_read_back": True,
            "rights_and_source_provenance_verified": False,
            "host_process_isolation_verified": False,
            "model_loader_custody_qualified": False,
            "optimizer_authorized": False,
        }


def _parse_split(data: bytes, split: str) -> tuple[Mapping[str, Any], ...]:
    if not data or len(data) > PILOT_MAX_SPLIT_BYTES or not data.endswith(b"\n"):
        raise PinnedCorpusError(f"{split} must be bounded, nonempty newline-terminated JSONL")
    lines = data.splitlines(keepends=True)
    if len(lines) > PILOT_MAX_ROWS_PER_SPLIT:
        raise PinnedCorpusError(f"{split} exceeds pilot row budget")
    rows: list[Mapping[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
            raise PinnedCorpusError(f"{split} row {number} exceeds bounded JSONL line")
        try:
            raw = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
            row = _check_row(raw, split, number)
        except (UnicodeError, ValueError, TypeError, CorpusError) as exc:
            raise PinnedCorpusError(f"{split} row {number} is invalid") from exc
        rows.append(MappingProxyType(dict(row)))
    return tuple(rows)


def snapshot_pinned_corpus(
    handles: Mapping[str, PinnedPrivateInput],
    expected_sha256: Mapping[str, str],
) -> PinnedCorpusPilot:
    """Read three previously-opened trusted descriptors once; freeze all rows.

    All descriptors must remain owned and open by the caller until completion.
    This read does not inspect lexical paths or silently qualify an untrusted
    manifest.  Reject duplicate inodes, malformed digests, and split leakage.
    """
    if (not isinstance(handles, Mapping) or set(handles) != set(SPLITS)
            or not isinstance(expected_sha256, Mapping)
            or set(expected_sha256) != set(SPLITS)):
        raise PinnedCorpusError("exact train/validation/holdout descriptor and digest keys required")
    if any(not isinstance(value, PinnedPrivateInput) for value in handles.values()):
        raise PinnedCorpusError("all corpus inputs must be pinned private descriptors")
    if any(type(value) is not str or not _HEX64.fullmatch(value)
           for value in expected_sha256.values()):
        raise PinnedCorpusError("invalid expected split digest")
    # The pinned object's private identity is captured by fstat at open and
    # rechecked by read_bytes; never use its mutable lexical source path.
    original_ids = {split: handles[split]._identity for split in SPLITS}
    inode_ids = [(original_ids[split][0], original_ids[split][1]) for split in SPLITS]
    if len(set(inode_ids)) != len(SPLITS):
        raise PinnedCorpusError("split descriptors alias one filesystem inode")
    # Check pinned fstat sizes before allocating private plaintext in Python.
    # read_bytes() independently checks the same inode and applies its own
    # caller-supplied limit, which may be larger than this pilot's budget.
    if (any(not 0 < original_ids[split][2] <= PILOT_MAX_SPLIT_BYTES for split in SPLITS)
            or sum(original_ids[split][2] for split in SPLITS) > PILOT_MAX_TOTAL_BYTES):
        raise PinnedCorpusError("pinned corpus exceeds pilot input byte budget")
    bytes_by_split: dict[str, int] = {}
    rows: dict[str, tuple[Mapping[str, Any], ...]] = {}
    total_bytes = 0
    for split in SPLITS:
        try:
            data = handles[split].read_bytes()
        except PrivateInputError as exc:
            raise PinnedCorpusError(f"{split} descriptor changed or is unqualified") from exc
        total_bytes += len(data)
        if total_bytes > PILOT_MAX_TOTAL_BYTES:
            raise PinnedCorpusError("combined corpus exceeds pilot byte budget")
        if hashlib.sha256(data).hexdigest() != expected_sha256[split]:
            raise PinnedCorpusError(f"{split} differs from the expected digest")
        rows[split] = _parse_split(data, split)
        bytes_by_split[split] = len(data)
    try:
        _check_isolation(rows)  # type: ignore[arg-type]  # immutable mappings
    except CorpusError as exc:
        raise PinnedCorpusError("record, prompt, or source crosses corpus splits") from exc
    return PinnedCorpusPilot(
        rows=MappingProxyType(rows),
        split_sha256=MappingProxyType({split: expected_sha256[split] for split in SPLITS}),
        split_bytes=MappingProxyType(bytes_by_split),
    )
