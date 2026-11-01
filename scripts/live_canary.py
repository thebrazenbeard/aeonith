"""Operator-controlled live Aeonith service canary using original fiction.

This script does not contact a service unless both execution and paid-inference
consent are supplied. It never prints the manuscript, review, or auth secrets.
It tests response structure and source anchors, not literary judgment quality.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import uuid
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from typing import Any

from aeonith.core import CANONICAL_LENSES, SCHEMA


# Original synthetic text: do not substitute a private manuscript for a canary.
CANARY_TITLE = "Harbor Bell (synthetic canary)"
CANARY_TEXT = (
    "At noon the harbor bell rang thirteen times. "
    "The fishermen laughed at the mistake, but the tide did not."
)
PILOT_LENSES = ("literary_thematic", "stylistic", "symbolic")
MAX_RESPONSE_BYTES = 4_000_000
MAX_TIMEOUT_SECONDS = 120.0
ENV_VAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
JWT_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class CanaryError(Exception):
    """Expected, safe-to-report canary failure."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CanaryError("redirect_refused")


def parse_lenses(value: str) -> tuple[str, ...]:
    """Accept a short, explicit canary selection without caller-defined lenses."""
    if value == "all":
        return CANONICAL_LENSES
    lenses = tuple(part.strip() for part in value.split(","))
    if (not lenses or any(not item or item not in CANONICAL_LENSES for item in lenses)
            or len(lenses) != len(set(lenses))):
        raise CanaryError("invalid_lenses")
    return lenses


def canary_request(lenses: tuple[str, ...] = CANONICAL_LENSES) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "work": {"title": CANARY_TITLE, "text": CANARY_TEXT},
        "lenses": list(lenses),
    }


def validate_url(url: str) -> None:
    if not isinstance(url, str) or not url:
        raise CanaryError("url_required")
    try:
        parsed = urlsplit(url)
        _ = parsed.port  # Reject malformed ports before connecting.
    except ValueError as exc:
        raise CanaryError("invalid_url") from exc
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CanaryError("invalid_url")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise CanaryError("https_required")


def confirm_remote_host(url: str, expected_host: str | None) -> None:
    """Require a separate operator confirmation before sending remote secrets."""
    validate_url(url)
    host = urlsplit(url).hostname
    if host in {"127.0.0.1", "localhost", "::1"}:
        return
    if not expected_host or expected_host.lower() != host:
        raise CanaryError("remote_host_confirmation_required")


def confirm_trusted_oidc_target(url: str, expected_host: str | None) -> None:
    """Never disclose short-lived Vercel Trusted Source tokens off Vercel."""
    confirm_remote_host(url, expected_host)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname.endswith(".vercel.app")
            or not expected_host or expected_host.lower() != parsed.hostname):
        raise CanaryError("trusted_oidc_requires_vercel_preview")


def _secret_from_env(name: str) -> str:
    if not ENV_VAR.fullmatch(name):
        raise CanaryError("invalid_secret_env_name")
    token = os.environ.get(name)
    if not token or token != token.strip() or "\r" in token or "\n" in token:
        raise CanaryError("secret_env_missing_or_invalid")
    return token


def _trusted_oidc_from_env(name: str) -> str:
    """Read a JWT-shaped GitHub OIDC token; Vercel verifies it, not this client."""
    token = _secret_from_env(name)
    if len(token) > 8192 or JWT_SHAPE.fullmatch(token) is None:
        raise CanaryError("trusted_oidc_token_missing_or_invalid")
    return token


def _strict_json(data: bytes) -> Any:
    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CanaryError("duplicate_json_field")
            result[key] = value
        return result

    def reject_constant(_constant: str) -> None:
        raise CanaryError("non_finite_json")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise CanaryError("non_finite_json")
        return number

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_fields,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise CanaryError("invalid_response_json") from exc


def examine_review(result: Any, expected_lenses: tuple[str, ...] = CANONICAL_LENSES) -> dict[str, int]:
    """Check a completed response against the synthetic request, without LLM judging."""
    if not isinstance(result, dict) or result.get("schema_version") != SCHEMA:
        raise CanaryError("response_schema_mismatch")
    if result.get("status") != "completed" or result.get("error") is not None:
        raise CanaryError("response_not_completed")
    reviews = result.get("lens_reviews")
    if not isinstance(reviews, list) or len(reviews) != len(expected_lenses):
        raise CanaryError("lens_coverage_invalid")
    observed: list[str] = []
    anchors = 0
    for review in reviews:
        if not isinstance(review, dict):
            raise CanaryError("lens_row_invalid")
        lens = review.get("lens")
        if not isinstance(lens, str) or lens not in expected_lenses:
            raise CanaryError("lens_row_invalid")
        observed.append(lens)
        if not isinstance(review.get("analysis"), str) or not review["analysis"].strip():
            raise CanaryError("lens_row_invalid")
        basis = review.get("basis")
        if basis not in {"textual", "insufficient_text"}:
            raise CanaryError("lens_row_invalid")
        support = review.get("support")
        if not isinstance(support, list):
            raise CanaryError("support_invalid")
        for item in support:
            if not isinstance(item, dict) or set(item) != {"source", "quote"}:
                raise CanaryError("support_invalid")
            quote = item.get("quote")
            if item.get("source") != "work" or not isinstance(quote, str) or not quote or quote not in CANARY_TEXT:
                raise CanaryError("support_invalid")
            anchors += 1
        if basis == "textual" and not support:
            raise CanaryError("textual_lens_unanchored")
        if basis == "insufficient_text" and not review.get("limitations"):
            raise CanaryError("insufficient_lens_unexplained")
    if set(observed) != set(expected_lenses) or len(set(observed)) != len(observed):
        raise CanaryError("lens_coverage_invalid")
    if anchors == 0:
        raise CanaryError("no_textual_evidence_anchor")
    if not isinstance(result.get("synthesis"), str) or not result["synthesis"].strip():
        raise CanaryError("synthesis_missing")
    if result.get("assessment") is not None:
        raise CanaryError("unexpected_literary_verdict")
    provenance = result.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("review_source") != "injected_provider":
        raise CanaryError("provider_provenance_missing")
    return {"lens_count": len(reviews), "work_quote_anchors": anchors}


