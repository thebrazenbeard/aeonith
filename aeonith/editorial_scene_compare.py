"""Pure, offline preparation and evidence validation for alternative prose scenes.

This is intentionally separate from ``evaluation.quality_eval.build_blind_pair``:
that function compares *critic outputs about one work*, whereas this module
compares two different candidate passages. It makes no literary merit claim,
does not call a model, access a network, or read/write a filesystem.

Blinding hides caller-declared revision labels, not textual clues or identities
that a reader can infer. A caller must keep the assignment key separate from
the display, and separately establish manuscript custody and reviewer consent.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from typing import Any


REQUEST_SCHEMA = "aeonith.scene_compare.v1"
DISPLAY_SCHEMA = "aeonith.scene_blind_pair.v1"
KEY_SCHEMA = "aeonith.scene_blind_key.v1"
FINDING_SCHEMA = "aeonith.scene_finding.v1"
VALIDATED_SCHEMA = "aeonith.scene_finding_validation.v1"
SUMMARY_SCHEMA = "aeonith.scene_comparison_summary.v1"

MAX_SCENE_CHARS = 12_000
MAX_QUESTIONS = 8
MAX_QUESTION_CHARS = 240
MAX_QUOTE_CHARS = 500
MAX_ANALYSIS_CHARS = 2_000
MAX_FINDINGS = 64

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PAIR_ID = re.compile(r"[0-9a-f]{24}\Z")
_SCOPE_KEYS = frozenset({"work_id", "canto_id", "scene_id"})
_SOURCE_KEYS = _SCOPE_KEYS | {"revision_id", "provenance"}
_CANDIDATE_KEYS = frozenset({"text", "sha256", "source"})
_DISPLAY_KEYS = frozenset({
    "schema_version", "pair_id", "scope_sha256", "questions", "A", "B",
    "directions",
})
_FINDING_KEYS = frozenset({
    "schema_version", "pair_id", "arm", "source_sha256", "quote", "start",
    "end", "analysis", "origin_claim",
})
_KEY_KEYS = frozenset({
    "schema_version", "pair_id", "scope", "source_provenance",
    "seed_sha256", "assignment", "display_sha256", "questions_provenance",
    "limitations",
})


class SceneComparisonError(ValueError):
    """Input cannot safely establish a bounded, source-bound comparison."""


def _digest(value: Any) -> str:
    """Canonical SHA-256 for in-memory JSON metadata (not a signature)."""
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SceneComparisonError("metadata must be canonical UTF-8 JSON") from exc
    return hashlib.sha256(data).hexdigest()


def _text_hash(text: str) -> str:
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise SceneComparisonError("passage must be valid UTF-8 text") from exc


def _exact(value: Any, keys: frozenset[str], description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise SceneComparisonError(f"invalid {description} fields")
    return value


def _identifier(value: Any) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _scope(value: Any) -> dict[str, str]:
    obj = _exact(value, _SCOPE_KEYS, "scene scope")
    if any(not _identifier(obj[key]) for key in _SCOPE_KEYS):
        raise SceneComparisonError("scope IDs must be bounded identifiers")
    return {key: obj[key] for key in sorted(_SCOPE_KEYS)}


def _candidate(value: Any, scope: dict[str, str]) -> dict[str, Any]:
    obj = _exact(value, _CANDIDATE_KEYS, "candidate")
    source = _exact(obj["source"], _SOURCE_KEYS, "candidate source")
    if (any(not _identifier(source[key]) for key in _SOURCE_KEYS - {"provenance"})
            or source["provenance"] != "USER"):
        raise SceneComparisonError("candidate provenance must be bounded and caller-asserted USER")
    if any(source[key] != scope[key] for key in _SCOPE_KEYS):
        raise SceneComparisonError("candidate scope does not match the comparison scope")
    passage, declared_hash = obj["text"], obj["sha256"]
    if type(passage) is not str or not 0 < len(passage) <= MAX_SCENE_CHARS or not passage.strip():
        raise SceneComparisonError("scene must be nonempty and at most 12000 characters")
    if (type(declared_hash) is not str or not _SHA256.fullmatch(declared_hash)
            or declared_hash != _text_hash(passage)):
        raise SceneComparisonError("candidate text fingerprint mismatch")
    return {"text": passage, "sha256": declared_hash,
            "source": {key: source[key] for key in sorted(_SOURCE_KEYS)}}


def _questions(value: Any) -> list[str]:
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_QUESTIONS
            or any(type(item) is not str or not item.strip()
                   or len(item) > MAX_QUESTION_CHARS for item in value)
            or len(set(value)) != len(value)):
        raise SceneComparisonError("questions must be distinct, bounded, nonempty strings")
    for item in value:
        try:
            item.encode("utf-8")
        except UnicodeError as exc:
            raise SceneComparisonError("questions must be valid UTF-8") from exc
    return list(value)


def prepare_scene_pair(first: Any, second: Any, *, scope: Any,
                       questions: Any, seed: str | None = None
                       ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Construct an in-memory display and separate private assignment key.

    A fresh random seed is used if omitted. Supplying one makes tests and
    revision comparisons reproducible, but an exposed seed can reveal the
    assignment. No caller source/revision labels appear in the display.
    """
    normalized_scope = _scope(scope)
    a = _candidate(first, normalized_scope)
    b = _candidate(second, normalized_scope)
    editorial_questions = _questions(questions)
    if a["source"]["revision_id"] == b["source"]["revision_id"]:
        raise SceneComparisonError("candidate revision IDs must differ")
    if a["sha256"] == b["sha256"]:
        raise SceneComparisonError("identical passages are not a comparison")
    if seed is None:
        seed = secrets.token_hex(16)
    if type(seed) is not str or not 0 < len(seed) <= 128:
        raise SceneComparisonError("seed must be a bounded nonempty string")
    try:
        seed.encode("utf-8")
    except UnicodeError as exc:
        raise SceneComparisonError("seed must be valid UTF-8") from exc

    # Sorting ensures input argument reversal cannot silently alter assignment.
    ordered = sorted((a, b), key=lambda item: item["source"]["revision_id"])
    scope_hash = _digest(normalized_scope)
    pair_id = _digest({
        "scope_sha256": scope_hash, "questions": editorial_questions,
        "candidates": [(row["source"]["revision_id"], row["sha256"])
                       for row in ordered], "seed": seed,
    })[:24]
    flipped = int(_digest({"pair_id": pair_id, "seed": seed})[-1], 16) % 2 == 1
    display_rows = list(reversed(ordered)) if flipped else ordered

    display = {
        "schema_version": DISPLAY_SCHEMA, "pair_id": pair_id,
        "scope_sha256": scope_hash, "questions": editorial_questions,
        "A": {"text": display_rows[0]["text"], "sha256": display_rows[0]["sha256"]},
        "B": {"text": display_rows[1]["text"], "sha256": display_rows[1]["sha256"]},
        "directions": (
            "Read both scenes independently; substantiate criticisms with exact "
            "passage spans. No structural check proves literary quality."
        ),
    }
    key = {
        "schema_version": KEY_SCHEMA, "pair_id": pair_id,
        "scope": normalized_scope, "source_provenance": "USER",
        "seed_sha256": _text_hash(seed),
        "display_sha256": _digest(display),
        "questions_provenance": "USER",
        "assignment": {
            arm: {"revision_id": row["source"]["revision_id"],
                  "source_sha256": row["sha256"]}
            for arm, row in zip(("A", "B"), display_rows)
        },
        "limitations": "Caller source labels and reviewer identity are not independently verified",
    }
    return display, key


