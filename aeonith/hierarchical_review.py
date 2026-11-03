"""Bounded, private, opt-in cross-section *literal motif* evidence.

This intentionally does not synthesize a book's meaning. A phrase repeated in
source-verified critique quotes is a candidate for human interpretation, not
evidence that a particular theme or authorial intention is established.

No provider, filesystem, logging or network operations occur here.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from .book_review import SCHEMA as BATCH_SCHEMA
from .longform import MAX_SEGMENTS, MAX_SOURCE_CHARS

SCHEMA = "aeonith.hierarchical_motif_candidates.v1"
MAX_PHRASES = 16
MAX_ANCHORS = 4096


class HierarchicalReviewError(ValueError):
    """Unverifiable input or exceeded bound; no partial candidate is returned."""


def _digest(text: str) -> str:
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise HierarchicalReviewError("invalid UTF-8 in hierarchical review input") from exc


def _require(test: bool) -> None:
    if not test:
        # Do not include caller manuscript, provider output or phrase in errors.
        raise HierarchicalReviewError("invalid or ungrounded hierarchical review input")


def _phrases(value: Any) -> list[str]:
    _require(isinstance(value, (list, tuple)) and 1 <= len(value) <= MAX_PHRASES)
    _require(all(type(p) is str and 3 <= len(p) <= 80 and p.strip() == p
                 and "\n" not in p and "\r" not in p and "\x00" not in p
                 for p in value))
    _require(len(set(value)) == len(value))
    return list(value)


def _evidence_from_report(source: str, report: Mapping[str, Any]) -> tuple[list[dict[str, Any]], set[int], int]:
    """Rebuild exact quote-source connections and cross-check the index.

    Original source text is mandatory: digest-only provenance is insufficient
    to verify a substring in the correct bounded reviewed excerpt.
    """
    _require(report.get("schema_version") == BATCH_SCHEMA)
    _require(type(report.get("scope")) is str and report.get("scope") in {
        "exact_whole_source_segments_no_synthesis", "after_checkpoint_exclusive",
    })
    _require(report.get("source_sha256") == _digest(source))
    _require(report.get("source_chars") == len(source))
    _require(report.get("whole_book_synthesis") is None)
    index = report.get("cross_segment_evidence_index")
    _require(isinstance(index, Mapping))
    _require(index.get("schema_version") == "aeonith.cross_segment_evidence_index.v1")
    _require(index.get("source_sha256") == _digest(source))
    _require(index.get("semantic_relationships") == "UNASSESSED"
             and index.get("whole_book_interpretation") is None)
    sections, reviews = index.get("sections"), report.get("reviews")
    _require(isinstance(sections, list) and 1 <= len(sections) <= MAX_SEGMENTS)
    _require(isinstance(reviews, list) and len(reviews) <= MAX_SEGMENTS)
    by_id: dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        _require(isinstance(review, Mapping))
        segment_id = review.get("segment_id")
        _require(isinstance(segment_id, str) and segment_id and segment_id not in by_id)
        by_id[segment_id] = review

    expected_ids: set[str] = set()
    verified: list[dict[str, Any]] = []
    completed_sections: set[int] = set()
    completed_count = 0
    planned_count = 0
    previous_end = 0
    for section_index, section in enumerate(sections):
        _require(isinstance(section, Mapping))
        start, end = section.get("start"), section.get("end")
        _require(type(start) is int and type(end) is int
                 and start == previous_end and start < end <= len(source))
        previous_end = end
        _require(section.get("section_index") == section_index)
        segments, evidence_rows = section.get("segments"), section.get("evidence_rows")
        _require(isinstance(segments, list) and segments
                 and isinstance(evidence_rows, list))
        planned_count += len(segments)
        _require(planned_count <= MAX_SEGMENTS)
        expected_evidence: list[dict[str, Any]] = []
        section_completed = 0
        for item in segments:
            _require(isinstance(item, Mapping))
            seg_id, source_sha = item.get("segment_id"), item.get("source_sha256")
            _require(isinstance(seg_id, str) and seg_id and seg_id not in expected_ids)
            _require(isinstance(source_sha, str) and len(source_sha) == 64)
            expected_ids.add(seg_id)
            observed = by_id.get(seg_id)
            status = observed.get("status") if observed is not None else "not_attempted"
            _require(item.get("status") == status)
            if observed is None:
                continue
            seg_start, seg_end = observed.get("start"), observed.get("end")
            _require(type(seg_start) is int and type(seg_end) is int
                     and start <= seg_start < seg_end <= end)
            _require(observed.get("source_sha256") == source_sha)
            piece = source[seg_start:seg_end]
            _require(_digest(piece) == source_sha)
            if status != "completed":
                continue
            section_completed += 1
            completed_count += 1
            completed_sections.add(section_index)
            normalized = observed.get("review")
            _require(isinstance(normalized, Mapping)
                     and normalized.get("status") == "completed")
            lens_reviews = normalized.get("lens_reviews")
            _require(isinstance(lens_reviews, list) and 1 <= len(lens_reviews) <= 20)
            for lens_row in lens_reviews:
                _require(isinstance(lens_row, Mapping))
                lens, basis, supports = (lens_row.get("lens"), lens_row.get("basis"),
                                          lens_row.get("support"))
                _require(isinstance(lens, str) and lens
                         and isinstance(basis, str)
                         and basis in {"textual", "insufficient_text"}
                         and isinstance(supports, list) and len(supports) <= 12)
                work_quotes = []
                supplied_count = 0
                for support in supports:
                    _require(isinstance(support, Mapping))
                    if support.get("source") == "work":
                        quote = support.get("quote")
                        _require(set(support) == {"source", "quote"}
                                 and type(quote) is str and 1 <= len(quote) <= 500
                                 and quote in piece)
                        quote_sha = _digest(quote)
                        work_quotes.append({"quote_sha256": quote_sha, "quote_chars": len(quote)})
                        verified.append({
                            "section_index": section_index, "segment_id": seg_id,
                            "segment_source_sha256": source_sha, "quote": quote,
                            "quote_sha256": quote_sha,
                        })
                        _require(len(verified) <= MAX_ANCHORS)
                    elif support.get("source") == "provided_evidence":
                        _require(set(support) == {"source", "ref"}
                                 and isinstance(support.get("ref"), str))
                        supplied_count += 1
                    else:
                        _require(False)
                expected_evidence.append({
                    "segment_id": seg_id, "lens": lens, "basis": basis,
                    "work_quotes": work_quotes,
                    "provided_reference_count": supplied_count,
                })
        _require(section.get("planned_segments") == len(segments))
        _require(section.get("completed_segments") == section_completed)
        _require(evidence_rows == expected_evidence)
    _require(previous_end == len(source))
    _require(set(by_id) <= expected_ids)
    _require(report.get("planned_segments") == planned_count)
    _require(report.get("completed_segments") == completed_count)
    expected_index_status = (
        "fully_indexed_excerpts" if completed_count == planned_count else
        "partially_indexed_excerpts" if completed_count else
        "failed_without_completed_excerpt" if reviews else "not_attempted"
    )
    _require(index.get("status") == expected_index_status)
    expected_batch_status = (
        "segments_completed" if completed_count == planned_count else
        "provider_unavailable" if not reviews else "incomplete"
    )
    _require(report.get("status") == expected_batch_status)
    return verified, completed_sections, planned_count


def derive_cross_section_motif_candidates(
    source_text: str,
    completed_batch_report: Mapping[str, Any],
    literal_phrases: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Report grounded *lexical* candidate recurrence across reviewed sections.

    The caller opts in with literal phrase hypotheses. A candidate appears only
    when the exact phrase is contained in validated work quotations in at least
    two distinct source sections. This verifies recurrence, NOT a literary
    theme, causal relationship, or a whole-book interpretation.

    Only SHA-256 quote/phrase digests and segment identifiers leave this pure
    function; the supplied manuscript and returned segment critique remain
    entirely in the caller's memory. Do not publish raw batch inputs.
    """
    _require(type(source_text) is str and 1 <= len(source_text) <= MAX_SOURCE_CHARS)
    _require(isinstance(completed_batch_report, Mapping))
    phrases = _phrases(literal_phrases)
    verified, completed_sections, planned_segments = _evidence_from_report(
        source_text, completed_batch_report
    )
    completed_segments = completed_batch_report["completed_segments"]
    # A self-consistent report does not authenticate its original segment
    # boundaries. In particular, an attacker can shorten a reviewed excerpt
    # to a genuine quote and adjust both hashes without changing counts. The
    # quote itself is grounded, but any claimed whole-source coverage is not.
    reported_coverage = ("none" if completed_segments == 0 else
                         "complete" if completed_segments == planned_segments else "partial")
    coverage = ("none" if completed_segments == 0 else
                "report_declared_coverage_unverified")
    candidates: list[dict[str, Any]] = []
    for number, phrase in enumerate(phrases, start=1):
        anchors: list[dict[str, Any]] = []
        seen: set[tuple[int, str, str]] = set()
        for evidence in verified:
            if phrase not in evidence["quote"]:
                continue
            key = (evidence["section_index"], evidence["segment_id"], evidence["quote_sha256"])
            if key in seen:
                continue
            seen.add(key)
            anchors.append({k: evidence[k] for k in (
                "section_index", "segment_id", "segment_source_sha256", "quote_sha256"
            )})
        sections = sorted({anchor["section_index"] for anchor in anchors})
        qualifies = len(sections) >= 2
        candidates.append({
            "candidate_id": f"motif-{number:02d}",
            "literal_phrase_sha256": _digest(phrase),
            "status": ("recurring_literal_candidate" if qualifies
                       else "UNKNOWN_insufficient_cross_section_evidence"),
            "sections_with_anchors": sections if qualifies else [],
            "anchors": anchors if qualifies else [],
            "semantic_interpretation": "UNKNOWN",
        })
    return {
        "schema_version": SCHEMA,
        "source_sha256": _digest(source_text),
        "scope": completed_batch_report["scope"],
        "coverage": {
            "status": coverage, "reported_segment_status": reported_coverage,
            "counts_source": "untrusted_batch_report",
            "report_partition_authenticated": False,
            "planned_segments": planned_segments,
            "completed_segments": completed_segments,
            "sections_with_completed_segments": sorted(completed_sections),
        },
        "semantic_status": "UNKNOWN", "whole_book_synthesis": None,
        "candidates": candidates,
        "limitations": [
            "Only reviewed excerpts and validated literal work-quote anchors were considered.",
            "Repeated wording is not proof of theme, narrative causality or intent.",
            "Section boundaries and segment coverage are report-declared, not independently authenticated.",
            "No cross-section model analysis or provider calls were performed.",
        ],
    }
