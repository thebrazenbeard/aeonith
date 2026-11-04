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
# Still an intentionally tiny excerpt window, not a whole-work verifier.
SHORT_EXCERPT_CHARACTERS = 400
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
    r"|(?:in|from)\s+(?:the\s+)?(?:chapter|scene|section|act)\s+\d+"
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
_QUOTED_METALINGUISTIC_LABEL = re.compile(
    r"['\"“‘](?:recurring|recurrent|repeated)\s+(?:motif|theme|symbol|image|pattern)['\"”’]",
    re.IGNORECASE,
)
_SOURCE_EXTERNAL_CONTEXT = re.compile(
    r"\b(?:earlier|previous|later|subsequent)\s+(?:chapter|scene|section|act)s?\b|"
    r"\bchapter\s+\d+\b", re.IGNORECASE,
)
_SOURCE_QUOTED_PASSAGES = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\'[^\'\n]*\'(?!\w)'
)
_NUMBERED_CONTEXT = re.compile(r"\b(chapter|scene|section|act)\s+(\d+)\b", re.IGNORECASE)
_DIRECTIONAL_CONTEXT = re.compile(
    r"\b(earlier|previous|later|subsequent)\s+(chapter|scene|section|act)s?\b",
    re.IGNORECASE,
)
_NON_ASSERTION = re.compile(
    r"\b(?:no|not|never|without|unsupported|unproven|cannot|can't|couldn't|"
    r"insufficient|absence|unclear|unjustified|speculative|plausible|premature|"
    r"hypothetical|hypothesis|may|might|could|possibly|possible|"
    r"would\s+need|fails?\s+to\s+show|not\s+enough|only\s+if|rather\s+than)\b",
    re.IGNORECASE,
)
_CONTRAST_AFTER_CLAIM = re.compile(r"\b(?:though|although|however|nevertheless|but)\b", re.IGNORECASE)
_EXPLICIT_SINGLE_INSTANCE = re.compile(
    r"\b(?:once|one\s+time|a\s+single\s+(?:time|instance|occasion))\b", re.IGNORECASE,
)
_PREDICATE_SUBJECT = re.compile(
    r"\b(?:the|this|an?)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+"
    r"(?:is|are|becomes?|forms?|serves?\s+as)\s+(?:an?\s+|the\s+)?$",
    re.IGNORECASE,
)
_OF_SUBJECT = re.compile(
    r"\s+of\s+(?:an?\s+|the\s+)?([A-Za-z]+(?:\s+[A-Za-z]+)?)\b",
    re.IGNORECASE,
)
_POSSIBLE_ANAPHORIC_REPEAT = re.compile(
    r"\b(?:it|its|they|their|the\s+same)\b", re.IGNORECASE,
)
_INITIAL_CONDITIONAL = re.compile(r"^\s*(?:perhaps|if)\s+(?:the|this|an?)\b", re.IGNORECASE)


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
    # Mere occurrence of the phrase in the source does not license an
    # *assertion* about recurrence. Only a quoted reference to that wording
    # earns the source-quotation exemption.
    quoted = (match.start() > 0 and match.end() < len(prose)
              and prose[match.start() - 1] in "\"'“‘"
              and prose[match.end()] in "\"'”’")
    if quoted and match.group().casefold() in excerpt.casefold():
        return True
    # Evaluate the same local clause, not a negation in another paragraph.
    left = max(prose.rfind(".", 0, match.start()),
               prose.rfind("?", 0, match.start()),
               prose.rfind("!", 0, match.start()),
               prose.rfind(";", 0, match.start()),
               prose.rfind("\n", 0, match.start())) + 1
    # A hedge about the first half of a sentence is not a hedge about a
    # distinct claim introduced after a contrast: "it may rain, but X is Y".
    before = prose[left:match.start()]
    contrast_before = list(_CONTRAST_AFTER_CLAIM.finditer(before))
    if contrast_before:
        left += contrast_before[-1].end()
    # 'If the bell is ...' and 'Perhaps the bell is ...' are hypotheses,
    # unlike 'If it rains, the bell is ...' (an independent second clause).
    claim_prefix = prose[left:match.start()]
    if "," not in claim_prefix and _INITIAL_CONDITIONAL.search(claim_prefix):
        return True
    right_candidates = [prose.find(mark, match.end()) for mark in ".?!;\n"]
    right = min((place for place in right_candidates if place >= 0), default=len(prose))
    clause = prose[max(left, match.start() - 90):min(right, match.end() + 90)]
    # A later hedge cannot retroactively make an earlier confident assertion
    # a non-assertion ("dominates the novel, though we cannot be certain").
    contrast = _CONTRAST_AFTER_CLAIM.search(clause)
    if contrast and contrast.start() >= match.end() - max(left, match.start() - 90):
        clause = clause[:contrast.start()]
    return bool(_NON_ASSERTION.search(clause))


