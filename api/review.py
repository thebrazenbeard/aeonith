"""Bearer-protected serverless Aeonith critique endpoint."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from aeonith.service import (
    MAX_BODY_BYTES, _error, authorize, encode_result, process_review,
)


class handler(BaseHTTPRequestHandler):  # Vercel Python runtime entrypoint
    def log_message(self, _format: str, *args: object) -> None:
        # Do not emit manuscript-bearing paths, headers or content in logs.
        return

    def _respond(self, code: int, result: dict[str, object]) -> None:
        try:
            body = encode_result(result)
        except (TypeError, ValueError, UnicodeError, RecursionError):
            code = 502
            body = encode_result(_error("invalid_response", "Review response unavailable"))
        if len(body) > 4_000_000:
            code = 502
            body = encode_result(_error("response_too_large", "Review response unavailable"))
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        status, result = authorize(self.headers)
        if status is not None:
            self._respond(status, result or _error("unauthorized", "Authorization required"))
            return
        # Presence, including an empty first value in duplicated headers,
        # makes message framing ambiguous. Never read or invoke a provider.
        if self.headers.get_all("Transfer-Encoding", []):
            self._respond(400, _error("invalid_body", "Chunked requests are not supported"))
            return
        values = self.headers.get_all("Content-Length", [])
        if len(values) != 1:
            self._respond(411, _error("length_required", "Content-Length is required"))
            return
        raw_length = values[0]
        if (not isinstance(raw_length, str) or not raw_length
                or len(raw_length) > 12
                or any(char not in "0123456789" for char in raw_length)):
            self._respond(400, _error("invalid_body", "Invalid Content-Length"))
            return
        declared_length = int(raw_length)
        if declared_length < 0:
            self._respond(400, _error("invalid_body", "Invalid Content-Length"))
            return
        if declared_length > MAX_BODY_BYTES:
            self._respond(413, _error("payload_too_large", "Request body exceeds service limit"))
            return
        raw = self.rfile.read(declared_length)
        if len(raw) != declared_length:
            self._respond(400, _error("invalid_body", "Incomplete request body"))
            return
        code, result = process_review(raw, self.headers)
        self._respond(code, result)

    def do_GET(self) -> None:
        self._respond(405, _error("method_not_allowed", "POST required"))

    def do_OPTIONS(self) -> None:
        self.do_GET()

    def do_HEAD(self) -> None:
        self.send_response(405)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

