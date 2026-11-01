"""Single Vercel Python runtime entrypoint for the protected Aeonith API.

Vercel's project-level Python runtime chooses one explicit entrypoint. The
existing health and review handlers retain their independently tested HTTP
behavior; the canonical /api route dispatches GET to health and POST to review.
Friendly paths are rewritten to /api in vercel.json.
"""

from __future__ import annotations

from api.health import handler as HealthHandler
from api.review import handler as ReviewHandler


class handler(ReviewHandler):
    """Vercel HTTP handler: GET liveness, POST authenticated critique."""

    def do_GET(self) -> None:
        HealthHandler.do_GET(self)

    def do_POST(self) -> None:
        ReviewHandler.do_POST(self)

    def do_OPTIONS(self) -> None:
        ReviewHandler.do_OPTIONS(self)

    def do_HEAD(self) -> None:
        ReviewHandler.do_HEAD(self)
