"""Prepare source-exact private excerpts in memory, without reviewing them.

This module does not read a repository or authenticate its caller. The caller
must obtain ``trusted_selection`` from *separate, private, authoritative*
custody; passing the same attacker-controlled record as both inputs provides
no provenance guarantee. No model, filesystem, network or persistence exists
here, and no excerpt is a verdict about the surrounding manuscript.

Returned excerpt text and source metadata are **PRIVATE CALLER MEMORY**. Never
serialize these objects into public logging, CI artifacts, or issue comments.
Only ``manifest.report()`` is deliberately sanitized for routine diagnostics.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field


SCHEMA = "aeonith.editorial_excerpt_manifest.v1"
MAX_EXCERPT_CHARS = 12_000
MAX_SOURCE_CHARS = 1_000_000
MAX_SOURCE_UTF8_BYTES = 3_000_000
MAX_EXCERPTS = 256

_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PARAGRAPH_BREAK = re.compile(r"(?:\r?\n[ \t]*){2,}")


class ExcerptManifestError(ValueError):
    """Sanitized fixed-code rejection; intentionally contains no user data."""


@dataclass(frozen=True, slots=True, repr=False)
class SourceRecord:
    """Opaque private revision identity, not a provenance attestation itself."""

    source_id: str
    revision_id: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedExcerpt:
    """A complete Unicode code-point slice with private source references."""

    index: int
    start: int
    end: int
    boundary: str
    text: str = field(repr=False)
    source_id: str = field(repr=False)
    revision_id: str = field(repr=False)
    source_sha256: str = field(repr=False)
    excerpt_sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ExcerptManifest:
    """Privacy-sensitive in-memory coverage and excerpt material."""

    source_chars: int
    source_utf8_bytes: int
    coverage: str
    offset_unit: str
    gaps: tuple[tuple[int, int], ...]
    source_record: SourceRecord = field(repr=False)
    excerpts: tuple[PreparedExcerpt, ...] = field(repr=False)
    schema_version: str = SCHEMA
    privacy: str = "PRIVATE_CALLER_MEMORY"

    def report(self) -> dict[str, object]:
        """Expose only fixed codes and numeric coverage, never prose or IDs."""
        return {
            "schema_version": SCHEMA,
            "status": "READY",
            "coverage": self.coverage,
            "offset_unit": self.offset_unit,
            "source_chars": self.source_chars,
            "covered_chars": self.source_chars - sum(end - start for start, end in self.gaps),
            "gap_count": len(self.gaps),
            "excerpt_count": len(self.excerpts),
            "issue_codes": (),
            "semantic_quality": "UNASSESSED",
        }


def _check_record(record: SourceRecord) -> None:
    if (
        type(record) is not SourceRecord
        or type(record.source_id) is not str
        or _OPAQUE_ID.fullmatch(record.source_id) is None
        or type(record.revision_id) is not str
        or _OPAQUE_ID.fullmatch(record.revision_id) is None
        or type(record.source_sha256) is not str
        or _SHA256.fullmatch(record.source_sha256) is None
    ):
        raise ExcerptManifestError("INVALID_RECORD")


def _encode_utf8_or_none(value: str) -> bytes | None:
    """Contain UnicodeEncodeError and its private ``object`` before rejection.

    Raising a sanitized exception *inside* ``except UnicodeError`` would
    still retain the original text in ``__context__`` for log collectors.
    """
    try:
        return value.encode("utf-8", "strict")
    except UnicodeError:
        return None


def _paragraph_aware_end(text: str, start: int, limit: int) -> tuple[int, str]:
    if limit == len(text):
        return limit, "source_end"
    # A natural break must not turn an arbitrarily short paragraph into a
    # pathological number of excerpts. Preserve the break itself in the slice.
    threshold = start + max(1, (limit - start) // 3)
    last_break = None
    for match in _PARAGRAPH_BREAK.finditer(text, threshold, limit):
        last_break = match.end()
    if last_break is not None and start < last_break <= limit:
        return last_break, "paragraph"
    return limit, "limit"


def prepare_excerpt_manifest(
    trusted_selection: SourceRecord,
    submitted: SourceRecord,
    text: str,
    *,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
) -> ExcerptManifest:
    """Verify exact UTF-8 source and prepare complete <=12k code-point slices.

    ``trusted_selection`` must have been separately authenticated by the
    caller's private source-of-truth workflow. ``submitted`` is the candidate
    record accompanying ``text`` and cannot override that selection. Neither
    a matching hash nor this function's success proves creative quality.

    Raises ``ExcerptManifestError`` with a fixed non-disclosing code. No
    partial manifest is returned when source or resource validation fails.
    """
    _check_record(trusted_selection)
    _check_record(submitted)
    if submitted != trusted_selection:
        raise ExcerptManifestError("SELECTION_MISMATCH")
    if type(max_excerpt_chars) is not int or not 1 <= max_excerpt_chars <= MAX_EXCERPT_CHARS:
        raise ExcerptManifestError("INVALID_LIMIT")
    if type(text) is not str or not text:
        raise ExcerptManifestError("INVALID_SOURCE")
    if len(text) > MAX_SOURCE_CHARS:
        raise ExcerptManifestError("SOURCE_TOO_LARGE")
    if not text.strip() or "\x00" in text:
        raise ExcerptManifestError("INVALID_SOURCE")
    encoded = _encode_utf8_or_none(text)
    if encoded is None:
        raise ExcerptManifestError("INVALID_SOURCE")
    if len(encoded) > MAX_SOURCE_UTF8_BYTES:
        raise ExcerptManifestError("SOURCE_TOO_LARGE")
    if not hmac.compare_digest(hashlib.sha256(encoded).hexdigest(), trusted_selection.source_sha256):
        raise ExcerptManifestError("SOURCE_HASH_MISMATCH")
    # Bound even deliberately tiny slices before constructing an output.
    if (len(text) + max_excerpt_chars - 1) // max_excerpt_chars > MAX_EXCERPTS:
        raise ExcerptManifestError("TOO_MANY_EXCERPTS")

    excerpts = []
    start = 0
    while start < len(text):
        limit = min(start + max_excerpt_chars, len(text))
        end, boundary = _paragraph_aware_end(text, start, limit)
        piece = text[start:end]
        if not piece or end <= start:
            raise ExcerptManifestError("COVERAGE_FAILED")
        # A provider v1 review of an all-whitespace excerpt is invalid. Fail
        # closed instead of dropping that source span or claiming readiness.
        if not piece.strip():
            raise ExcerptManifestError("UNREVIEWABLE_EXCERPT")
        if len(excerpts) == MAX_EXCERPTS:
            raise ExcerptManifestError("TOO_MANY_EXCERPTS")
        excerpts.append(
            PreparedExcerpt(
                index=len(excerpts), start=start, end=end, boundary=boundary,
                text=piece, source_id=trusted_selection.source_id,
                revision_id=trusted_selection.revision_id,
                source_sha256=trusted_selection.source_sha256,
                excerpt_sha256=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
            )
        )
        start = end

    if start != len(text) or any(
        excerpts[i].end != excerpts[i + 1].start
        for i in range(len(excerpts) - 1)
    ):
        raise ExcerptManifestError("COVERAGE_FAILED")

    return ExcerptManifest(
        source_chars=len(text), source_utf8_bytes=len(encoded),
        coverage="EXACT_CONTIGUOUS", offset_unit="unicode_code_points",
        gaps=(), source_record=trusted_selection, excerpts=tuple(excerpts),
    )
