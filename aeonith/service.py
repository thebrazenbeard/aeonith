"""Restricted HTTP-service boundary for the Aeonith literary critic.

This module is not the authenticated multi-tenant host gate. It operates with
a single server-owned bearer secret and a single server-selected model
destination, and deliberately has no public endpoint-selection capability.
"""

from __future__ import annotations

import hmac
import json
import math
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .core import SCHEMA, critique
from .providers import OpenAICompatibleProvider, OpenAIResponsesProvider

MAX_BODY_BYTES = 1_000_000
_ALLOWED_REQUEST_KEYS = frozenset({
    "schema_version", "work", "proposition", "context", "lenses", "claims",
})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _error(code: str, message: str, *, status: str = "invalid_request") -> dict[str, Any]:
    # Never include a header, submitted title/body or exception in errors.
    return {
        "schema_version": SCHEMA,
        "status": status,
        "error": {"code": code, "message": message},
    }


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _header_values(headers: Any, name: str) -> list[str]:
    """Read one logical header and detect duplicates when the type allows it."""
    if hasattr(headers, "get_all"):
        values = headers.get_all(name, [])
        return list(values) if values else []
    if isinstance(headers, Mapping):
        return [str(value) for key, value in headers.items() if str(key).lower() == name.lower()]
    return []


def _single_header(headers: Any, name: str) -> str | None:
    values = _header_values(headers, name)
    return values[0] if len(values) == 1 else None


def authorize(
    headers: Any, environ: Mapping[str, str] | None = None,
) -> tuple[int | None, dict[str, Any] | None]:
    """Authorize the private service before touching a request body."""
    env = _env(environ)
    secret = env.get("AEONITH_SERVICE_TOKEN", "")
    if (not isinstance(secret, str) or len(secret) < 32
            or not secret.strip() or not secret.isascii()):
        return 503, _error("service_unconfigured", "Review service is not configured",
                           status="provider_unavailable")
    authorization = _single_header(headers, "Authorization")
    prefix = "Bearer "
    if (authorization is None or not authorization.startswith(prefix)
            or len(authorization) > 4096):
        return 401, _error("unauthorized", "Valid bearer authorization required")
    token = authorization[len(prefix):]
    if not token or not token.isascii() or not hmac.compare_digest(token, secret):
        return 401, _error("unauthorized", "Valid bearer authorization required")
    return None, None


def _strict_json(raw: bytes) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def bad_constant(_value: str) -> None:
        raise ValueError("nonfinite JSON value")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON value")
        return number

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=bad_constant, parse_float=finite_float)


def _remote_provider(env: Mapping[str, str]) -> bool:
    try:
        return urlsplit(env.get("AEONITH_PROVIDER_URL", "")).hostname not in _LOCAL_HOSTS
    except ValueError:
        # Invalid endpoint is rejected by the provider constructor, but never
        # silently bypass the disclosure gate.
        return True


def _construct_provider(env: Mapping[str, str]) -> Any:
    kind = env.get("AEONITH_PROVIDER_KIND", "openai-responses")
    url = env.get("AEONITH_PROVIDER_URL", "")
    model = env.get("AEONITH_PROVIDER_MODEL", "")
    api_key = env.get("AEONITH_PROVIDER_API_KEY") or None
    # Model destination and all paid inference settings are server-owned.
    common = {
        "url": url, "model": model, "api_key": api_key,
        "timeout": 45, "max_tokens": 8_192,
        "structured_outputs": env.get("AEONITH_STRUCTURED_OUTPUTS") == "true",
    }
    if kind == "openai-responses":
        return OpenAIResponsesProvider(**common)
    if kind == "openai-compatible":
        return OpenAICompatibleProvider(
            **common, token_field="max_tokens", temperature=0.2, json_mode=True,
        )
    raise ValueError("unsupported configured provider")


def is_ready(environ: Mapping[str, str] | None = None) -> bool:
    """Conservative configuration readiness; not evidence of model success."""
    env = _env(environ)
    secret = env.get("AEONITH_SERVICE_TOKEN", "")
    if (env.get("AEONITH_ENABLE_LIVE_REVIEWS") != "true"
            or not isinstance(secret, str) or len(secret) < 32
            or not secret.strip() or not secret.isascii()
            or not env.get("AEONITH_PROVIDER_URL")
            or not env.get("AEONITH_PROVIDER_MODEL")):
        return False
    if _remote_provider(env) and not env.get("AEONITH_PROVIDER_API_KEY"):
        return False
    try:
        _construct_provider(env)
    except (TypeError, ValueError):
        return False
    return True


def process_review(
    body: bytes,
    headers: Any,
    environ: Mapping[str, str] | None = None,
    provider: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Process a JSON request after independent, server-held authorization.

    The injectable provider is a Python-only testing seam. It is never
    obtained from the HTTP request, and production handlers never pass one.
    """
    env = _env(environ)
    status, error = authorize(headers, env)
    if status is not None:
        return status, error or _error("unauthorized", "Authorization required")
    content_type = _single_header(headers, "Content-Type") or ""
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        return 415, _error("unsupported_media_type", "Content-Type must be application/json")
    if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
        return 413, _error("payload_too_large", "Request body exceeds service limit")
    if not body:
        return 400, _error("empty_body", "JSON request body is required")
    try:
        request = _strict_json(body)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return 400, _error("invalid_json", "Request must be valid UTF-8 JSON")
    if not isinstance(request, dict):
        return 400, _error("invalid_request", "Request must be a JSON object")
    if set(request) - _ALLOWED_REQUEST_KEYS:
        return 400, _error("invalid_request", "Unknown request fields are not permitted")
    # Never invoke paid inference unless an explicit operator switch is on.
    if env.get("AEONITH_ENABLE_LIVE_REVIEWS") != "true":
        return 503, _error("service_disabled", "Live reviews are disabled",
                           status="provider_unavailable")
    if not is_ready(env):
        return 503, _error("provider_unavailable", "Review provider is not configured",
                           status="provider_unavailable")
    if _remote_provider(env):
        disclosure = _single_header(headers, "X-Aeonith-Disclosure")
        if disclosure != "accepted":
            return 403, _error(
                "disclosure_required",
                "Explicit external-provider disclosure acknowledgment required",
            )
    if provider is None:
        try:
            provider = _construct_provider(env)
        except (TypeError, ValueError):
            return 503, _error("provider_unavailable", "Review provider is not configured",
                               status="provider_unavailable")
    try:
        result = critique(request, provider)
    except Exception:
        # An unexpected failure at this public boundary must never disclose
        # the manuscript, host environment, upstream response or traceback.
        return 502, _error("review_failed", "Review service could not complete")
    code = {
        "completed": 200,
        "invalid_request": 400,
        "provider_unavailable": 503,
        "provider_error": 502,
        "invalid_provider_output": 502,
    }[result["status"]]
    if code != 200:
        # The core's CLI-oriented diagnostics may interpolate caller-supplied
        # claim/evidence identifiers. Public errors must not echo manuscripts.
        messages = {
            400: ("invalid_request", "Review request is invalid"),
            503: ("provider_unavailable", "Review provider is unavailable"),
            502: ("review_failed", "Review service could not complete"),
        }
        error_code, message = messages[code]
        return code, _error(error_code, message, status=result["status"])
    return 200, result


def encode_result(result: dict[str, Any]) -> bytes:
    """Serialize only bounded, valid JSON without silently permitting NaN."""
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")

