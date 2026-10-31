"""Offline, deterministic source planner for bounded literary excerpts.

Planning never sends, persists, summarizes, or critiques manuscript text.
Segment reviews must not be represented as a whole-book assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .text_input import MAX_OUTPUT_BYTES, MAX_TEXT_CHARS, make_request

SCHEMA = "aeonith.longform_plan.v1"
MAX_SOURCE_CHARS = 2_000_000
MAX_SOURCE_BYTES = 8_000_000
MAX_SEGMENTS = 512
DEFAULT_CHUNK_CHARS = 20_000
SEGMENT_CONTEXT = (
    "This is one bounded excerpt from submitted writing. Critique only the "
    "words supplied here. Do not infer unseen chapters, the entire work, or "
    "the author's intentions from this segment."
)
_MD_HEAD = re.compile(r"^#{1,2}[ \t]+([^\r\n]+)", re.MULTILINE)
_PLAIN_HEAD = re.compile(
    r"^(?:(?:chapter|part|book|section|act)\b[^\r\n]{0,200}|canto[ \t]+(?:[IVXLCDM]+|[0-9]+)\b[^\r\n]{0,180}|prologue|epilogue)[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE,
)


class LongformPlanError(ValueError):
    """Exact source coverage cannot fit the bounded review contract."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _valid_source(text: Any, title: Any, chars: Any, bytes_limit: Any) -> int:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SOURCE_CHARS:
        raise LongformPlanError("source must contain 1 to 2000000 meaningful characters")
    if "\x00" in text:
        raise LongformPlanError("source cannot contain NUL characters")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise LongformPlanError("source must be valid UTF-8") from exc
    if size > MAX_SOURCE_BYTES:
        raise LongformPlanError("source exceeds 8 MB")
    if not isinstance(title, str) or len(title) > 500:
        raise LongformPlanError("title must be 500 characters or fewer")
    try:
        title.encode("utf-8")
    except UnicodeError as exc:
        raise LongformPlanError("title must be valid UTF-8") from exc
    if type(chars) is not int or not 32 <= chars <= MAX_TEXT_CHARS:
        raise LongformPlanError("max_chunk_chars must be 32 to 200000")
    if type(bytes_limit) is not int or not 256 <= bytes_limit <= MAX_OUTPUT_BYTES:
        raise LongformPlanError("max_request_bytes must be 256 to 1000000")
    return size


def _sections(text: str) -> list[tuple[int, int, str]]:
    markers = []
    for matcher, group in ((_MD_HEAD, 1), (_PLAIN_HEAD, 0)):
        for match in matcher.finditer(text):
            markers.append((match.start(), match.group(group)))
            if len(markers) > MAX_SEGMENTS:
                raise LongformPlanError("source has more than 512 major section markers")
    markers.sort(key=lambda p: p[0])
    if not markers:
        return [(0, len(text), "Unsectioned source")]
    sections: list[tuple[int, int, str]] = []
    if markers[0][0] and text[:markers[0][0]].strip():
        sections.append((0, markers[0][0], "Opening material"))
    for i, (offset, label) in enumerate(markers):
        start = 0 if i == 0 and not sections else offset
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        if end > start:
            sections.append((start, end, label.strip()[:120] or "Untitled section"))
    return sections


def _request(piece: str, title: str) -> dict[str, Any]:
    value = make_request(piece, title=title)
    value["context"] = SEGMENT_CONTEXT
    return value


def _request_bytes(piece: str, title: str) -> int:
    value = {
        "schema_version": "aeonith.review.v1",
        "work": {"title": title, "text": piece},
        "context": SEGMENT_CONTEXT,
    }
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _fit_end(text: str, start: int, end: int, title: str, chars: int, budget: int) -> int:
    lower, upper = start, min(end, start + chars)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if _request_bytes(text[start:middle], title) <= budget:
            lower = middle
        else:
            upper = middle - 1
    if lower == start:
        raise LongformPlanError("request budget cannot fit even one source character")
    return lower


