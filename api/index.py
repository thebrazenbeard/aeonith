"""Single, route-aware Vercel Python entrypoint for the Aeonith API.

The platform selects one Python handler and can rewrite multiple friendly
routes to it. Health and critique still have separate method contracts.
The rewrite's query marker is a routing hint, never authorization.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from aeonith.service import _error
from api.health import handler as HealthHandler
from api.review import handler as ReviewHandler

_HEALTH_PATHS = frozenset({"/healthz", "/api/health"})
_REVIEW_PATHS = frozenset({"/v1/critique", "/api/review"})
_ROUTE_HINT = "aeonith_route"


class handler(ReviewHandler):
    """Choose health/review by route before enforcing the HTTP method.

    When the runtime preserves the original path, it takes precedence over
    client query parameters. When it supplies only rewritten /api, a single
    exact query marker selects the handler. The marker is public; a caller
    can also send it directly to /api. It grants no authority to dispatch
    inference; ReviewHandler still requires the server-held bearer secret,
    and spend/rate limits must apply to every POST alias.
    """

    def _route(self) -> str | None:
        try:
            parsed = urlsplit(self.path)
        except (TypeError, ValueError):
            return None
        if parsed.path in _HEALTH_PATHS:
            return "health"
        if parsed.path in _REVIEW_PATHS:
            return "review"
        if parsed.path != "/api":
            return None
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True,
                              strict_parsing=True, max_num_fields=8)
        except ValueError:
            return None
        # Duplicates, unrelated fields and malformed hints fail closed.
        if len(pairs) != 1 or pairs[0][0] != _ROUTE_HINT:
            return None
        return pairs[0][1] if pairs[0][1] in {"health", "review"} else None

    def _route_error(self, known_route: bool) -> None:
        if known_route:
            self._respond(405, _error("method_not_allowed", "Method is not allowed for this route"))
        else:
            self._respond(404, _error("not_found", "Unknown service route"))

    def do_GET(self) -> None:
        route = self._route()
        if route == "health":
            HealthHandler.do_GET(self)
        else:
            self._route_error(route is not None)

    def do_POST(self) -> None:
        route = self._route()
        if route == "review":
            ReviewHandler.do_POST(self)
        else:
            # Unknown/health paths never read bodies or invoke providers.
            self._route_error(route is not None)

    def do_OPTIONS(self) -> None:
        self._route_error(self._route() is not None)

    def do_PUT(self) -> None:
        self._route_error(self._route() is not None)

    def do_PATCH(self) -> None:
        self._route_error(self._route() is not None)

    def do_DELETE(self) -> None:
        self._route_error(self._route() is not None)

    def do_HEAD(self) -> None:
        self.send_response(405 if self._route() is not None else 404)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
