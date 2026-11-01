"""Private, local-only HTTP review boundary for the Aeonith literary critic.

No paid API, hosted model, Redis admission service, cloud credential, or
arbitrary provider URL is supported by this service. Inference is explicitly
opted into by the operator and can reach only a loopback model server.
"""

from __future__ import annotations

import hmac
import json
import math
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .core import SCHEMA, _parse_request, critique
from .providers import LocalOpenAICompatibleProvider

# The local HTTP interface accepts bounded excerpts; the separate CLI retains
# its 1 MiB aggregate request limit.
MAX_BODY_BYTES = 64 * 1024
MAX_REVIEW_WORK_CHARS = 12_000
MAX_REVIEW_CONTEXT_CHARS = 2_000
_DEFAULT_MAX_OUTPUT_TOKENS = 4_096
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 45.0
_ALLOWED_REQUEST_KEYS = frozenset({
    "schema_version", "work", "proposition", "context", "lenses", "claims",
})
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})
_CLOUD_CONFIGURATION_KEYS = (
    "AEONITH_PROVIDER_API_KEY", "AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN",
    "AEONITH_REQUIRE_VERCEL_GATEWAY_OIDC", "AEONITH_ADMISSION_REDIS_URL",
    "AEONITH_ADMISSION_REDIS_TOKEN", "AEONITH_ALLOWED_PROVIDER_URLS",
    "VERCEL", "VERCEL_ENV",
)


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


def _local_provider_url(env: Mapping[str, str]) -> bool:
    """Allow only literal loopback IPs and the standard chat endpoint.

    Avoid DNS, redirects and userinfo so even hostile local environment
    settings cannot silently turn manuscript requests into paid network calls.
    """
    try:
        parts = urlsplit(env.get("AEONITH_PROVIDER_URL", ""))
        return (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS
                and parts.port is not None and parts.port > 0
                and parts.path == "/v1/chat/completions"
                and parts.username is None and parts.password is None
                and not parts.query and not parts.fragment)
    except (TypeError, ValueError):
        return False


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


def _review_settings(env: Mapping[str, str]) -> tuple[int, int, float]:
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


def _bool_setting(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    if value not in ("true", "false"):
        raise ValueError(f"invalid {name}")
    return value == "true"


def _request_exceeds_limits(request: dict[str, Any], max_lenses: int) -> bool:
    work = request.get("work", request.get("proposition"))
    text = work.get("text") if isinstance(work, dict) else work
    context = request.get("context")
    lenses = request.get("lenses")
    return bool(
        (isinstance(text, str) and len(text) > MAX_REVIEW_WORK_CHARS)
        or (isinstance(context, str) and len(context) > MAX_REVIEW_CONTEXT_CHARS)
        or (isinstance(lenses, list) and len(lenses) > max_lenses)
        or (lenses is None and max_lenses < 14)
    )


def _construct_provider(env: Mapping[str, str]) -> Any:
    if env.get("AEONITH_PROVIDER_KIND") != "local-openai-compatible":
        raise ValueError("only a local OpenAI-compatible model is supported")
    if any(env.get(key) for key in _CLOUD_CONFIGURATION_KEYS):
        raise ValueError("cloud credentials and hosted configuration are unsupported")
    if not _local_provider_url(env):
        raise ValueError("provider must be a literal loopback chat-completions endpoint")
    _max_lenses, max_tokens, timeout = _review_settings(env)
    return LocalOpenAICompatibleProvider(
        url=env["AEONITH_PROVIDER_URL"],
        model=env.get("AEONITH_PROVIDER_MODEL", ""),
        timeout=timeout,
        max_tokens=max_tokens,
        json_mode=_bool_setting(env, "AEONITH_LOCAL_JSON_MODE", True),
        structured_outputs=_bool_setting(env, "AEONITH_STRUCTURED_OUTPUTS", False),
    )


def is_ready(environ: Mapping[str, str] | None = None) -> bool:
    """Local-only configuration readiness; not evidence of model success."""
    env = _env(environ)
    secret = env.get("AEONITH_SERVICE_TOKEN", "")
    if (env.get("AEONITH_ENABLE_LIVE_REVIEWS") != "true"
            or not isinstance(secret, str) or len(secret) < 32
            or not secret.strip() or not secret.isascii()
            or not env.get("AEONITH_PROVIDER_URL")
            or not env.get("AEONITH_PROVIDER_MODEL")):
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
    try:
        max_lenses, _max_output_tokens, _timeout = _review_settings(env)
    except ValueError:
        return 503, _error("service_unconfigured", "Review service limits are not configured",
                           status="provider_unavailable")
    if _request_exceeds_limits(request, max_lenses):
        return 413, _error("review_limit_exceeded", "Review exceeds the configured service limits")
    # Check the core schema, evidence-reference integrity and lens set before
    # any model invocation.
    try:
        parsed_request, _reason = _parse_request(request)
    except (TypeError, ValueError, RecursionError):
        parsed_request = None
    if parsed_request is None:
        return 400, _error("invalid_request", "Review request is invalid")
    # Never invoke inference unless an explicit operator switch is on.
    if env.get("AEONITH_ENABLE_LIVE_REVIEWS") != "true":
        return 503, _error("service_disabled", "Live reviews are disabled",
                           status="provider_unavailable")
    if not is_ready(env):
        return 503, _error("provider_unavailable", "Review provider is not configured",
                           status="provider_unavailable")
    # Local providers consume no paid account quota. No Redis or other cloud
    # admission round-trip is ever made, including in production requests.
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