def _natural_end(text: str, start: int, end: int) -> tuple[int, str]:
    threshold = start + max(1, (end - start) * 3 // 5)
    paragraph = text.rfind("\n\n", threshold, end)
    if paragraph >= 0:
        return paragraph + 2, "paragraph"
    line = text.rfind("\n", threshold, end)
    if line >= 0:
        return line + 1, "line"
    return end, "hard"


def plan_longform(
    text: str, *, title: str = "",
    max_chunk_chars: int = DEFAULT_CHUNK_CHARS,
    max_request_bytes: int = MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Map every source code point to exactly one valid v1 excerpt request."""
    source_bytes = _valid_source(text, title, max_chunk_chars, max_request_bytes)
    chapters = _sections(text)
    sections = []
    segments = []
    for section_index, (section_start, section_end, label) in enumerate(chapters):
        # Headings can contain names, secrets or unpublished plot details.
        # Public plan metadata must not echo any manuscript line.
        sections.append({
            "section_index": section_index, "label": f"Section {section_index + 1}",
            "start": section_start, "end": section_end,
        })
        start, part = section_start, 0
        while start < section_end:
            limit = _fit_end(text, start, section_end, title, max_chunk_chars, max_request_bytes)
            if limit == section_end:
                end, boundary = limit, "section"
            else:
                end, boundary = _natural_end(text, start, limit)
            # A common chapter ending is a short blank suffix. Keep the last
            # real character with that suffix so no whitespace-only v1
            # request is needed, without omitting or duplicating any codepoint.
            if end < section_end and not text[end:section_end].strip():
                last_visible = end - 1
                while last_visible > start and text[last_visible].isspace():
                    last_visible -= 1
                tail = text[last_visible:section_end]
                if (
                    last_visible > start and tail.strip()
                    and len(tail) <= max_chunk_chars
                    and _request_bytes(tail, title) <= max_request_bytes
                    and text[start:last_visible].strip()
                ):
                    end, boundary = last_visible, "balanced_trailing_whitespace"
            piece = text[start:end]
            if not piece.strip():
                raise LongformPlanError(
                    "source contains an unreviewable whitespace-only span; no text was skipped"
                )
            try:
                _request(piece, title)
            except ValueError as exc:
                raise LongformPlanError("segment violates the v1 input contract") from exc
            req_bytes = _request_bytes(piece, title)
            if req_bytes > max_request_bytes:
                raise AssertionError("planned request exceeds its budget")
            part += 1
            segments.append({
                "segment_id": f"segment-{len(segments) + 1:04d}",
                "section_index": section_index, "section_part": part,
                "start": start, "end": end, "chars": len(piece),
                "source_utf8_bytes": len(piece.encode("utf-8")),
                "request_utf8_bytes": req_bytes,
                "source_sha256": _digest(piece), "boundary": boundary,
            })
            if len(segments) > MAX_SEGMENTS:
                raise LongformPlanError("source exceeds 512-segment safety limit")
            start = end
    if not segments or segments[0]["start"] != 0 or segments[-1]["end"] != len(text):
        raise LongformPlanError("exact source coverage was not achieved")
    if any(segments[i]["end"] != segments[i + 1]["start"] for i in range(len(segments) - 1)):
        raise LongformPlanError("source spans are not contiguous")
    return {
        "schema_version": SCHEMA,
        "source_sha256": _digest(text), "source_chars": len(text),
        "source_utf8_bytes": source_bytes, "title": title,
        "offset_unit": "unicode_code_points",
        "coverage": "exact_contiguous_source",
        "max_chunk_chars": max_chunk_chars, "max_request_bytes": max_request_bytes,
        "sections": sections, "segments": segments,
        "limitations": [
            "This is an excerpt plan, not a critique or whole-book verdict.",
            "Section boundaries are heuristic, not semantic chapter understanding.",
        ],
    }


def build_segment_request(text: str, plan: Mapping[str, Any], segment_index: int) -> dict[str, Any]:
    """Prepare one v1 request and fail closed on source/segment mismatch."""
    if not isinstance(text, str) or not isinstance(plan, Mapping):
        raise LongformPlanError("source text and plan are required")
    if plan.get("schema_version") != SCHEMA:
        raise LongformPlanError("unknown plan schema")
    try:
        matching = plan.get("source_sha256") == _digest(text) and plan.get("source_chars") == len(text)
    except UnicodeError as exc:
        raise LongformPlanError("source must be UTF-8") from exc
    if not matching:
        raise LongformPlanError("source revision differs from plan fingerprint")
    segments = plan.get("segments")
    if (not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS
            or type(segment_index) is not int or not 0 <= segment_index < len(segments)):
        raise LongformPlanError("segment index is invalid")
    chars_limit, bytes_limit = plan.get("max_chunk_chars"), plan.get("max_request_bytes")
    if (type(chars_limit) is not int or not 32 <= chars_limit <= MAX_TEXT_CHARS
            or type(bytes_limit) is not int or not 256 <= bytes_limit <= MAX_OUTPUT_BYTES):
        raise LongformPlanError("plan resource limits are invalid")
    try:
        canonical = plan_longform(
            text, title=plan.get("title"),
            max_chunk_chars=chars_limit, max_request_bytes=bytes_limit,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise LongformPlanError("plan source or limits are invalid") from exc
    # A plan is caller data, not attestation. Canonical replay checks every
    # segment hash, source budget, section field and claimed coverage before
    # even one excerpt is sent to a reviewer.
    if dict(plan) != canonical:
        raise LongformPlanError("plan metadata differs from canonical source coverage")
    previous_end = 0
    for entry in segments:
        if not isinstance(entry, Mapping):
            raise LongformPlanError("plan segment metadata is invalid")
        item_start, item_end = entry.get("start"), entry.get("end")
        if (type(item_start) is not int or type(item_end) is not int
                or item_start != previous_end or not item_start < item_end <= len(text)
                or item_end - item_start > chars_limit):
            raise LongformPlanError("plan segments do not cover the source contiguously")
        previous_end = item_end
    if previous_end != len(text):
        raise LongformPlanError("plan leaves unreviewed source material")
    segment = segments[segment_index]
    if not isinstance(segment, Mapping):
        raise LongformPlanError("segment metadata is invalid")
    start, end = segment.get("start"), segment.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise LongformPlanError("segment offsets are invalid")
    piece = text[start:end]
    if segment.get("source_sha256") != _digest(piece):
        raise LongformPlanError("segment hash mismatch")
    try:
        request = _request(piece, plan.get("title"))
    except (TypeError, ValueError) as exc:
        raise LongformPlanError("invalid v1 segment request") from exc
    request_bytes = _request_bytes(piece, plan["title"])
    if (request_bytes != segment.get("request_utf8_bytes")
            or segment.get("chars") != len(piece)
            or segment.get("source_utf8_bytes") != len(piece.encode("utf-8"))
            or request_bytes > bytes_limit):
        raise LongformPlanError("request differs from planned byte budget")
    return request


def _read_utf8(path: str) -> str:
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
    else:
        target = Path(path)
        if target.stat().st_size > MAX_SOURCE_BYTES:
            raise LongformPlanError("source exceeds 8 MB")
        with target.open("rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise LongformPlanError("source exceeds 8 MB")
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise LongformPlanError("source must be UTF-8") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeonith-longform")
    parser.add_argument("--input", required=True, help="UTF-8 manuscript path or -")
    parser.add_argument("--title", default="")
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--request-bytes", type=int, default=MAX_OUTPUT_BYTES)
    args = parser.parse_args(argv)
    try:
        plan = plan_longform(
            _read_utf8(args.input), title=args.title,
            max_chunk_chars=args.chunk_chars, max_request_bytes=args.request_bytes,
        )
    except (OSError, ValueError, UnicodeError):
        print("Could not plan Aeonith source: invalid UTF-8, source or resource limits", file=sys.stderr)
        return 2
    print(json.dumps(plan, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