def _display(value: Any) -> Mapping[str, Any]:
    obj = _exact(value, _DISPLAY_KEYS, "blind display")
    if obj["schema_version"] != DISPLAY_SCHEMA or not isinstance(obj["pair_id"], str) \
            or not _PAIR_ID.fullmatch(obj["pair_id"]):
        raise SceneComparisonError("invalid blinded pair identity")
    if type(obj["scope_sha256"]) is not str or not _SHA256.fullmatch(obj["scope_sha256"]):
        raise SceneComparisonError("invalid blinded source scope fingerprint")
    _questions(obj["questions"])
    if type(obj["directions"]) is not str or not obj["directions"]:
        raise SceneComparisonError("missing blinded directions")
    for arm in ("A", "B"):
        row = _exact(obj[arm], frozenset({"text", "sha256"}), "display arm")
        if type(row["text"]) is not str or not 0 < len(row["text"]) <= MAX_SCENE_CHARS \
                or not row["text"].strip() or row["sha256"] != _text_hash(row["text"]):
            raise SceneComparisonError("display arm fingerprint mismatch")
    if obj["A"]["sha256"] == obj["B"]["sha256"]:
        raise SceneComparisonError("blind display has identical alternatives")
    return obj


def _bound_display(display: Any, assignment_key: Any) -> Mapping[str, Any]:
    """Require the original operator-held assignment key to seal exact bytes.

    A malicious party that holds and rewrites both display and private key can
    forge a new packet; this is custody-bound integrity, not an authentication
    signature. Do not reveal the key to blind raters or an untrusted model.
    """
    viewed = _display(display)
    key = _exact(assignment_key, _KEY_KEYS, "private assignment key")
    if (key["schema_version"] != KEY_SCHEMA or key["pair_id"] != viewed["pair_id"]
            or key["display_sha256"] != _digest(viewed)
            or _digest(_scope(key["scope"])) != viewed["scope_sha256"]
            or key["source_provenance"] != "USER"
            or key["questions_provenance"] != "USER"
            or type(key["seed_sha256"]) is not str
            or not _SHA256.fullmatch(key["seed_sha256"])):
        raise SceneComparisonError("blind display is not bound to its private key")
    if (not isinstance(key["assignment"], Mapping)
            or set(key["assignment"]) != {"A", "B"}):
        raise SceneComparisonError("invalid private assignment")
    seen_revisions: set[str] = set()
    for arm in ("A", "B"):
        assigned = _exact(key["assignment"][arm],
                          frozenset({"revision_id", "source_sha256"}),
                          "private source assignment")
        revision = assigned["revision_id"]
        if (not _identifier(revision) or revision in seen_revisions
                or assigned["source_sha256"] != viewed[arm]["sha256"]):
            raise SceneComparisonError("private assignment does not match display")
        seen_revisions.add(revision)
    if type(key["limitations"]) is not str:
        raise SceneComparisonError("invalid assignment limitations")
    return viewed


