"""Fail-closed distributed admission for *paid* Aeonith HTTP reviews.

The caller must authenticate, validate the full request and enforce external
disclosure *before* invoking :func:`admit_request`. Its successful return is
the last required step before one model invocation. A reservation consumes
one daily allowance even if inference later fails or times out.

All counters and replay tombstones live in a server-owned Upstash Redis REST
database. A single EVAL is used because non-atomic read/increment sequences
can admit concurrent requests over budget across Vercel function instances.

The daily limit is an invocation count, **not** a hard dollar budget. An
independently enforced provider spending limit is still required. This module
does not retry ambiguous network failures: the reservation may already have
been applied remotely, and a retry must use the same request ID and fail
closed as a replay.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .core import SCHEMA


_MAX_RESPONSE_BYTES = 4096
_REQUEST_TIMEOUT_SECONDS = 3
_REPLAY_TTL_SECONDS = 7 * 24 * 60 * 60
_PREFIX = "aeonith:admission:v1"
_UUID4 = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)

# 0 = admitted, 1 = replay, 2 = daily budget exhausted, 3 = broken state.
# Redis EVAL executes the check and all writes atomically on the server.
_ADMIT_SCRIPT = """
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
if not limit or limit < 1 or not ttl or ttl < 1 then return 3 end
if redis.call('EXISTS', KEYS[2]) == 1 then return 1 end
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if not used or used < 0 then return 3 end
if used >= limit then return 2 end
local next_count = redis.call('INCR', KEYS[1])
if next_count == 1 then redis.call('EXPIRE', KEYS[1], ttl) end
redis.call('SET', KEYS[2], '1', 'EX', ttl)
return 0
""".strip()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):
        return None


def _failure(code: str, message: str, *, unavailable: bool = False) -> dict[str, Any]:
    """Never reflect inputs, headers, database URLs or upstream responses."""
    return {
        "schema_version": SCHEMA,
        "status": "provider_unavailable" if unavailable else "invalid_request",
        "error": {"code": code, "message": message},
    }


def _single_header(headers: Any, name: str) -> str | None:
    if hasattr(headers, "get_all"):
        values = headers.get_all(name, [])
        values = list(values) if values else []
    elif isinstance(headers, Mapping):
        values = [str(value) for key, value in headers.items()
                  if str(key).lower() == name.lower()]
    else:
        values = []
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def _configured(env: Mapping[str, str]) -> tuple[str, str, int] | None:
    raw_url = env.get("AEONITH_ADMISSION_REDIS_URL", "")
    token = env.get("AEONITH_ADMISSION_REDIS_TOKEN", "")
    raw_limit = env.get("AEONITH_DAILY_REVIEW_LIMIT", "")
    if not all(isinstance(value, str) for value in (raw_url, token, raw_limit)):
        return None
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or not host.endswith(".upstash.io")
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or port not in (None, 443)):
        return None
    # Bearer credentials must be safe in an HTTP header; never echo them.
    if (len(token) < 16 or len(token) > 4096 or not token.isascii()
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        return None
    if not re.fullmatch(r"[1-9][0-9]{0,3}", raw_limit):
        return None
    daily_limit = int(raw_limit)
    if daily_limit > 1000:
        return None
    return raw_url.rstrip("/"), token, daily_limit


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def admission_ready(env: Mapping[str, str]) -> bool:
    """Configuration check only; a real reservation still must be verified."""
    return _configured(env) is not None


def admit_request(
    headers: Any, env: Mapping[str, str],
) -> tuple[int | None, dict[str, Any] | None]:
    """Reserve one global daily invocation or deny, before paid inference.

    Required server-only environment variables:
    ``AEONITH_ADMISSION_REDIS_URL``, ``AEONITH_ADMISSION_REDIS_TOKEN``,
    ``AEONITH_DAILY_REVIEW_LIMIT`` (1–1000). No configuration means no model
    calls, never an in-memory or unmetered fallback.

    Request header ``X-Aeonith-Request-Id`` must be a unique lowercase UUIDv4.
    A repeated identifier is rejected for seven days with HTTP 409. This is a
    bounded replay window, not a claim of durable exactly-once completion.
    """
    config = _configured(env)
    if config is None:
        return 503, _failure("admission_unavailable", "Review admission is unavailable",
                             unavailable=True)
    request_id = _single_header(headers, "X-Aeonith-Request-Id")
    if request_id is None or _UUID4.fullmatch(request_id) is None:
        return 400, _failure("invalid_request_id", "A unique request identifier is required")

    endpoint, token, daily_limit = config
    request_hash = hashlib.sha256(request_id.encode("ascii")).hexdigest()
    quota_key = f"{_PREFIX}:day:{_day_key()}"
    replay_key = f"{_PREFIX}:request:{request_hash}"
    command = [
        "EVAL", _ADMIT_SCRIPT, "2", quota_key, replay_key,
        str(daily_limit), str(_REPLAY_TTL_SECONDS),
    ]
    body = json.dumps(command, separators=(",", ":")).encode("utf-8")
    request = Request(
        endpoint, data=body, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        # Do not inherit proxy environment variables and never follow a
        # redirect that might forward the Redis credential elsewhere.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise ValueError("admission transport status")
            raw_response = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw_response) > _MAX_RESPONSE_BYTES:
            raise ValueError("admission response exceeds bound")
        parsed = json.loads(raw_response.decode("utf-8"))
        if not isinstance(parsed, dict) or set(parsed) != {"result"}:
            raise ValueError("admission result envelope")
        decision = parsed["result"]
        if type(decision) is not int or decision not in (0, 1, 2):
            raise ValueError("admission decision")
    except Exception:
        # Deliberately no logging: network and parse exceptions can contain
        # REST tokens, user-controlled IDs or upstream response data.
        return 503, _failure("admission_unavailable", "Review admission is unavailable",
                             unavailable=True)

    if decision == 0:
        return None, None
    if decision == 1:
        return 409, _failure("duplicate_request", "This request was already submitted")
    return 429, _failure("daily_budget_exhausted", "Daily review allowance exhausted")