def _claim_explicitly_once(excerpt: str, prose: str, match: re.Match[str]) -> bool:
    """Spot one narrow mismatch: a named image appears *once*, another repeats.

    This is deliberately not entity resolution. A warning requires a named
    one- or two-word subject in either "motif of the bell" or "the bell is a
    recurring motif", plus an explicit single-instance marker in the same
    source sentence. In ambiguous cases we decline to flag.
    """
    subject = _OF_SUBJECT.match(prose[match.end():])
    if subject is None:
        subject = _PREDICATE_SUBJECT.search(prose[max(0, match.start() - 100):match.start()])
    if subject is None:
        return False
    phrase = subject[1]
    occurrence = re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE)
    if len(occurrence.findall(excerpt)) != 1:
        return False
    sentences = re.split(r"[.!?\n]+", excerpt)
    # A later "it rang again every night" may refer to the named subject.
    # Without entity resolution, decline to warn rather than assert absence.
    if any(not occurrence.search(sentence) and _SOURCE_RECURRENCE.search(sentence)
           and _POSSIBLE_ANAPHORIC_REPEAT.search(sentence) for sentence in sentences):
        return False
    for sentence in sentences:
        if not occurrence.search(sentence) or not _EXPLICIT_SINGLE_INSTANCE.search(sentence):
            continue
        # An explicit repeat in that very sentence invalidates the shortcut.
        # 'Once ..., then again' is not evidence of only one appearance.
        without_once = _EXPLICIT_SINGLE_INSTANCE.sub("", sentence)
        if not _SOURCE_RECURRENCE.search(without_once):
            return True
    return False


def _source_supports_external_claim(excerpt: str, match: re.Match[str]) -> bool:
    """A mentioned chapter does not license claims about *another* chapter."""
    claim = match.group()
    numbered = _NUMBERED_CONTEXT.search(claim)
    if numbered is not None:
        kind, number = numbered.groups()
        for cited in _NUMBERED_CONTEXT.finditer(excerpt):
            if cited.group(1).casefold() != kind.casefold() or cited.group(2) != number:
                continue
            before = excerpt[max(0, cited.start() - 70):cited.start()]
            before = re.split(r"[.!?;\n]", before)[-1]
            # 'There is no Chapter 27' is an explicit denial, not evidence
            # of the referenced chapter. Another affirmative occurrence can
            # still support the claim without global source-context guessing.
            if not re.search(r"\b(?:no|without)\s+$", before, re.IGNORECASE):
                return True
        return False
    directional = _DIRECTIONAL_CONTEXT.search(claim)
    if directional is not None:
        direction, kind = directional.groups()
        same_direction = re.compile(r"\b" + re.escape(direction) + r"\s+"
                                    + re.escape(kind) + r"s?\b", re.IGNORECASE)
        return bool(same_direction.search(excerpt))
    # A bare 'Chapter 1' cannot license 'as established earlier' or a claim
    # about the entire novel; retain only an exact source-phrase exemption.
    return claim.casefold() in excerpt.casefold()


def audit_semantic_risks(request: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Return hints for manual review, without pretending to establish truth.

    A source recurrence cue normally suppresses warnings. The limited exception
    is an explicit once-only image named by the critique while something else
    repeats. Neither branch establishes a semantic verdict.
    """
    if not isinstance(request, dict) or not isinstance(review, dict):
        raise ValueError("invalid_input")
    excerpt = _text_of_work(request)
    short = len(excerpt) <= SHORT_EXCERPT_CHARACTERS
    # A character merely writing the literal words 'recurring motif' is not
    # evidence that a literary image recurs in the excerpt.
    source_recurrence = bool(_SOURCE_RECURRENCE.search(
        _QUOTED_METALINGUISTIC_LABEL.sub("", excerpt)))
    # Quoted dialogue about a 'later chapter' is not evidence that the
    # unseen chapter's actual contents were supplied to this reviewer.
    unquoted_excerpt = _SOURCE_QUOTED_PASSAGES.sub("", excerpt)
    source_context = bool(_SOURCE_EXTERNAL_CONTEXT.search(unquoted_excerpt))
    prose_items = _candidate_prose(review)
    warnings: list[dict[str, str]] = []
    for path, prose in prose_items:
        if short:
            if any(not _cautious_or_quoted(prose, match, excerpt)
                   and (not source_recurrence or _claim_explicitly_once(excerpt, prose, match))
                   for match in _RECURRENCE_CLAIM.finditer(prose)):
                warnings.append({"code": "possible_unfounded_recurrence", "path": path})
        if short:
            if any(not _source_supports_external_claim(unquoted_excerpt, match)
                   and not _cautious_or_quoted(prose, match, excerpt)
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
            "Repetition cues and limited image matching can miss unrelated overclaims.",
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
