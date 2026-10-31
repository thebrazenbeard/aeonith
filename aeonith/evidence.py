"""Optional, deterministic source-location sidecar for Aeonith critiques.

This does not change ``aeonith.review.v1`` or promote textual presence into
literary, historical, or formal verification. It only locates exact character
sequences in the caller's supplied work. The caller owns privacy and storage.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from .core import CANONICAL_LENSES

LOCATION_SCHEMA = "aeonith.quote_locations.v1"
MAX_TEXT_CHARS = 200_000
MAX_QUOTE_CHARS = 500
MAX_STORED_SPANS = 32
MAX_SUPPORT_PER_LENS = 12


def _valid_limits(text: Any, max_spans: Any) -> None:
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise ValueError("work text must be a string of at most 200000 characters")
    if type(max_spans) is not int or not 1 <= max_spans <= MAX_STORED_SPANS:
        raise ValueError("max_spans must be an integer from 1 through 32")


def locate_quote(text: str, quote: str, *, max_spans: int = 16) -> dict[str, Any]:
    """Locate every exact, potentially overlapping occurrence of ``quote``.

    Offsets are Python Unicode code-point positions in the *unmodified* input,
    as half-open ``[start, end)`` spans. No case-folding, whitespace repair,
    Unicode normalization, fuzzy matching, or sentence selection occurs. When
    duplicates exist, no occurrence is arbitrarily selected as "intended".

    The total count remains exact even when stored candidate spans are capped.
    """
    _valid_limits(text, max_spans)
    if not isinstance(quote, str) or not quote or len(quote) > MAX_QUOTE_CHARS:
        raise ValueError("quote must be a nonempty string of at most 500 characters")
    spans: list[dict[str, int]] = []
    count = 0
    cursor = 0
    while True:
        start = text.find(quote, cursor)
        if start < 0:
            break
        count += 1
        if len(spans) < max_spans:
            spans.append({"start": start, "end": start + len(quote)})
        cursor = start + 1  # include overlapping occurrences
    return {
        "schema_version": LOCATION_SCHEMA,
        "status": "located" if count else "not_found",
        "unit": "unicode_code_points",
        "match_count": count,
        "ambiguous": count > 1,
        "spans": spans,
        "truncated": count > len(spans),
    }


def audit_review_spans(work_text: str, completed_review: Mapping[str, Any], *, max_spans: int = 16) -> dict[str, Any]:
    """Create a separate location index for a *completed* ``review.v1``.

    The review is not modified. A cited user evidence reference is explicitly
    unverified and cannot be mapped to manuscript offsets. This optional
    sidecar is deliberately not a new claim of source authority.
    """
    _valid_limits(work_text, max_spans)
    if not work_text.strip():
        raise ValueError("completed review must have nonempty work text")
    if not isinstance(completed_review, Mapping) or completed_review.get("status") != "completed":
        raise ValueError("a completed review result is required")
    reviews = completed_review.get("lens_reviews")
    if not isinstance(reviews, list) or not 1 <= len(reviews) <= len(CANONICAL_LENSES):
        raise ValueError("completed review must have a bounded list of lens reviews")

    textual: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    seen_lenses: set[str] = set()
    located_quotes: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, Mapping):
            raise ValueError("lens review is not an object")
        lens = review.get("lens")
        if not isinstance(lens, str) or lens not in CANONICAL_LENSES or lens in seen_lenses:
            raise ValueError("lens must be a unique canonical name")
        seen_lenses.add(lens)
        supports = review.get("support")
        if not isinstance(supports, list) or len(supports) > MAX_SUPPORT_PER_LENS:
            raise ValueError("support list must be bounded")
        for index, item in enumerate(supports):
            if not isinstance(item, Mapping):
                raise ValueError("support must be an object")
            source = item.get("source")
            if source == "work":
                if set(item) != {"source", "quote"}:
                    raise ValueError("unexpected textual support metadata")
                quote = item.get("quote")
                if not isinstance(quote, str) or not quote or len(quote) > MAX_QUOTE_CHARS:
                    raise ValueError("quoted support is not a bounded string")
                if quote not in located_quotes:
                    located_quotes[quote] = locate_quote(work_text, quote, max_spans=max_spans)
                location = deepcopy(located_quotes[quote])
                if location["status"] != "located":
                    raise ValueError("quoted support is absent from work text")
                textual.append({"lens": lens, "support_index": index, "quote": quote, "location": location})
            elif source == "provided_evidence":
                if set(item) != {"source", "ref"}:
                    raise ValueError("unexpected reference support metadata")
                ref = item.get("ref")
                if not isinstance(ref, str) or not ref or len(ref) > 500:
                    raise ValueError("evidence reference ID is invalid")
                external.append({"lens": lens, "support_index": index, "ref": ref, "status": "provided_unverified"})
            else:
                raise ValueError("unknown support source")

    return {
        "schema_version": LOCATION_SCHEMA,
        "status": "annotated",
        "source_text_sha256": hashlib.sha256(work_text.encode("utf-8", errors="surrogatepass")).hexdigest(),
        "offset_unit": "unicode_code_points",
        "textual_anchors": textual,
        "external_refs": external,
        "claim": "exact_textual_location_only_not_interpretive_verification",
    }
