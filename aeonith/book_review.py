"""Opt-in, source-guarded batches of *segment* critiques, not whole-book verdicts.

No network call is made without an injected provider. The caller owns provider
cost, manuscript disclosure permissions and private storage of review outputs.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .checkpoint import (
    DEFAULT_MARKER,
    CheckpointError,
    checkpoint_segment_request,
    plan_after_checkpoint,
)
from .core import critique
from .longform import (
    MAX_SEGMENTS,
    LongformPlanError,
    build_segment_request,
    plan_longform,
)

SCHEMA = "aeonith.segment_batch.v1"
DEFAULT_MAX_SEGMENTS = 8


class BatchReviewError(ValueError):
    """Preflight failed before any provider request was sent."""


def _limits(max_segments: int) -> None:
    if type(max_segments) is not int or not 1 <= max_segments <= MAX_SEGMENTS:
        raise BatchReviewError("max_segments must be an integer between 1 and 512")


def _canonical_longform(text: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(text, str) or not isinstance(plan, Mapping):
        raise BatchReviewError("source text and plan are required")
    try:
        canonical = plan_longform(
            text,
            title=plan.get("title"),
            max_chunk_chars=plan.get("max_chunk_chars"),
            max_request_bytes=plan.get("max_request_bytes"),
        )
    except (LongformPlanError, ValueError, TypeError, UnicodeError) as exc:
        raise BatchReviewError("invalid source or long-form plan") from exc
    if dict(plan) != canonical:
        raise BatchReviewError("long-form plan is not canonical for this source")
    return canonical


def _execute(
    plan: dict[str, Any],
    request_at: Any,
    provider: Any,
    *,
    max_segments: int,
    scope: str,
    full_source_sha256: str | None = None,
) -> dict[str, Any]:
    _limits(max_segments)
    segments = plan["segments"]
    if len(segments) > max_segments:
        raise BatchReviewError("planned segment count exceeds approved call budget")
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "provider_unavailable" if provider is None else "incomplete",
        "scope": scope,
        "source_sha256": plan["source_sha256"],
        "full_source_sha256": full_source_sha256 or plan["source_sha256"],
        "source_chars": plan["source_chars"],
        "planned_segments": len(segments),
        "attempted_segments": 0,
        "completed_segments": 0,
        "attempted_chars": 0,
        "completed_chars": 0,
        "reviews": [],
        "whole_book_synthesis": None,
        "limitations": [
            "This batches bounded excerpt reviews; there is no cross-chapter synthesis.",
            "A completed segment is not a verified literary interpretation.",
            "The provider and its returned reviews may process private manuscript prose.",
        ],
    }
    if provider is None:
        return result
    for i, segment in enumerate(segments):
        request = request_at(i)
        review = critique(request, provider)
        status = review.get("status")
        entry = {
            "segment_id": segment["segment_id"],
            "start": segment["start"],
            "end": segment["end"],
            "source_sha256": segment["source_sha256"],
            "status": status,
            # Full provider responses are private author/editor data.
            "review": review,
        }
        result["reviews"].append(entry)
        result["attempted_segments"] += 1
        result["attempted_chars"] += segment["chars"]
        if status == "completed":
            result["completed_segments"] += 1
            result["completed_chars"] += segment["chars"]
        else:
            # Stop to avoid paid calls after an observed provider/validation failure.
            break
    if result["completed_segments"] == len(segments):
        result["status"] = "segments_completed"
    else:
        result["status"] = "incomplete"
    return result


def review_longform_plan(
    text: str,
    plan: Mapping[str, Any],
    *,
    provider: Any = None,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> dict[str, Any]:
    """Review exactly planned excerpts with explicit provider and call budget.

    This function does NOT create a whole-book synthesized critique.
    """
    canonical = _canonical_longform(text, plan)
    _limits(max_segments)
    if len(canonical["segments"]) > max_segments:
        raise BatchReviewError("planned segment count exceeds approved call budget")
    return _execute(
        canonical,
        lambda index: build_segment_request(text, canonical, index),
        provider,
        max_segments=max_segments,
        scope="exact_whole_source_segments_no_synthesis",
    )


def review_checkpoint_plan(
    text: str,
    checkpoint_plan: Mapping[str, Any],
    *,
    provider: Any = None,
    marker: str = DEFAULT_MARKER,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> dict[str, Any]:
    """Review only text AFTER a unique author marker, never preceding prose."""
    if not isinstance(checkpoint_plan, Mapping):
        raise BatchReviewError("checkpoint plan is required")
    excerpt_plan = checkpoint_plan.get("excerpt_plan")
    if not isinstance(excerpt_plan, Mapping):
        raise BatchReviewError("checkpoint plan is invalid")
    try:
        canonical = plan_after_checkpoint(
            text,
            marker=marker,
            title=excerpt_plan.get("title"),
            max_chunk_chars=excerpt_plan.get("max_chunk_chars"),
        )
    except (CheckpointError, ValueError, TypeError) as exc:
        raise BatchReviewError("checkpoint source is invalid") from exc
    if dict(checkpoint_plan) != canonical:
        raise BatchReviewError("checkpoint plan is not canonical for this source")
    _limits(max_segments)
    if len(canonical["excerpt_plan"]["segments"]) > max_segments:
        raise BatchReviewError("planned segment count exceeds approved call budget")
    return _execute(
        canonical["excerpt_plan"],
        lambda index: checkpoint_segment_request(text, canonical, index, marker=marker),
        provider,
        max_segments=max_segments,
        scope="after_checkpoint_exclusive",
        full_source_sha256=canonical["full_source_sha256"],
    )