def validate_scene_finding(display: Any, finding: Any, *,
                           assignment_key: Any) -> dict[str, Any]:
    """Validate literal source location; never validate interpretation or author."""
    viewed = _bound_display(display, assignment_key)
    obj = _exact(finding, _FINDING_KEYS, "editorial finding")
    if obj["schema_version"] != FINDING_SCHEMA or obj["pair_id"] != viewed["pair_id"]:
        raise SceneComparisonError("finding belongs to another comparison")
    arm = obj["arm"]
    if arm not in ("A", "B") or type(arm) is not str:
        raise SceneComparisonError("finding arm must be A or B")
    source = viewed[arm]
    if obj["source_sha256"] != source["sha256"]:
        raise SceneComparisonError("finding refers to another source revision")
    quote = obj["quote"]
    if type(quote) is not str or not quote.strip() or len(quote) > MAX_QUOTE_CHARS:
        raise SceneComparisonError("finding quote must be bounded and nonempty")
    start, end = obj["start"], obj["end"]
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(source["text"])
            or source["text"][start:end] != quote):
        raise SceneComparisonError("finding quote does not match its exact Unicode span")
    analysis = obj["analysis"]
    if type(analysis) is not str or not analysis.strip() \
            or len(analysis) > MAX_ANALYSIS_CHARS:
        raise SceneComparisonError("finding analysis must be bounded and nonempty")
    if obj["origin_claim"] not in ("model", "human", "unspecified"):
        raise SceneComparisonError("finding origin must not assert verification")
    try:
        analysis.encode("utf-8")
    except UnicodeError as exc:
        raise SceneComparisonError("finding analysis must be valid UTF-8") from exc
    return {
        "schema_version": VALIDATED_SCHEMA,
        "pair_id": viewed["pair_id"], "arm": arm,
        "source_sha256": source["sha256"],
        "quote": quote, "start": start, "end": end,
        "analysis": analysis, "origin_claim": obj["origin_claim"],
        "evidence_class": "REVIEW", "literal_source_location": "validated",
        "semantic_quality": "UNASSESSED", "human_identity_verified": False,
    }


def summarize_scene_comparison(display: Any, findings: Any, *,
                               assignment_key: Any) -> dict[str, Any]:
    """Emit only aggregate metadata, never source text or critique prose."""
    viewed = _bound_display(display, assignment_key)
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise SceneComparisonError("too many scene findings")
    counts = {"A": 0, "B": 0}
    unique_locations: set[tuple[str, str, int, int]] = set()
    duplicate_locations = 0
    for finding in findings:
        candidate = _exact(finding, frozenset({
            "schema_version", "pair_id", "arm", "source_sha256", "quote",
            "start", "end", "analysis", "origin_claim", "evidence_class",
            "literal_source_location", "semantic_quality", "human_identity_verified",
        }), "validated finding")
        if (candidate["schema_version"] != VALIDATED_SCHEMA
                or candidate["evidence_class"] != "REVIEW"
                or candidate["literal_source_location"] != "validated"
                or candidate["semantic_quality"] != "UNASSESSED"
                or candidate["human_identity_verified"] is not False):
            raise SceneComparisonError("unverified editorial finding cannot be promoted")
        # Revalidate rather than trusting a caller-created `validated` dict.
        original_finding = {key: candidate[key] for key in _FINDING_KEYS}
        original_finding["schema_version"] = FINDING_SCHEMA
        validate_scene_finding(viewed, original_finding,
                               assignment_key=assignment_key)
        location = (candidate["arm"], candidate["source_sha256"],
                    candidate["start"], candidate["end"])
        if location in unique_locations:
            duplicate_locations += 1
        else:
            unique_locations.add(location)
            counts[candidate["arm"]] += 1
    lengths = (len(viewed["A"]["text"]), len(viewed["B"]["text"]))
    length_ratio = max(lengths) / min(lengths)
    return {
        "schema_version": SUMMARY_SCHEMA, "pair_id": viewed["pair_id"],
        "source_scope_sha256": viewed["scope_sha256"],
        "distinct_literal_source_locations": counts,
        "repeated_location_entries": duplicate_locations,
        "comparison_warnings": (["length_imbalance"] if length_ratio > 1.5 else [])
        + ["caller_supplied_questions_may_bias_comparison"],
        "literary_preference": "NOT_COMPUTED", "semantic_quality": "UNASSESSED",
        "source_provenance": "USER", "questions_provenance": "USER",
        "reviewer_independence": "UNVERIFIED",
    }
