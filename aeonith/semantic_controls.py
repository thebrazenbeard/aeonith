"""Privacy-safe, advisory checks for overconfident literary interpretations.

This is *not* an automated literary judge. It checks a small set of explicit
claims against an isolated excerpt and asks for human review when a claim
seems to require repetition or unseen story context. It never blocks a review,
contacts a model, or echoes source/model prose in reports.

Usage::

    python -m aeonith.semantic_controls < request_and_review.json

Input: {"request": <aeonith.review.v1 request>, "review": <completed review>}
Output: sanitized warning codes, JSON paths and counts only; no prose.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


INPUT_SCHEMA = "aeonith.semantic_triage_input.v1"
REPORT_SCHEMA = "aeonith.semantic_triage.v1"
MAX_INPUT_BYTES = 64 * 1024
MAX_EXCERPT_CHARACTERS = 12_000
SHORT_EXCERPT_CHARACTERS = 200
MAX_REVIEW_TEXT = 12_000
MAX_LENSES = 14
MAX_CHALLENGES = 30

_RECURRENCE_CLAIM = re.compile(
    r"\b(?:"
    r"recurr(?:ing|ent|ence)\s+(?:motif|theme|symbol|image|imagery|pattern)s?"
    r"|repeat(?:ed|ing)\s+(?:motif|theme|symbol|image|imagery|pattern)s?"
    r"|(?:the|this|a)\s+pattern\s+repeat(?:s|edly)?"
    r"|again\s+and\s+again"
    r"|throughout\s+(?:the|this)\s+(?:text|work|story|novel|book)"
    r")\b", re.IGNORECASE,
)
_EXTERNAL_CONTEXT_CLAIM = re.compile(
    r"\b(?:"
    r"(?:in|from|as\s+seen\s+in)\s+(?:an?\s+|the\s+)?(?:earlier|previous|later|subsequent)\s+(?:chapter|scene|section|act)s?"
    r"|(?:throughout|across)\s+(?:the|this)\s+(?:novel|book)"
    r"|(?:as|already)\s+(?:established|shown)\s+earlier"
    r")\b", re.IGNORECASE,
)
_SOURCE_RECURRENCE = re.compile(
    r"\b(?:again|repeated(?:ly)?|repeat(?:s|ed)?|recurr(?:ing|ent|ed|s)?|every|each|"
    r"twice|thrice|often|always|usually|daily|weekly|nightly|yearly|"
    r"morning\s+after\s+morning|day\s+after\s+day|once\s+more|many\s+times)\b",
    re.IGNORECASE,
)
_SOURCE_EXTERNAL_CONTEXT = re.compile(
    r"\b(?:earlier|previous|later|subsequent)\s+(?:chapter|scene|section|act)s?\b|"
    r"\bchapter\s+\d+\b", re.IGNORECASE,
)
_NON_ASSERTION = re.compile(
    r"\b(?:no|not|never|without|unsupported|unproven|cannot|can't|couldn't|"
    r"insufficient|absence|unclear|unjustified|speculative|premature|"
    r"hypothetical|hypothesis|may|might|could|possibly|possible|"
    r"would\s+need|fails?\s+to\s+show|not\s+enough|rather\s+than)\b",
    re.IGNORECASE,
)


def _text_of_work(request: dict[str, Any]) -> str:
    if request.get("schema_version") != "aeonith.review.v1":
        raise ValueError("invalid_request")
    if ("work" in request) == ("proposition" in request):
        raise ValueError("invalid_request")
    work = request.get("work", request.get("proposition"))
    if isinstance(work, dict):
        work = work.get("text")
    if not isinstance(work, str) or not work.strip() or len(work) > MAX_EXCERPT_CHARACTERS:
        raise ValueError("invalid_excerpt")
    return work


def _candidate_prose(review: dict[str, Any]) -> list[tuple[str, str]]:
    if review.get("status") != "completed":
        return []
    items: list[tuple[str, str]] = []
    synthesis = review.get("synthesis")
    if isinstance(synthesis, str):
        items.append(("synthesis", synthesis))
    rows = review.get("lens_reviews", [])
    if not isinstance(rows, list) or len(rows) > MAX_LENSES:
        raise ValueError("invalid_review")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("invalid_review")
        analysis = row.get("analysis")
        if isinstance(analysis, str):
            items.append((f"lens_reviews[{index}].analysis", analysis))
    challenges = review.get("challenges", [])
    if not isinstance(challenges, list) or len(challenges) > MAX_CHALLENGES:
        raise ValueError("invalid_review")
    for index, row in enumerate(challenges):
        if not isinstance(row, dict):
            raise ValueError("invalid_review")
        value = row.get("text")
        if isinstance(value, str):
            items.append((f"challenges[{index}].text", value))
    if any(len(value) > MAX_REVIEW_TEXT for _, value in items):
        raise ValueError("invalid_review")
    return items


def _cautious_or_quoted(prose: str, match: re.Match[str], excerpt: str) -> bool:
    """Favor precision over recall: never flag a non-assertion or source quote."""
    if match.group().casefold() in excerpt.casefold():
        return True
    # Evaluate the same local clause, not a negation in another paragraph.
    left = max(prose.rfind(".", 0, match.start()),
               prose.rfind("?", 0, match.start()),
               prose.rfind("!", 0, match.start()),
               prose.rfind("\n", 0, match.start())) + 1
    right_candidates = [prose.find(mark, match.end()) for mark in ".?!\n"]
    right = min((place for place in right_candidates if place >= 0), default=len(prose))
    clause = prose[max(left, match.start() - 90):min(right, match.end() + 90)]
    return bool(_NON_ASSERTION.search(clause))


def audit_semantic_risks(request: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Return hints for manual review, without pretending to establish truth.

    Source repetition cues suppress the recurrence warning, even in short
    passages; lack of cues alone cannot establish that recurrence is false.
    Both cues and lexical claims are heuristic and can miss genuine cases.
    """
    if not isinstance(request, dict) or not isinstance(review, dict):
        raise ValueError("invalid_input")
    excerpt = _text_of_work(request)
    short = len(excerpt) <= SHORT_EXCERPT_CHARACTERS
    source_recurrence = bool(_SOURCE_RECURRENCE.search(excerpt))
    source_context = bool(_SOURCE_EXTERNAL_CONTEXT.search(excerpt))
    prose_items = _candidate_prose(review)
    warnings: list[dict[str, str]] = []
    for path, prose in prose_items:
        if short and not source_recurrence:
            if any(not _cautious_or_quoted(prose, match, excerpt)
                   for match in _RECURRENCE_CLAIM.finditer(prose)):
                warnings.append({"code": "possible_unfounded_recurrence", "path": path})
        if short and not source_context:
            if any(not _cautious_or_quoted(prose, match, excerpt)
                   for match in _EXTERNAL_CONTEXT_CLAIM.finditer(prose)):
                warnings.append({"code": "possible_unseen_story_context", "path": path})
    counts = {
        "examined_prose_fields": len(prose_items),
        "warning_count": len(warnings),
        "short_excerpt": short,
        "source_recurrence_cue": source_recurrence,
        "source_external_context_cue": source_context,
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "semantic_quality": "UNASSESSED",
        "classification": "HEURISTIC_HUMAN_REVIEW_ONLY",
        "counts": counts,
        "warnings": warnings,
        "limitations": [
            "Lexical cues cannot prove or refute literary interpretation.",
            "A repetition cue elsewhere in the excerpt can hide an unrelated overclaim.",
            "Warnings are advisory; no production review is blocked or scored.",
        ],
    }


def _read_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("invalid_input_size")
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate_json_key")
            obj[key] = value
        return obj
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json")))
    if not isinstance(payload, dict) or set(payload) != {"request", "review"}:
        raise ValueError("invalid_input")
    return payload["request"], payload["review"]


def main() -> int:
    try:
        request, review = _read_payload()
        report = audit_semantic_risks(request, review)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, RecursionError):
        print(json.dumps({"schema_version": REPORT_SCHEMA,
                          "status": "invalid_input", "semantic_quality": "UNASSESSED"},
                         separators=(",", ":")))
        return 2
    print(json.dumps(report, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