def invoke_canary(url: str, *, token: str, timeout: float, bypass_token: str | None = None,
                  trusted_oidc_token: str | None = None,
                  lenses: tuple[str, ...] = CANONICAL_LENSES,
                  expected_host: str | None = None) -> dict[str, int]:
    confirm_remote_host(url, expected_host)
    if bypass_token is not None and trusted_oidc_token is not None:
        raise CanaryError("protection_auth_methods_mutually_exclusive")
    if trusted_oidc_token is not None:
        confirm_trusted_oidc_target(url, expected_host)
    if trusted_oidc_token is not None and (len(trusted_oidc_token) > 8192
            or JWT_SHAPE.fullmatch(trusted_oidc_token) is None):
        raise CanaryError("trusted_oidc_token_missing_or_invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise CanaryError("timeout_out_of_bounds")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        # The CLI's separate paid-inference flag acknowledges disclosure of
        # this fixed synthetic text to the operator-configured remote model.
        "X-Aeonith-Disclosure": "accepted",
        # A unique key lets a durable quota reject accidental replay without
        # re-sending synthetic text to a potentially billable model.
        "X-Aeonith-Request-Id": str(uuid.uuid4()),
    }
    if bypass_token:
        headers["x-vercel-protection-bypass"] = bypass_token
    if trusted_oidc_token:
        headers["x-vercel-trusted-oidc-idp-token"] = trusted_oidc_token
    request = Request(
        url,
        data=json.dumps(canary_request(lenses), ensure_ascii=False, allow_nan=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        # Do not forward manuscript or credentials through inherited proxies or redirects.
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise CanaryError(f"http_status_{exc.code}") from None
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise CanaryError("transport_error") from None
    if status != 200:
        raise CanaryError(f"http_status_{status}")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CanaryError("response_too_large")
    return examine_review(_strict_json(raw), lenses)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Opt-in canary for a deployed Aeonith critique service. Never outputs manuscript or review text.")
    parser.add_argument("--url", help="Explicit trusted full service critique URL, e.g. https://your-project.example/api/review")
    parser.add_argument("--expected-host", help="Required for remote URLs: exact independently verified deployment hostname, without scheme or path")
    parser.add_argument("--execute", action="store_true", help="Actually make the HTTP request; omitted by default")
    parser.add_argument("--allow-paid-inference", action="store_true", help="Acknowledge a paid-model invocation and disclosure of synthetic canary text")
    parser.add_argument("--auth-env", default="AEONITH_SERVICE_TOKEN", help="Environment variable holding the service bearer secret (not its value)")
    protection = parser.add_mutually_exclusive_group()
    protection.add_argument("--vercel-bypass-env", help="Optional environment variable holding a protected-preview bypass secret")
    protection.add_argument("--trusted-oidc-env", help="Alternative environment variable holding a short-lived GitHub Actions OIDC JWT for Vercel Trusted Sources")
    parser.add_argument("--timeout", type=float, default=90.0, help="HTTP timeout in seconds, >0 and <=120 (default: 90)")
    parser.add_argument("--lenses", default="all", help="all, or comma-separated canonical lenses; initial small pilot: literary_thematic,stylistic,symbolic")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_run", "reason": "explicit_execution_required"}, sort_keys=True))
        # A safe no-op must not be mistaken for a successful release probe.
        return 2
    if not args.allow_paid_inference:
        print(json.dumps({"status": "not_run", "reason": "paid_inference_consent_required"}, sort_keys=True))
        return 2
    try:
        # Validate URL and consent before reading secrets or making a call.
        confirm_remote_host(args.url, args.expected_host)
        lenses = parse_lenses(args.lenses)
        if args.trusted_oidc_env:
            confirm_trusted_oidc_target(args.url, args.expected_host)
        # Validate the selected deployment-protection method before reading
        # the application bearer token. Never print token text on failures.
        bypass = _secret_from_env(args.vercel_bypass_env) if args.vercel_bypass_env else None
        trusted_oidc = _trusted_oidc_from_env(args.trusted_oidc_env) if args.trusted_oidc_env else None
        token = _secret_from_env(args.auth_env)
        start = time.monotonic()
        counts = invoke_canary(args.url, token=token, timeout=args.timeout,
                               bypass_token=bypass, trusted_oidc_token=trusted_oidc,
                               lenses=lenses, expected_host=args.expected_host)
    except CanaryError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    except Exception:
        # Do not expose arbitrary provider/HTTP exceptions, URLs or tokens.
        print(json.dumps({"status": "failed", "reason": "unexpected_canary_error"}, sort_keys=True))
        return 1
    print(json.dumps({"status": "passed", **counts, "elapsed_ms": round((time.monotonic() - start) * 1000)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
