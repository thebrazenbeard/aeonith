"""Render an Aeonith review result as readable, escaped Markdown.

This is a presentation layer for the existing ``aeonith.review.v1`` contract.
It never invokes a model, verifies a source, or grants revision authority.

After integration, run ``python -m aeonith.formatting --input result.json``.
The module also runs directly during isolated development.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SCHEMA = "aeonith.review.v1"
MAX_INPUT_BYTES = 2_097_152
LENS_LABELS = {
    "psychological": "Psychological",
    "literary_thematic": "Literary and thematic",
    "narrative_structure": "Narrative structure",
    "character_development": "Character development",
    "historical_cultural": "Historical and cultural",
    "philosophical": "Philosophical",
    "genre_specific": "Genre-specific",
    "stylistic": "Stylistic",
    "sociological": "Sociological",
    "moral_ethical": "Moral and ethical",
    "symbolic": "Symbolic",
    "reader_response": "Reader-response",
    "linguistic": "Linguistic",
    "comparative": "Comparative",
}
EXIT_CODES = {
    "completed": 0,
    "invalid_request": 2,
    "provider_unavailable": 3,
    "provider_error": 4,
    "invalid_provider_output": 5,
}


class InvalidReview(ValueError):
    """Input does not match the minimum Aeonith result presentation contract."""


def _escape(value: str) -> str:
    """Escape raw HTML and Markdown controls from arbitrary provider text."""
    # Model output is also displayed in terminals. Strip control bytes, bidi
    # overrides and lone surrogates so a quoted passage cannot operate a
    # terminal or visually reverse a safety/status label.
    unsafe_bidi = {0x061C, 0x200E, 0x200F} | set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
    cleaned = "".join(
        "\ufffd"
        if (
            (ord(char) < 32 and char not in "\n\t")
            or 0x7F <= ord(char) <= 0x9F
            or 0xD800 <= ord(char) <= 0xDFFF
            or ord(char) in unsafe_bidi
        )
        else char
        for char in value
    )
    rendered = html.escape(cleaned, quote=False)
    rendered = re.sub(r"([\\`*_~$\[\]()!#|>])", r"\\\1", rendered)
    lines = rendered.splitlines() or [""]
    escaped_lines: list[str] = []
    for line in lines:
        line = re.sub(r"^([ \t]*)([-+])(?=\s)", r"\1\\\2", line)
        line = re.sub(r"^([ \t]*)(-{3,})(?=\s*$)", lambda match: match[1] + "\\" + match[2], line)
        line = re.sub(r"^([ \t]*)(\d{1,9})(\.)(?=\s)", r"\1\2\\\3", line)
        escaped_lines.append(line)
    return "\n".join(escaped_lines)


def _line(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InvalidReview("expected a nonempty bounded text field")
    return _escape(value.strip())


def _items(value: Any, limit: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit:
        raise InvalidReview("expected a bounded list")
    return value


def _support_lines(support: Any) -> list[str]:
    lines: list[str] = []
    for item in _items(support, 12):
        if not isinstance(item, Mapping):
            raise InvalidReview("support item is not an object")
        if item.get("source") == "work" and set(item) == {"source", "quote"}:
            lines.append(f"- Submitted text: “{_line(item.get('quote'), 500)}”")
        elif item.get("source") == "provided_evidence" and set(item) == {"source", "ref"}:
            lines.append(f"- Supplied reference (unverified): {_line(item.get('ref'), 500)}")
        else:
            raise InvalidReview("unsupported evidence anchor")
    return lines


def render_review_markdown(result: Mapping[str, Any], *, title: str | None = None) -> str:
    """Render validated review data; avoid semantic or verification claims.

    This deliberately checks result shape even when called outside the core.
    It cannot determine whether a provider's *interpretation* is correct.
    """
    if not isinstance(result, Mapping) or result.get("schema_version") != SCHEMA:
        raise InvalidReview("not an Aeonith v1 result")
    status = result.get("status")
    if not isinstance(status, str) or status not in EXIT_CODES:
        raise InvalidReview("unrecognized Aeonith result status")
    if title is not None and (not isinstance(title, str) or len(title) > 500):
        raise InvalidReview("title must be at most 500 characters")

    heading = _escape(title.strip()) if title and title.strip() else "Aeonith literary critique"
    if status != "completed":
        error = result.get("error")
        if not isinstance(error, Mapping) or not isinstance(error.get("code"), str):
            raise InvalidReview("unavailable result lacks an error code")
        code = _line(error["code"], 100)
        return (
            f"# {heading}\n\n"
            f"**No literary critique was generated.**\n\n"
            f"Status: `{status}`; reason: {code}.\n\n"
            "A model provider must return a valid completed result before a review can be shown.\n"
        )

    reviews = _items(result.get("lens_reviews"), len(LENS_LABELS))
    if not reviews:
        raise InvalidReview("completed review contains no critical lenses")
    seen: set[str] = set()
    lines = [f"# {heading}", "", "*Provider-supplied criticism; interpretations and external claims are not independently verified.*", ""]
    for review in reviews:
        if not isinstance(review, Mapping):
            raise InvalidReview("lens review is not an object")
        lens = review.get("lens")
        if not isinstance(lens, str) or lens not in LENS_LABELS or lens in seen:
            raise InvalidReview("unknown or duplicate critical lens")
        seen.add(lens)
        basis = review.get("basis")
        if basis not in ("textual", "insufficient_text"):
            raise InvalidReview("invalid lens basis")
        analysis = _line(review.get("analysis"), 6_000)
        supports = _support_lines(review.get("support", []))
        limitations = [_line(item, 1_000) for item in _items(review.get("limitations", []), 15)]
        if basis == "textual" and not supports:
            raise InvalidReview("textual reading has no evidence anchor")
        if basis == "insufficient_text" and not limitations:
            raise InvalidReview("insufficient reading has no explanation")

        lines.extend([f"## {LENS_LABELS[lens]}", "", analysis, ""])
        if basis == "insufficient_text":
            lines.extend(["*Insufficient textual basis for a firm reading.*", ""])
        if supports:
            lines.extend(["Evidence anchors (not independent verification):", "", *supports, ""])
        if limitations:
            lines.extend(["Limitations:", "", *(f"- {item}" for item in limitations), ""])

    synthesis = _line(result.get("synthesis"), 12_000)
    lines.extend(["## Overall synthesis", "", synthesis, ""])

    challenges = _items(result.get("challenges", []), 30)
    if challenges:
        lines.extend(["## Questions and counterreadings", ""])
        for item in challenges:
            if not isinstance(item, Mapping):
                raise InvalidReview("invalid challenge")
            lines.append(f"- {_line(item.get('text'), 2_000)}")
            for support_line in _support_lines(item.get("support", [])):
                lines.append(f"  {support_line}")
        lines.append("")

    uncertainties = _items(result.get("uncertainties", []), 30)
    if uncertainties:
        lines.extend(["## Uncertainties", "", *(f"- {_line(item, 1_000)}" for item in uncertainties), ""])

    audit = _items(result.get("evidence_audit", []), 100)
    if audit:
        lines.extend(["## Supplied evidence status", "", "*These labels describe input provenance, not independently established facts.*", ""])
        for item in audit:
            if not isinstance(item, Mapping) or item.get("status") not in ("provided_unverified", "unsupported"):
                raise InvalidReview("invalid input evidence audit")
            lines.append(f"- {_line(item.get('claim_id'), 100)}: `{item['status']}`")
        lines.append("")

    assessment = result.get("assessment")
    if assessment is not None:
        if assessment not in ("SURVIVES", "FAILS", "UNKNOWN"):
            raise InvalidReview("invalid provisional proposition assessment")
        lines.extend(["## Provisional proposition assessment", "", f"**{assessment}** (model review; not formal verification).", ""])

    return "\n".join(lines).rstrip() + "\n"


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidReview("duplicate JSON key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise InvalidReview("non-finite JSON number")
    return number


def _reject_constant(_: str) -> None:
    raise InvalidReview("non-finite JSON number")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeonith-render")
    parser.add_argument("--input", required=True, help="Aeonith result JSON file, or - for stdin")
    parser.add_argument("--title", help="optional displayed work title")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            path = Path(args.input)
            if path.stat().st_size > MAX_INPUT_BYTES:
                raise InvalidReview("result exceeds size limit")
            with path.open("rb") as handle:
                raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise InvalidReview("result exceeds size limit")
        result = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_unique,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        markdown = render_review_markdown(result, title=args.title)
        sys.stdout.write(markdown)
        return EXIT_CODES[result["status"]]
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        print("Could not render Aeonith result: invalid JSON or result structure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
