"""Checkpoint-scoped, offline long-form review planning.

A checkpoint is a strict source boundary, not consent to send any manuscript.
No pre-checkpoint prose is placed into segment requests or output metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from typing import Any

from .longform import (
    DEFAULT_CHUNK_CHARS,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_CHARS,
    LongformPlanError,
    _read_utf8,
    build_segment_request,
    plan_longform,
)

SCHEMA = "aeonith.checkpoint_plan.v1"
DEFAULT_MARKER = "[ps]"


class CheckpointError(ValueError):
    """The requested source boundary cannot be verified safely."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tail(text: str, marker: str) -> tuple[int, str]:
    if not isinstance(text, str) or not isinstance(marker, str):
        raise CheckpointError("source and marker must be text")
    if not 1 <= len(marker) <= 128 or "\x00" in marker:
        raise CheckpointError("checkpoint marker must have 1 to 128 characters")
    try:
        size = len(text.encode("utf-8"))
        marker.encode("utf-8")
    except UnicodeError as exc:
        raise CheckpointError("source and marker must be valid UTF-8") from exc
    if not text or len(text) > MAX_SOURCE_CHARS or size > MAX_SOURCE_BYTES:
        raise CheckpointError("source exceeds long-form limits or is empty")
    if text.count(marker) != 1:
        raise CheckpointError("checkpoint marker must appear exactly once")
    start = text.index(marker) + len(marker)
    after = text[start:]
    if not after.strip():
        raise CheckpointError("nothing reviewable occurs after checkpoint")
    return start, after


def plan_after_checkpoint(
    text: str,
    *,
    marker: str = DEFAULT_MARKER,
    title: str = "",
    max_chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> dict[str, Any]:
    """Plan exact post-marker source coverage; do not return any raw prose."""
    start, after = _tail(text, marker)
    try:
        segments = plan_longform(
            after, title=title, max_chunk_chars=max_chunk_chars
        )
    except (LongformPlanError, ValueError, UnicodeError) as exc:
        raise CheckpointError("cannot plan exact post-checkpoint coverage") from exc
    return {
        "schema_version": SCHEMA,
        "scope": "after_checkpoint_exclusive",
        "full_source_sha256": _sha256(text),
        "marker_sha256": _sha256(marker),
        "checkpoint_end": start,
        "excluded_prefix_chars": start,
        "eligible_chars": len(after),
        "offset_unit": "unicode_code_points",
        "excerpt_plan": segments,
        "limitations": [
            "Metadata only: no manuscript prose, critique, or provider call.",
            "The marker and all prior text are excluded from every excerpt.",
            "Excerpt reviews do not establish whole-book literary quality.",
        ],
    }


def checkpoint_segment_request(
    text: str, plan: Mapping[str, Any], segment_index: int, *,
    marker: str = DEFAULT_MARKER,
) -> dict[str, Any]:
    """Revalidate the complete source, plan and marker before revealing a segment."""
    if not isinstance(plan, Mapping) or not isinstance(plan.get("excerpt_plan"), Mapping):
        raise CheckpointError("checkpoint plan is required")
    if type(segment_index) is not int:
        raise CheckpointError("segment index must be an integer")
    start, after = _tail(text, marker)
    if (plan.get("schema_version") != SCHEMA
            or plan.get("scope") != "after_checkpoint_exclusive"
            or plan.get("marker_sha256") != _sha256(marker)
            or plan.get("full_source_sha256") != _sha256(text)
            or plan.get("checkpoint_end") != start):
        raise CheckpointError("checkpoint plan does not match source and marker")
    excerpt_plan = plan["excerpt_plan"]
    try:
        canonical = plan_after_checkpoint(
            text, marker=marker,
            title=excerpt_plan.get("title"),
            max_chunk_chars=excerpt_plan.get("max_chunk_chars"),
        )
        if dict(plan) != canonical:
            raise CheckpointError("checkpoint plan metadata was modified")
        request = build_segment_request(after, canonical["excerpt_plan"], segment_index)
    except (LongformPlanError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise CheckpointError("cannot safely build checkpoint-scoped excerpt") from exc
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeonith-checkpoint")
    parser.add_argument("--input", required=True, help="strict UTF-8 manuscript path or -")
    parser.add_argument("--title", default="")
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    args = parser.parse_args(argv)
    try:
        result = plan_after_checkpoint(
            _read_utf8(args.input), marker=args.marker, title=args.title,
            max_chunk_chars=args.chunk_chars,
        )
    except (OSError, ValueError, UnicodeError):
        print("Cannot plan post-checkpoint source: missing, ambiguous or invalid boundary", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
