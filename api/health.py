"""Unauthenticated liveness, not an inference quality or authorization receipt."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from aeonith.service import encode_result, is_ready


class handler(BaseHTTPRequestHandler):  # Vercel Python runtime entrypoint
    def log_message(self, _format: str, *args: object) -> None:
        # No request-target/header logging from the app itself.
        return

    def _respond(self, code: int, result: dict[str, object]) -> None:
        body = encode_result(result)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._respond(200, {
            "schema_version": "aeonith.health.v1",
            "service": "aeonith",
            "status": "ok",
            "review_configured": is_ready(),
        })

    def do_POST(self) -> None:
        self._respond(405, {"error": {"code": "method_not_allowed",
                                      "message": "GET required"}})

    def do_OPTIONS(self) -> None:
        self.do_POST()

    def do_HEAD(self) -> None:
        # Respond without writing an HTTP body; no cross-origin preflight.
        self.send_response(405)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

