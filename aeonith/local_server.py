"""Run Aeonith's private review interface on an existing computer.

The server uses only the Python standard library. It neither provisions a
cloud service nor chooses a model; :mod:`aeonith.service` owns provider
configuration, manuscript validation, authorization and readiness. The
default listener is strictly loopback, not a public deployment.

Usage::

    python -m aeonith.local_server

Set a strong ``AEONITH_SERVICE_TOKEN`` and configure a *local* model through
the service environment variables before submitting any manuscript.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import socket
import sysconfig
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from aeonith.service import _error, authorize
from aeonith.funnel_limits import LocalAdmission
from api.health import handler as HealthHandler
from api.review import handler as ReviewHandler


_SOURCE_PUBLIC = Path(__file__).resolve().parent.parent / "public"
_INSTALLED_PUBLIC = Path(sysconfig.get_path("data")) / "share" / "aeonith"
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/docx-import-worker.js": ("docx-import-worker.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
_HEALTH_PATHS = frozenset({"/healthz", "/api/health"})
_REVIEW_PATHS = frozenset({"/api/review", "/v1/critique"})
_MAX_ASSET_BYTES = 2_000_000
_MAX_CONNECTIONS = 16
_IDLE_SOCKET_TIMEOUT_SECONDS = 15
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


def _funnel_host(value: str | None) -> str | None:
    """Validate a single HTTPS Funnel origin; never accept arbitrary web hosts.

    The origin is server-owned configuration. A hostname supplied by an HTTP
    client (or by an untrusted forwarded header) never enables this mode.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 253 or not value.isascii():
        raise ValueError("AEONITH_FUNNEL_ORIGIN must be a bounded HTTPS .ts.net origin")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
    except ValueError as exc:
        raise ValueError("invalid AEONITH_FUNNEL_ORIGIN") from exc
    labels = host.split(".")
    if (len(labels) != 4 or labels[-2:] != ["ts", "net"]
            or any(_DNS_LABEL.fullmatch(part) is None for part in labels)
            or parsed.scheme != "https" or value != f"https://{host}"
            or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("AEONITH_FUNNEL_ORIGIN must be an exact HTTPS machine.tailnet.ts.net origin")
    return host


def _bind_address(host: str) -> tuple[str, int]:
    """Reject public listeners and all DNS-dependent bind names."""
    if host == "localhost":
        host = "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("--host must be a literal IP address or localhost") from exc
    if not address.is_loopback:
        raise ValueError("local server refuses non-loopback binding")
    return str(address), socket.AF_INET6 if address.version == 6 else socket.AF_INET


def _asset_root() -> Path:
    """Work from a source checkout or a wheel with installed data assets."""
    if (_SOURCE_PUBLIC / "index.html").is_file():
        return _SOURCE_PUBLIC
    return _INSTALLED_PUBLIC


class _LocalHandler(ReviewHandler):
    """Restricted local routes; never serves arbitrary filesystem paths."""

    server_version = "AeonithLocal"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        # An idle loopback connection must not consume a worker indefinitely.
        self.connection.settimeout(_IDLE_SOCKET_TIMEOUT_SECONDS)

    def end_headers(self) -> None:
        if getattr(self, "_retry_after", 0):
            self.send_header("Retry-After", str(self._retry_after))
        self.send_header("Content-Security-Policy", (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; worker-src 'self'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        ))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _route(self) -> str | None:
        # Treat all queries, fragments and encoded path variants as unknown.
        if len(self.path) > 256 or "?" in self.path or "#" in self.path:
            return None
        try:
            path = urlsplit(self.path)
        except ValueError:
            return None
        if path.query or path.fragment or path.scheme or path.netloc:
            return None
        if path.path in _ASSETS:
            return "asset"
        if path.path in _HEALTH_PATHS:
            return "health"
        if path.path in _REVIEW_PATHS:
            return "review"
        return None

    def _same_host(self) -> bool:
        """Block DNS rebinding; accept only local or explicitly pinned Funnel origin."""
        values = self.headers.get_all("Host", [])
        if len(values) != 1 or len(values[0]) > 256:
            return False
        raw = values[0]
        if not raw or any(character.isspace() for character in raw):
            return False
        try:
            parsed = urlsplit("http://" + raw)
            port = parsed.port
            hostname = parsed.hostname
        except ValueError:
            return False
        if (not hostname or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password or parsed.netloc != raw):
            return False
        origin_values = self.headers.get_all("Origin", [])
        if len(origin_values) > 1:
            return False
        funnel_host = self.server.funnel_host
        if funnel_host and raw == funnel_host and hostname == funnel_host:
            # HTTPS terminates on the operator's own Tailscale device. Only
            # the exact configured public origin may make browser requests.
            # Never infer public origin from X-Forwarded-* request headers.
            if self.command == "POST" and not origin_values:
                return False
            return not origin_values or origin_values[0] == f"https://{funnel_host}"
        actual_port = self.server.server_port
        if port is not None and port != actual_port:
            return False
        if port is None and actual_port != 80:
            return False
        bound_host = self.server.server_address[0]
        if bound_host in {"127.0.0.1", "::1"}:
            allowed_hosts = {bound_host, "localhost"}
        else:
            allowed_hosts = {bound_host}
        if hostname not in allowed_hosts:
            return False
        if origin_values:
            try:
                origin = urlsplit(origin_values[0])
                origin_port = origin.port
            except ValueError:
                return False
            if (origin.scheme != "http" or origin.hostname != hostname
                    or (origin_port or 80) != actual_port or origin.path
                    or origin.query or origin.fragment or origin.username
                    or origin.password):
                return False
        return True

    def _dispatch_allowed(self) -> bool:
        if self._same_host():
            return True
        self.close_connection = True
        self._respond(403, _error("forbidden_origin", "Request origin is not permitted"))
        return False

    def _unknown_or_wrong_method(self, route: str | None) -> None:
        self.close_connection = True
        if route is None:
            self._respond(404, _error("not_found", "Unknown local route"))
        else:
            self._respond(405, _error("method_not_allowed", "Method is not allowed for this route"))

    def _rate_limited(self, code: str, retry_after: int) -> None:
        """Reply without reading a manuscript or disclosing internal counters."""
        self.close_connection = True
        self._retry_after = max(1, retry_after)
        try:
            self._respond(429, _error(code, "Local review capacity is temporarily unavailable"))
        finally:
            self._retry_after = 0

    def _serve_asset(self, path: str) -> None:
        filename, content_type = _ASSETS[path]
        resource = _asset_root() / filename
        try:
            if resource.stat().st_size > _MAX_ASSET_BYTES:
                raise ValueError("oversized asset")
            body = resource.read_bytes()
            if len(body) > _MAX_ASSET_BYTES:
                raise ValueError("oversized asset")
        except (OSError, ValueError):
            self._respond(503, _error("asset_unavailable", "Local interface is unavailable"))
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._dispatch_allowed():
            return
        if self.path == "/?utm_source=chatgpt.com":
            # ChatGPT decorates outbound links. Strip this exact public
            # decoration without relaxing the prohibition on query-bearing
            # API routes or potentially sensitive URL parameters.
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        route = self._route()
        if route == "health":
            HealthHandler.do_GET(self)
        elif route == "asset":
            self._serve_asset(urlsplit(self.path).path)
        else:
            self._unknown_or_wrong_method(route)

    def do_POST(self) -> None:
        if not self._dispatch_allowed():
            return
        route = self._route()
        if route == "review":
            admission = self.server.public_limiter
            if admission is None:
                # Provider remains strictly loopback. The private-only path
                # retains the original auth-before-manuscript behavior.
                ReviewHandler.do_POST(self)
                return
            # Public mode has a global local throttle, independent of Host
            # spelling. A forged Host: localhost header cannot evade quotas.
            status, result = authorize(self.headers)
            if status is not None:
                if status == 401:
                    allowed, retry_after = admission.auth_attempt_allowed()
                    if not allowed:
                        self._rate_limited("authentication_rate_limited", retry_after)
                        return
                    admission.record_auth_failure()
                self._respond(status, result or _error("unauthorized", "Authorization required"))
                return
            # Failed credentials must never consume the legitimate owner's
            # authorization capacity. Only failed credentials are throttled;
            # valid ones still face the independent model-review quota.
            reservation, retry_after = admission.begin_review()
            if reservation is None:
                self._rate_limited("review_rate_limited", retry_after)
                return
            # A valid bearer and a reserved allowance precede body reads.
            # The reusable handler rechecks authorization before reading.
            with reservation:
                ReviewHandler.do_POST(self)
        else:
            self._unknown_or_wrong_method(route)

    def do_OPTIONS(self) -> None:
        if self._dispatch_allowed():
            self._unknown_or_wrong_method(self._route())

    def do_HEAD(self) -> None:
        # Deliberately no HEAD route, to avoid any accidental API operation.
        if self._dispatch_allowed():
            self.send_response(405 if self._route() else 404)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

    do_PUT = do_OPTIONS
    do_PATCH = do_OPTIONS
    do_DELETE = do_OPTIONS


def create_server(host: str = "127.0.0.1", port: int = 8765,
                  *, funnel_origin: str | None = None) -> ThreadingHTTPServer:
    """Create an HTTP server without contacting or provisioning anything."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("port must be an integer between 0 and 65535")
    bind_host, address_family = _bind_address(host)
    selected_origin = funnel_origin if funnel_origin is not None else os.environ.get("AEONITH_FUNNEL_ORIGIN")
    configured_funnel_host = _funnel_host(selected_origin)
    if configured_funnel_host and bind_host != "127.0.0.1":
        raise ValueError("Funnel mode requires the local server bound to 127.0.0.1")

    class BoundServer(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self, *args, **kwargs):
            self._connection_slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
            self.funnel_host = configured_funnel_host
            self.public_limiter = LocalAdmission() if configured_funnel_host else None
            super().__init__(*args, **kwargs)

        def process_request(self, request, client_address):
            if not self._connection_slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self._connection_slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self._connection_slots.release()

    BoundServer.address_family = address_family
    return BoundServer((bind_host, port), _LocalHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private, zero-cost Aeonith local HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="listener IP (default: loopback only)")
    parser.add_argument("--port", type=int, default=8765, help="listener port (default: 8765)")
    args = parser.parse_args(argv)
    try:
        server = create_server(args.host, args.port)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    host, port = server.server_address[:2]
    bracketed = f"[{host}]" if ":" in host else host
    print(f"Aeonith private local UI: http://{bracketed}:{port}/", flush=True)
    if server.funnel_host:
        print(f"Approved Funnel origin: https://{server.funnel_host} (enable Tailscale separately)", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
