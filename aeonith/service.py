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

from .admission import admission_ready, admit_request
from .core import SCHEMA, _parse_request, critique
from .providers import OpenAICompatibleProvider, OpenAIResponsesProvider

# A paid HTTP pilot accepts bounded excerpts, not full-book or large evidence
# batches. CLI workflows retain the separate 1 MiB aggregate request limit.
MAX_BODY_BYTES = 64 * 1024
# Conservative paid-pilot limits. The CLI and long-form planner are unaffected.
MAX_PILOT_WORK_CHARS = 12_000
MAX_PILOT_CONTEXT_CHARS = 2_000
_DEFAULT_MAX_OUTPUT_TOKENS = 4_096
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 45.0
_OFFICIAL_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
_VERCEL_GATEWAY_RESPONSES_ENDPOINT = "https://ai-gateway.vercel.sh/v1/responses"
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


def _bounded_int_env(env: Mapping[str, str], name: str, default: int,
                     minimum: int, maximum: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    if (not isinstance(raw, str) or not raw or len(raw) > 6
            or any(character not in "0123456789" for character in raw)):
        raise ValueError(f"invalid {name}")
    result = int(raw)
    if not minimum <= result <= maximum:
        raise ValueError(f"out-of-range {name}")
    return result


def _pilot_settings(env: Mapping[str, str]) -> tuple[int, int, float]:
    """Fail closed on malformed operator limits, even when the model is ready."""
    max_lenses = _bounded_int_env(env, "AEONITH_MAX_LENSES", 14, 1, 14)
    max_output_tokens = _bounded_int_env(
        env, "AEONITH_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS, 256, 8_192,
    )
    raw_timeout = env.get("AEONITH_PROVIDER_TIMEOUT_SECONDS")
    if raw_timeout is None:
        timeout = _DEFAULT_PROVIDER_TIMEOUT_SECONDS
    else:
        if not isinstance(raw_timeout, str) or not raw_timeout or len(raw_timeout) > 16:
            raise ValueError("invalid provider timeout")
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise ValueError("invalid provider timeout") from exc
    if not math.isfinite(timeout) or not 1 <= timeout <= 50:
        raise ValueError("provider timeout must be between 1 and 50 seconds")
    return max_lenses, max_output_tokens, timeout


def _hosted_runtime(env: Mapping[str, str]) -> bool:
    return (env.get("VERCEL") == "1"
            or env.get("VERCEL_ENV") in {"production", "preview", "development"}
            or env.get("AEONITH_ENFORCE_PROVIDER_ALLOWLIST") == "true")


def _gateway_oidc_required(env: Mapping[str, str]) -> bool:
    """Treat an invalid pilot budget-lock flag as a configuration failure."""
    flag = env.get("AEONITH_REQUIRE_VERCEL_GATEWAY_OIDC")
    if flag is None or flag == "false":
        return False
    if flag != "true":
        raise ValueError("invalid Gateway OIDC requirement")
    return True


def _validate_gateway_oidc_lock(env: Mapping[str, str], kind: str, url: str) -> bool:
    """Pin the paid pilot to project-budgeted OIDC independent of Vercel markers."""
    if not _gateway_oidc_required(env):
        return False
    if (kind != "openai-responses"
            or url != _VERCEL_GATEWAY_RESPONSES_ENDPOINT
            or not env.get("VERCEL_OIDC_TOKEN")
            or env.get("AEONITH_PROVIDER_API_KEY")
            or env.get("AI_GATEWAY_API_KEY")):
        raise ValueError("Gateway pilot requires exact endpoint and OIDC only")
    return True


def _validate_hosted_provider_endpoint(env: Mapping[str, str], kind: str, url: str) -> None:
    """A hosted worker may send writing only to an explicitly allowed URL.

    The Vercel-provided environment identity is trusted configuration, never
    request data. Local fake-provider tests remain compatible outside Vercel.
    Self-hosted operators can also opt into this restriction with the literal
    ``AEONITH_ENFORCE_PROVIDER_ALLOWLIST=true``.
    """
    if not _hosted_runtime(env):
        return
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid hosted provider endpoint") from exc
    if (parsed.scheme != "https" or parsed.hostname in _LOCAL_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("hosted provider endpoint must be trusted HTTPS")
    allowed = ({_OFFICIAL_RESPONSES_ENDPOINT, _VERCEL_GATEWAY_RESPONSES_ENDPOINT}
               if kind == "openai-responses" else set())
    configured = env.get("AEONITH_ALLOWED_PROVIDER_URLS", "")
    if configured:
        entries = [entry.strip() for entry in configured.split(",")]
        if len(entries) > 8 or any(not entry or len(entry) > 2_048 for entry in entries):
            raise ValueError("invalid provider endpoint allowlist")
        allowed.update(entries)
    if url not in allowed:
        raise ValueError("provider endpoint is not explicitly allowlisted")


def _pilot_request_exceeds_limits(request: dict[str, Any], max_lenses: int) -> bool:
    work = request.get("work", request.get("proposition"))
    text = work.get("text") if isinstance(work, dict) else work
    context = request.get("context")
    lenses = request.get("lenses")
    return bool(
        (isinstance(text, str) and len(text) > MAX_PILOT_WORK_CHARS)
        or (isinstance(context, str) and len(context) > MAX_PILOT_CONTEXT_CHARS)
        or (isinstance(lenses, list) and len(lenses) > max_lenses)
        or (lenses is None and max_lenses < 14)
    )


def _construct_provider(env: Mapping[str, str]) -> Any:
    kind = env.get("AEONITH_PROVIDER_KIND", "openai-responses")
    url = env.get("AEONITH_PROVIDER_URL", "")
    model = env.get("AEONITH_PROVIDER_MODEL", "")
    oidc_locked = _validate_gateway_oidc_lock(env, kind, url)
    # Vercel project budgets apply to deployment OIDC calls, not calls using
    # an API key. Require OIDC for the hosted gateway rather than silently
    # switching to a key that would bypass the configured project budget.
    if oidc_locked or (url == _VERCEL_GATEWAY_RESPONSES_ENDPOINT and _hosted_runtime(env)):
        api_key = env.get("VERCEL_OIDC_TOKEN") or None
    else:
        # Ambient Vercel OIDC may never be sent to a different host.
        api_key = (env.get("AEONITH_PROVIDER_API_KEY")
                   or (env.get("VERCEL_OIDC_TOKEN")
                       if url == _VERCEL_GATEWAY_RESPONSES_ENDPOINT else None))
    _max_lenses, max_tokens, timeout = _pilot_settings(env)
    _validate_hosted_provider_endpoint(env, kind, url)
    # Model destination and all paid inference settings are server-owned.
    common = {
        "url": url, "model": model, "api_key": api_key,
        "timeout": timeout, "max_tokens": max_tokens,
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
    try:
        oidc_locked = _gateway_oidc_required(env)
    except ValueError:
        return False
    secret = env.get("AEONITH_SERVICE_TOKEN", "")
    if (env.get("AEONITH_ENABLE_LIVE_REVIEWS") != "true"
            or not isinstance(secret, str) or len(secret) < 32
            or not secret.strip() or not secret.isascii()
            or not env.get("AEONITH_PROVIDER_URL")
            or not env.get("AEONITH_PROVIDER_MODEL")):
        return False
    url = env.get("AEONITH_PROVIDER_URL")
    if _remote_provider(env):
        if oidc_locked or (url == _VERCEL_GATEWAY_RESPONSES_ENDPOINT and _hosted_runtime(env)):
            if not env.get("VERCEL_OIDC_TOKEN"):
                return False
        elif not (env.get("AEONITH_PROVIDER_API_KEY")
                  or (url == _VERCEL_GATEWAY_RESPONSES_ENDPOINT
                      and env.get("VERCEL_OIDC_TOKEN"))):
            return False
    # The public hosted health flag must never advertise review readiness
    # without a configured cross-instance admission gate. Configuration alone
    # is not a Redis availability test; the actual EVAL remains fail-closed.
    if (_hosted_runtime(env) or oidc_locked) and not admission_ready(env):
        return False
    try:
        _pilot_settings(env)
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
    try:
        max_lenses, _max_output_tokens, _timeout = _pilot_settings(env)
    except ValueError:
        return 503, _error("service_unconfigured", "Review service limits are not configured",
                           status="provider_unavailable")
    if _pilot_request_exceeds_limits(request, max_lenses):
        return 413, _error("pilot_limit_exceeded", "Review exceeds the configured pilot limits")
    # Check the core schema, evidence-reference integrity and lens set before
    # consuming a distributed allowance. Otherwise a malformed-but-framed
    # authorized request could exhaust the daily budget without model usage.
    try:
        parsed_request, _reason = _parse_request(request)
    except (TypeError, ValueError, RecursionError):
        parsed_request = None
    if parsed_request is None:
        return 400, _error("invalid_request", "Review request is invalid")
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
    # Reserve one distributed daily invocation before constructing or calling
    # any real provider. The injected fake-provider seam is only used by local
    # non-hosted tests; hosted workers enforce admission even when injected.
    if provider is None or _hosted_runtime(env) or _gateway_oidc_required(env):
        admission_status, admission_error = admit_request(headers, env)
        if admission_status is not None:
            return admission_status, admission_error or _error(
                "admission_unavailable", "Review admission is unavailable",
                status="provider_unavailable",
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

