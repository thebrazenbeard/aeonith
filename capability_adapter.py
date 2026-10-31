"""Standalone JSON capability adapter for an Aeonith critique implementation.

This module is intentionally independent of transport and model providers.
It wraps ``aeonith.core.critique`` when that package is installed; importing it
does not import or invoke any network client. The invocation envelope is a
correlation record, not an authorization token or an identity attestation.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable, Mapping
from typing import Any


CAPABILITY = "aeonith.review.v1"
INVOKE_KIND = "capability.invoke.v1"
RESULT_KIND = "capability.result.v1"
MAX_INPUT_BYTES = 262_144
MAX_OUTPUT_BYTES = 2_097_152
V1_DEFAULT_LENSES = (
    "psychological", "literary_thematic", "narrative_structure",
    "character_development", "historical_cultural", "philosophical",
    "genre_specific", "stylistic", "sociological", "moral_ethical",
    "symbolic", "reader_response", "linguistic", "comparative",
)
_CORE_STATUSES = {
    "completed", "provider_unavailable", "invalid_request",
    "provider_error", "invalid_provider_output",
}
_SAFE_FAILURES = {
    "provider_unavailable": ("unavailable", "Semantic review was not performed"),
    "invalid_request": ("rejected", "The review request was invalid"),
    "provider_error": ("failed", "The configured review provider failed"),
    "invalid_provider_output": ("failed", "The provider returned an invalid review"),
}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED_ENVELOPE = {"kind", "request_id", "capability", "payload"}
_CORE_RESULT_KEYS = {
    "schema_version", "status", "assessment", "lens_reviews", "synthesis",
    "challenges", "uncertainties", "evidence_audit", "provenance", "error",
}


class DuplicateKeyError(ValueError):
    """A JSON object used the same key more than once."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _within_depth(value: Any, limit: int = 128) -> bool:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > limit:
            return False
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return True


def _response(
    request_id: str | None,
    outcome: str,
    *,
    core_status: str | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": RESULT_KIND,
        "request_id": request_id,
        "capability": CAPABILITY,
        "outcome": outcome,
        "core_status": core_status,
        "result": result,
        "error": error,
    }


def _error(request_id: str | None, code: str, message: str) -> dict[str, Any]:
    return _response(request_id, "rejected", error={"code": code, "message": message})


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_support(value: Any, work_text: str, references: set[str]) -> bool:
    if not isinstance(value, list) or len(value) > 30:
        return False
    for support in value:
        if not isinstance(support, dict):
            return False
        if support.get("source") == "work":
            if set(support) != {"source", "quote"}:
                return False
            quote = support.get("quote")
            if not _nonempty(quote) or quote not in work_text:
                return False
        elif support.get("source") == "provided_evidence":
            if set(support) != {"source", "ref"}:
                return False
            if not isinstance(support.get("ref"), str) or support["ref"] not in references:
                return False
        else:
            return False
    return True


def _within_output_budget(value: Any) -> bool:
    """Ensure provider output is JSON without NaN/Infinity/cycles or huge payloads."""
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        return len(encoded.encode("utf-8")) <= MAX_OUTPUT_BYTES
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        return False


