"""Explicit, non-billable smoke checks against a protected Aeonith preview.

No network by default. The only POST has no application bearer authorization,
so the review service must reject it before reading content or calling a model.
Never print source text, credentials, raw responses, or untrusted URLs.
"""

from __future__ import annotations

import argparse
from email.message import Message
from http.client import HTTPException
import json
import math
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JWT = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_MAX_REPLY_BYTES = 65_536
_MAX_TIMEOUT_SECONDS = 15.0
_CHECKS: tuple[tuple[str, str, str, int], ...] = (
    ("health", "GET", "/healthz", 200),
    ("health_alias", "GET", "/api/health", 200),
    ("health_method", "POST", "/healthz", 405),
    # The direct entrypoint reaches Aeonith's handler even when Vercel itself
    # would serve an unrelated platform HTML 404 for an arbitrary URL.
    ("unknown_route", "GET", "/api?aeonith_route=bogus", 404),
    ("review_method", "GET", "/api/review", 405),
    # The service must return 401 with a configured bearer secret, or 503
    # when it deliberately has no service secret. No body or bearer is sent.
    ("review_unauthorized", "POST", "/api/review", 0),
)


class PreviewSmokeError(Exception):
    """Only sanitized internal failure codes belong in command output."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PreviewSmokeError("redirect_refused")


def confirm_origin(origin: str, expected_host: str | None) -> str:
    """Allow only an exact Vercel preview HTTPS origin, independently confirmed."""
    if not isinstance(origin, str) or not origin:
        raise PreviewSmokeError("origin_required")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise PreviewSmokeError("invalid_origin") from exc
    host = parsed.hostname
    if (
        not origin.isascii()
        or len(origin) > 255
        or parsed.scheme != "https"
        or not host
        or not host.endswith(".vercel.app")
        or port is not None
        or parsed.netloc.lower() != host
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(c) < 33 or ord(c) == 127 for c in origin)
    ):
        raise PreviewSmokeError("invalid_origin")
    if not expected_host or expected_host.lower() != host:
        raise PreviewSmokeError("remote_host_confirmation_required")
    return origin


def _oidc_header(env_name: str | None) -> str | None:
    if env_name is None:
        return None
    if not _ENV_NAME.fullmatch(env_name):
        raise PreviewSmokeError("invalid_token_env_name")
    value = os.environ.get(env_name)
    if (not value or not value.isascii() or len(value) > 16_384
            or value != value.strip() or not _JWT.fullmatch(value)):
        raise PreviewSmokeError("trusted_oidc_token_missing_or_invalid")
    return value


def _parse_reply(raw: bytes, headers: Message) -> dict:
    if len(raw) > _MAX_REPLY_BYTES:
        raise PreviewSmokeError("response_too_large")
    if not headers.get("Content-Type", "").lower().startswith("application/json"):
        raise PreviewSmokeError("non_json_response")
    if "no-store" not in headers.get("Cache-Control", "").lower():
        raise PreviewSmokeError("response_cache_control_missing")

    def unique_pairs(pairs):
        result = {}
        for key, val in pairs:
            if key in result:
                raise PreviewSmokeError("invalid_json_response")
            result[key] = val
        return result

    def invalid_constant(_value):
        raise PreviewSmokeError("invalid_json_response")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                            parse_constant=invalid_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PreviewSmokeError("invalid_json_response") from exc
    if not isinstance(result, dict):
        raise PreviewSmokeError("invalid_json_response")
    return result


def _one_probe(origin: str, method: str, path: str, timeout: float,
               oidc_token: str | None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if oidc_token:
        headers["x-vercel-trusted-oidc-idp-token"] = oidc_token
    request = Request(origin + path, data=b"" if method == "POST" else None,
                      headers=headers, method=method)
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            response_headers = response.headers
            raw = response.read(_MAX_REPLY_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        response_headers = exc.headers
        raw = exc.read(_MAX_REPLY_BYTES + 1)
        exc.close()
    except PreviewSmokeError:
        raise
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise PreviewSmokeError("transport_error") from None
    return status, _parse_reply(raw, response_headers)


def _verify_contract(check: str, status: int, result: dict, expected: int) -> None:
    if check in {"health", "health_alias"}:
        if (status != 200 or result.get("schema_version") != "aeonith.health.v1"
                or result.get("service") != "aeonith" or result.get("status") != "ok"
                or not isinstance(result.get("review_configured"), bool)):
            raise PreviewSmokeError("health_contract_failed")
        return
    if check == "review_unauthorized":
        if status not in {401, 503}:
            raise PreviewSmokeError("review_unauthorized_contract_failed")
        expected_code = "unauthorized" if status == 401 else "service_unconfigured"
    else:
        if status != expected:
            raise PreviewSmokeError("route_contract_failed")
        expected_code = "not_found" if check == "unknown_route" else "method_not_allowed"
    if (result.get("schema_version") != "aeonith.review.v1"
            or not isinstance(result.get("error"), dict)
            or result["error"].get("code") != expected_code):
        raise PreviewSmokeError("error_contract_failed")


def run_smoke(origin: str, *, expected_host: str | None,
              trusted_oidc_env: str | None = None, timeout: float = 8.0) -> int:
    origin = confirm_origin(origin, expected_host)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0
            or timeout > _MAX_TIMEOUT_SECONDS):
        raise PreviewSmokeError("timeout_out_of_bounds")
    token = _oidc_header(trusted_oidc_env)
    for check, method, path, expected in _CHECKS:
        try:
            status, result = _one_probe(origin, method, path, timeout, token)
            _verify_contract(check, status, result, expected)
        except PreviewSmokeError as exc:
            raise PreviewSmokeError(f"{check}:{exc}") from None
    return len(_CHECKS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit zero-inference Aeonith preview smoke")
    parser.add_argument("--execute", action="store_true", help="Run the six bounded, non-billable HTTP probes")
    parser.add_argument("--origin", help="Exact HTTPS Vercel preview origin, no path, e.g. https://deployment.vercel.app")
    parser.add_argument("--expected-host", help="Exact independently verified hostname, no scheme or path")
    parser.add_argument("--trusted-oidc-env", help="Optional name of env var containing a short-lived Vercel Trusted Source OIDC token")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-request timeout, >0 to <=15 seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_run", "reason": "explicit_execution_required"}, sort_keys=True))
        return 2
    try:
        count = run_smoke(args.origin, expected_host=args.expected_host,
                          trusted_oidc_env=args.trusted_oidc_env, timeout=args.timeout)
    except PreviewSmokeError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "reason": "unexpected_smoke_error"}, sort_keys=True))
        return 1
    print(json.dumps({"status": "passed", "checks": count, "paid_inference_calls": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
