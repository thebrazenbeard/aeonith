"""Opt-in, source-guarded batches of *segment* critiques, not whole-book verdicts.

No network call is made without an injected provider. The caller owns provider
cost, manuscript disclosure permissions and private storage of review outputs.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from .core import CANONICAL_LENSES
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


def _cross_segment_evidence_index(
    plan: dict[str, Any], reviews: list[dict[str, Any]], *, offset_scope: str,
) -> dict[str, Any]:
    """Index observed excerpt evidence without inventing a book-level finding.

    The enclosing review report is private. This derivative deliberately
    includes only generic section metadata, segment hashes, lens identifiers,
    evidence counts and short-quote digests—not manuscript or model prose.
    A support quote proves literal inclusion, not an interpretive relationship.
    """
    by_segment = {entry["segment_id"]: entry for entry in reviews}
    section_rows: list[dict[str, Any]] = []
    lens_sections: dict[str, set[int]] = {}
    lens_quote_counts: dict[str, int] = {}
    completed_total = 0
    for section in plan["sections"]:
        section_index = section["section_index"]
        planned = [segment for segment in plan["segments"]
                   if segment["section_index"] == section_index]
        segment_rows: list[dict[str, Any]] = []
        evidence_rows: list[dict[str, Any]] = []
        completed = 0
        attempted = 0
        for segment in planned:
            observed = by_segment.get(segment["segment_id"])
            status = observed["status"] if observed is not None else "not_attempted"
            if observed is not None:
                attempted += 1
            if status == "completed":
                completed += 1
                completed_total += 1
                # `critique` already validated the literal source support of
                # these normalized rows. Retain only provenance pointers;
                # neither this index nor a hash certifies literary quality.
                for lens_row in observed["review"]["lens_reviews"]:
                    lens = lens_row["lens"]
                    quotes = [
                        {
                            "quote_sha256": hashlib.sha256(anchor["quote"].encode("utf-8")).hexdigest(),
                            "quote_chars": len(anchor["quote"]),
                        }
                        for anchor in lens_row["support"] if anchor["source"] == "work"
                    ]
                    evidence_rows.append({
                        "segment_id": segment["segment_id"],
                        "lens": lens,
                        "basis": lens_row["basis"],
                        "work_quotes": quotes,
                        "provided_reference_count": sum(
                            anchor["source"] == "provided_evidence"
                            for anchor in lens_row["support"]
                        ),
                    })
                    if quotes:
                        lens_sections.setdefault(lens, set()).add(section_index)
                        lens_quote_counts[lens] = lens_quote_counts.get(lens, 0) + len(quotes)
            segment_rows.append({
                "segment_id": segment["segment_id"],
                "source_sha256": segment["source_sha256"],
                "status": status,
            })
        section_rows.append({
            "section_index": section_index,
            "label": section["label"],
            "start": section["start"], "end": section["end"],
            "planned_segments": len(planned),
            "attempted_segments": attempted,
            "completed_segments": completed,
            "status": ("complete" if completed == len(planned) else
                       "incomplete" if attempted else "not_attempted"),
            "segments": segment_rows,
            "evidence_rows": evidence_rows,
        })
    return {
        "schema_version": "aeonith.cross_segment_evidence_index.v1",
        "status": ("fully_indexed_excerpts" if completed_total == len(plan["segments"]) else
                   "partially_indexed_excerpts" if completed_total else
                   "failed_without_completed_excerpt" if reviews else "not_attempted"),
        "offset_scope": offset_scope,
        "source_sha256": plan["source_sha256"],
        "sections": section_rows,
        "lens_coverage": [
            {"lens": lens, "sections_with_literal_work_quotes": sorted(section_ids),
             "literal_quote_anchor_count": lens_quote_counts[lens]}
            for lens, section_ids in sorted(lens_sections.items())
        ],
        "semantic_relationships": "UNASSESSED",
        "whole_book_interpretation": None,
        "limitations": [
            "Sections come from heuristic source headings, not verified narrative chapters.",
            "Literal work-quote coverage does not prove a theme, causal link or interpretation.",
            "No cross-section model analysis or additional provider call was performed.",
        ],
    }


def _limits(max_segments: int) -> None:
    if type(max_segments) is not int or not 1 <= max_segments <= MAX_SEGMENTS:
        raise BatchReviewError("max_segments must be an integer between 1 and 512")


def _lenses(lenses: list[str] | tuple[str, ...] | None) -> list[str] | None:
    """Fail closed on malformed lens selection before any provider call."""
    if lenses is None:
        return None  # Keep the preexisting all-lens default for Python callers.
    if (
        not isinstance(lenses, (list, tuple))
        or not 1 <= len(lenses) <= len(CANONICAL_LENSES)
        or any(type(lens) is not str or lens not in CANONICAL_LENSES for lens in lenses)
        or len(set(lenses)) != len(lenses)
    ):
        raise BatchReviewError("lenses must be distinct canonical critical lens names")
    return list(lenses)


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
    lenses: list[str] | tuple[str, ...] | None = None,
    offset_scope: str = "full_submitted_source",
) -> dict[str, Any]:
    _limits(max_segments)
    selected_lenses = _lenses(lenses)
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
        result["cross_segment_evidence_index"] = _cross_segment_evidence_index(
            plan, result["reviews"], offset_scope=offset_scope,
        )
        return result
    for i, segment in enumerate(segments):
        request = request_at(i)
        if selected_lenses is not None:
            request["lenses"] = selected_lenses.copy()
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
    result["cross_segment_evidence_index"] = _cross_segment_evidence_index(
        plan, result["reviews"], offset_scope=offset_scope,
    )
    return result


def review_longform_plan(
    text: str,
    plan: Mapping[str, Any],
    *,
    provider: Any = None,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    lenses: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Review exactly planned excerpts with explicit provider and call budget.

    This function does NOT create a whole-book synthesized critique.
    """
    canonical = _canonical_longform(text, plan)
    _limits(max_segments)
    _lenses(lenses)
    if len(canonical["segments"]) > max_segments:
        raise BatchReviewError("planned segment count exceeds approved call budget")
    return _execute(
        canonical,
        lambda index: build_segment_request(text, canonical, index),
        provider,
        max_segments=max_segments,
        scope="exact_whole_source_segments_no_synthesis",
        lenses=lenses,
    )


def review_checkpoint_plan(
    text: str,
    checkpoint_plan: Mapping[str, Any],
    *,
    provider: Any = None,
    marker: str = DEFAULT_MARKER,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    lenses: list[str] | tuple[str, ...] | None = None,
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
    _lenses(lenses)
    if len(canonical["excerpt_plan"]["segments"]) > max_segments:
        raise BatchReviewError("planned segment count exceeds approved call budget")
    return _execute(
        canonical["excerpt_plan"],
        lambda index: checkpoint_segment_request(text, canonical, index, marker=marker),
        provider,
        max_segments=max_segments,
        scope="after_checkpoint_exclusive",
        full_source_sha256=canonical["full_source_sha256"],
        lenses=lenses,
        offset_scope="eligible_post_checkpoint_source",
    )