def _valid_completed_review(result: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Reject a fake success that omits the core's structural v1 guarantees.

    This validates the adapter boundary, not literary truth, provider identity,
    or accuracy of claimed external evidence.
    """
    if set(result) != _CORE_RESULT_KEYS or result["error"] is not None:
        return False
    assessment = result["assessment"]
    if assessment is not None and (not isinstance(assessment, str) or assessment not in {"SURVIVES", "FAILS", "UNKNOWN"}):
        return False
    if "work" in payload and assessment is not None:
        return False
    if not _nonempty(result["synthesis"]):
        return False
    provenance = result["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != {
        "review_source", "provider_name", "input_evidence_verified",
        "knowledge_files_attached_by_core", "provider_external_knowledge", "selected_lenses",
    }:
        return False
    if (
        provenance["review_source"] != "injected_provider"
        or not _nonempty(provenance["provider_name"])
        or provenance["input_evidence_verified"] is not False
        or provenance["knowledge_files_attached_by_core"] is not False
        or provenance["provider_external_knowledge"] != "UNKNOWN"
    ):
        return False
    if not isinstance(result["evidence_audit"], list):
        return False
    if not isinstance(result["uncertainties"], list) or any(not _nonempty(x) for x in result["uncertainties"]):
        return False

    requested = payload.get("lenses", list(V1_DEFAULT_LENSES))
    if not isinstance(requested, list) or not requested or len(requested) > len(V1_DEFAULT_LENSES):
        return False
    if any(not isinstance(lens, str) or lens not in V1_DEFAULT_LENSES for lens in requested):
        return False
    if len(set(requested)) != len(requested):
        return False
    if provenance["selected_lenses"] != requested:
        return False
    reviews = result["lens_reviews"]
    if not isinstance(reviews, list) or len(reviews) != len(requested):
        return False
    returned_lenses = [item.get("lens") for item in reviews if isinstance(item, dict)]
    if len(returned_lenses) != len(requested) or any(not isinstance(lens, str) for lens in returned_lenses):
        return False
    if set(returned_lenses) != set(requested):
        return False

    work = payload.get("work", payload.get("proposition"))
    work_text = work.get("text") if isinstance(work, dict) else work
    if not _nonempty(work_text):
        return False
    claims = payload.get("claims", [])
    if not isinstance(claims, list):
        return False
    references: set[str] = set()
    expected_audit: list[dict[str, Any]] = []
    for claim in claims:
        if (
            not isinstance(claim, dict)
            or not _nonempty(claim.get("id"))
            or not isinstance(claim.get("evidence", []), list)
        ):
            return False
        claim_refs: list[str] = []
        for evidence in claim.get("evidence", []):
            if not isinstance(evidence, dict) or not isinstance(evidence.get("ref"), str):
                return False
            references.add(evidence["ref"])
            claim_refs.append(evidence["ref"])
        expected_audit.append({
            "claim_id": claim["id"],
            "status": "provided_unverified" if claim_refs else "unsupported",
            "source_refs": claim_refs,
            "note": "Input provenance only; independent verification was not performed",
        })
    if result["evidence_audit"] != expected_audit:
        return False

    for review in reviews:
        if set(review) != {"lens", "analysis", "basis", "support", "limitations"}:
            return False
        basis = review.get("basis")
        if not _nonempty(review.get("analysis")) or not isinstance(basis, str) or basis not in {"textual", "insufficient_text"}:
            return False
        support = review.get("support")
        if not _valid_support(support, work_text, references):
            return False
        if review["basis"] == "textual" and not support:
            return False
        limitations = review.get("limitations")
        if not isinstance(limitations, list) or any(not _nonempty(x) for x in limitations):
            return False
        if review["basis"] == "insufficient_text" and not limitations:
            return False

    challenges = result["challenges"]
    if not isinstance(challenges, list):
        return False
    for challenge in challenges:
        if not isinstance(challenge, dict) or not _nonempty(challenge.get("text")):
            return False
        if set(challenge) != {"text", "support"}:
            return False
        if not _valid_support(challenge.get("support"), work_text, references):
            return False
    return True


def invoke(
    envelope: Mapping[str, Any] | Any,
    review: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate a capability invocation and delegate to a supplied reviewer.

    The caller/host owns consent, provider identity, endpoint trust, privacy,
    resource budgets, and all effects. The response makes no claim of those
    properties. Unexpected reviewer errors are reported without exception
    details, which could leak private source text or provider credentials.
    """
    if not isinstance(envelope, Mapping):
        return _error(None, "invalid_envelope", "Invocation must be a JSON object")

    raw_id = envelope.get("request_id")
    request_id = raw_id if isinstance(raw_id, str) and _REQUEST_ID.fullmatch(raw_id) else None
    if request_id is None:
        return _error(None, "invalid_request_id", "A bounded request_id is required")
    if set(envelope) != _ALLOWED_ENVELOPE:
        return _error(request_id, "invalid_envelope", "Envelope fields are invalid")
    if envelope["kind"] != INVOKE_KIND:
        return _error(request_id, "invalid_kind", "Unsupported invocation kind")
    if envelope["capability"] != CAPABILITY:
        return _error(request_id, "unsupported_capability", "Unsupported capability")
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        return _error(request_id, "invalid_payload", "Payload must be a JSON object")

    if review is None:
        return _response(
            request_id, "unavailable",
            error={"code": "reviewer_unavailable", "message": "No reviewer is configured"},
        )

    try:
        result = review(payload)
    except Exception:
        return _response(
            request_id, "failed",
            error={"code": "reviewer_error", "message": "The reviewer failed"},
        )

    status = result.get("status") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != CAPABILITY
        or not isinstance(status, str)
        or status not in _CORE_STATUSES
        or not _within_output_budget(result)
        or (status == "completed" and not _valid_completed_review(result, payload))
    ):
        return _response(
            request_id, "failed",
            error={"code": "invalid_reviewer_output", "message": "Reviewer result did not match the declared schema"},
        )

    if status != "completed":
        outcome, message = _SAFE_FAILURES[status]
        # Failure records may contain arbitrary provider-supplied fields.
        # Preserve the bounded core status, never forward their raw payload.
        return _response(
            request_id, outcome, core_status=status,
            error={"code": status, "message": message},
        )

    return _response(request_id, "ok", core_status="completed", result=result)


def decode_and_invoke(
    raw: bytes,
    review: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if len(raw) > MAX_INPUT_BYTES:
        return _error(None, "input_too_large", "Request exceeds the byte limit")
    try:
        envelope = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return _error(None, "invalid_json", "Request must be unique-key UTF-8 JSON")
    if not _within_depth(envelope):
        return _error(None, "invalid_json", "JSON nesting exceeds the limit")
    return invoke(envelope, review=review)


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    try:
        from aeonith.core import critique  # source package is separately installed
    except ImportError:
        critique = None
    output = decode_and_invoke(raw, review=critique)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if output["outcome"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
