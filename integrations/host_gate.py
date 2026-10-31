"""Conditional host-side gate for Aeonith's read-only critique capability.

This is a *contract adapter*, not an authentication system. In particular,
``HostContext`` and ``Reservation`` are ordinary Python values and do not
attest identity. Only a separately secured host may supply the authority and
reviewer bindings. See HOST_BOUNDARY.md before integrating.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from aeonith.core import critique
from capability_adapter import (
    CAPABILITY, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, RESULT_KIND, decode_and_invoke,
)

READ_ONLY_REVIEW = "read_only_review"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


@dataclass(frozen=True)
class HostContext:
    """Claims populated by an authenticated host session, never client JSON."""

    actor_id: str
    tenant_id: str
    provider_id: str
    external_provider: bool
    disclosure_scope: str


@dataclass(frozen=True)
class AuthorizationRequest:
    request_id: str
    actor_id: str
    tenant_id: str
    provider_id: str
    external_provider: bool
    disclosure_scope: str
    capability: str
    effect: str
    request_sha256: str
    input_bytes: int


@dataclass(frozen=True)
class Reservation:
    """Host-owned *committed* reservation; not a transferable bearer token.

    A successful host transaction must atomically check authenticated actor,
    tenant scope, provider disclosure, consent, expiry, replay/idempotency,
    quota and provider-call budget before returning this decision.
    """

    issuer: str
    reservation_id: str
    request_id: str
    actor_id: str
    tenant_id: str
    provider_id: str
    external_provider: bool
    disclosure_scope: str
    capability: str
    effect: str
    request_sha256: str
    consent_external_disclosure: bool
    consent_receipt_id: str | None
    expires_at_epoch: float
    max_input_bytes: int
    max_output_bytes: int
    reserved_provider_calls: int
    reserved_provider_input_tokens: int
    reserved_provider_output_tokens: int
    reserved_cost_microusd: int
    max_runtime_ms: int


class HostAuthority(Protocol):
    """Implement this port *outside* user-controlled request execution.

    Calls must be atomic and durable across workers/restarts; repeated request
    digests/identifiers cannot spend grants again. Consent must be recorded by
    an authenticated user for the exact external provider and data scope.
    """

    def authorize_and_reserve(self, request: AuthorizationRequest) -> Reservation | None:
        ...


def _denied(request_id: str | None, code: str = "host_authority_denied") -> dict[str, Any]:
    return {
        "kind": RESULT_KIND,
        "request_id": request_id,
        "capability": CAPABILITY,
        "outcome": "rejected",
        "core_status": None,
        "result": None,
        "error": {"code": code, "message": "Host authorization was not established"},
    }


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def _valid_context(context: Any) -> bool:
    return (
        isinstance(context, HostContext)
        and all(_valid_id(x) for x in (
            context.actor_id, context.tenant_id, context.provider_id, context.disclosure_scope,
        ))
        and type(context.external_provider) is bool
    )


def _valid_reservation(
    reservation: Any, request: AuthorizationRequest, *, now_epoch: float
) -> bool:
    if not isinstance(reservation, Reservation):
        return False
    if type(reservation.external_provider) is not bool:
        return False
    if not _valid_id(reservation.issuer) or not _valid_id(reservation.reservation_id):
        return False
    for name in ("request_id", "actor_id", "tenant_id", "provider_id", "external_provider", "disclosure_scope", "capability", "effect", "request_sha256"):
        if getattr(reservation, name) != getattr(request, name):
            return False
    if type(reservation.consent_external_disclosure) is not bool:
        return False
    if request.external_provider and not reservation.consent_external_disclosure:
        return False
    if request.external_provider and not _valid_id(reservation.consent_receipt_id):
        return False
    if reservation.consent_receipt_id is not None and not _valid_id(reservation.consent_receipt_id):
        return False
    if (
        type(reservation.expires_at_epoch) not in (int, float)
        or not math.isfinite(reservation.expires_at_epoch)
        or reservation.expires_at_epoch <= now_epoch
    ):
        return False
    for field, upper_bound in (
        (reservation.max_input_bytes, MAX_INPUT_BYTES),
        (reservation.max_output_bytes, MAX_OUTPUT_BYTES),
    ):
        if type(field) is not int or field <= 0 or field > upper_bound:
            return False
    if request.input_bytes > reservation.max_input_bytes:
        return False
    # One read-only model invocation is the entire effect surface of the gate.
    if type(reservation.reserved_provider_calls) is not int or reservation.reserved_provider_calls != 1:
        return False
    # These are minimum structural checks: host provider dispatch must meter
    # tokens, cost and time (the gate has no provider-side cancellation port).
    for field in (
        reservation.reserved_provider_input_tokens,
        reservation.reserved_provider_output_tokens,
        reservation.reserved_cost_microusd,
        reservation.max_runtime_ms,
    ):
        if type(field) is not int or field <= 0:
            return False
    return True


def invoke_with_host_authority(
    raw: bytes,
    *,
    context: HostContext | None = None,
    authority: HostAuthority | None = None,
    reviewer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Validate, reserve host authority, then invoke one read-only review.

    Inject ``clock`` only in tests or from the trusted host. All arguments are
    forgeable by a caller with arbitrary Python execution; that threat requires
    process/transport isolation and attestation, not code in this module.
    """
    if not isinstance(raw, bytes):
        return _denied(None, "invalid_invocation_bytes")

    # Validate both the envelope and the core payload *before* a quota
    # reservation. A missing reviewer alone cannot distinguish a malformed
    # critique payload from a valid request.
    preflight = decode_and_invoke(raw, review=lambda payload: critique(payload, provider=None))
    if preflight["outcome"] == "rejected":
        return preflight
    if (
        preflight["outcome"] != "unavailable"
        or preflight.get("error", {}).get("code") != "provider_unavailable"
    ):
        return _denied(preflight["request_id"])
    request_id = preflight["request_id"]

    if not _valid_context(context) or authority is None or reviewer is None or not callable(reviewer):
        return _denied(request_id, "host_authority_unavailable")
    try:
        now_epoch = clock()
        if type(now_epoch) not in (int, float) or not math.isfinite(now_epoch):
            raise ValueError("invalid clock")
        request = AuthorizationRequest(
            request_id=request_id,
            actor_id=context.actor_id,
            tenant_id=context.tenant_id,
            provider_id=context.provider_id,
            external_provider=context.external_provider,
            disclosure_scope=context.disclosure_scope,
            capability=CAPABILITY,
            effect=READ_ONLY_REVIEW,
            request_sha256=hashlib.sha256(raw).hexdigest(),
            input_bytes=len(raw),
        )
        reservation = authority.authorize_and_reserve(request)
        # An atomic host reservation can be slow. Re-read trusted host time
        # after it returns so an already-expired grant never dispatches.
        now_epoch = clock()
        if type(now_epoch) not in (int, float) or not math.isfinite(now_epoch):
            raise ValueError("invalid post-authorization clock")
        if not _valid_reservation(reservation, request, now_epoch=now_epoch):
            return _denied(request_id)
    except Exception:
        # Never disclose authority implementation, policy or credential details.
        return _denied(request_id)

    response = decode_and_invoke(raw, review=reviewer)
    try:
        encoded = json.dumps(response, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= reservation.max_output_bytes:
            return response
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        pass
    return _denied(request_id, "output_budget_exceeded")
