"""Offline two-server integration tests for optional Tailscale Funnel ingress.

The public HTTPS address exists only as simulated HTTP Host/Origin headers.
Both real HTTP servers bind ephemeral loopback ports, and the real local
OpenAI-compatible transport sends the manuscript only to the model fixture.
No network access, cloud account, paid inference, or Tailscale installation
is needed to run this suite.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from aeonith.funnel_limits import LocalAdmission
from aeonith.local_server import create_server


FUNNEL_HOST = "critic.test-tailnet.ts.net"
FUNNEL_ORIGIN = f"https://{FUNNEL_HOST}"
TOKEN = "funnel-integration-token-" + "t" * 40
EXACT_QUOTE = "The lantern went dark."
MANUSCRIPT = "The lantern went dark. Nobody lit it."
REQUEST = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Lantern", "text": MANUSCRIPT},
    "lenses": ["symbolic"],
}
CANDIDATE = {
    "lens_reviews": [{
        "lens": "symbolic",
        "analysis": "The extinguished lantern might evoke loss or interrupted hope.",
        "basis": "textual",
        "support": [{"source": "work", "quote": EXACT_QUOTE}],
        "limitations": ["A single image cannot establish its meaning conclusively."],
    }],
    "synthesis": "The image supports a cautious symbolic reading.",
    "uncertainties": ["The story does not explain why the lantern went dark."],
    "challenges": [],
    "assessment": None,
}


class _SyntheticChatCompletions(BaseHTTPRequestHandler):
    """Real HTTP fixture, not an injected/mocked Aeonith provider."""

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 100_000:
            self.send_error(413)
            return
        request = json.loads(self.rfile.read(size))
        with self.server.requests_lock:
            self.server.requests.append(request)
        answer = json.dumps({
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(CANDIDATE)},
            }],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


class FunnelFullPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticChatCompletions)
        cls.model.daemon_threads = True
        cls.model.requests = []
        cls.model.requests_lock = threading.Lock()
        cls.model_thread = threading.Thread(target=cls.model.serve_forever, daemon=True)
        cls.model_thread.start()

        cls.aeonith = create_server(port=0, funnel_origin=FUNNEL_ORIGIN)
        cls.aeonith_thread = threading.Thread(target=cls.aeonith.serve_forever, daemon=True)
        cls.aeonith_thread.start()
        cls.local_url = f"http://127.0.0.1:{cls.aeonith.server_port}"
        cls.config = {
            "AEONITH_SERVICE_TOKEN": TOKEN,
            "AEONITH_ENABLE_LIVE_REVIEWS": "true",
            "AEONITH_PROVIDER_KIND": "local-openai-compatible",
            "AEONITH_PROVIDER_URL": (
                f"http://127.0.0.1:{cls.model.server_port}/v1/chat/completions"
            ),
            "AEONITH_PROVIDER_MODEL": "synthetic-local-model",
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.aeonith.shutdown()
        cls.aeonith.server_close()
        cls.aeonith_thread.join(timeout=5)
        cls.model.shutdown()
        cls.model.server_close()
        cls.model_thread.join(timeout=5)

    def _model_call_count(self) -> int:
        with self.model.requests_lock:
            return len(self.model.requests)

    def _call(self, path: str = "/api/review", *, token: str | None = TOKEN,
              origin: str | None = FUNNEL_ORIGIN, host: str = FUNNEL_HOST,
              config: dict[str, str] | None = None) -> tuple[int, dict]:
        headers = {"Host": host, "Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        payload = json.dumps(REQUEST).encode("utf-8")
        request = Request(self.local_url + path, data=payload, method="POST", headers=headers)
        # Explicitly bypass ambient proxies, including any externally managed
        # proxy that could otherwise receive a manuscript in a test run.
        opener = build_opener(ProxyHandler({}))
        with patch.dict(os.environ, config or self.config, clear=True):
            try:
                with opener.open(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as exc:
                return exc.code, json.loads(exc.read())

    def test_public_origin_reaches_real_local_chat_completions_and_proves_quote(self):
        before = self._model_call_count()
        status, result = self._call()
        self.assertEqual(status, 200, result)
        self.assertEqual(self._model_call_count(), before + 1)
        self.assertEqual(result["schema_version"], "aeonith.review.v1")
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["error"])
        self.assertEqual(result["lens_reviews"][0]["lens"], "symbolic")
        self.assertEqual(
            result["lens_reviews"][0]["support"],
            [{"source": "work", "quote": EXACT_QUOTE}],
        )
        self.assertEqual(result["provenance"]["provider_name"], "local_openai_compatible")
        self.assertEqual(result["provenance"]["selected_lenses"], ["symbolic"])
        self.assertEqual(result["provenance"]["provider_external_knowledge"], "UNKNOWN")
        with self.model.requests_lock:
            model_request = self.model.requests[-1]
        self.assertEqual(model_request["model"], "synthetic-local-model")
        self.assertEqual(model_request["response_format"], {"type": "json_object"})
        self.assertEqual(model_request["messages"][0]["role"], "system")
        self.assertEqual(model_request["messages"][1]["role"], "user")
        self.assertEqual(
            json.loads(model_request["messages"][1]["content"])["work"]["text"],
            MANUSCRIPT,
        )

    def test_legacy_alias_uses_same_local_provider_without_bypassing_public_mode(self):
        before = self._model_call_count()
        status, result = self._call(path="/v1/critique")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self._model_call_count(), before + 1)

    def test_alternate_alias_cannot_bypass_shared_hourly_review_quota(self):
        # Shrink only this server's in-memory quota for a deterministic
        # integration check; both routes still use real service and model.
        previous = self.aeonith.public_limiter
        self.aeonith.public_limiter = LocalAdmission(max_reviews_per_hour=1)
        try:
            before = self._model_call_count()
            first_status, first = self._call(path="/api/review")
            self.assertEqual(first_status, 200, first)
            self.assertEqual(self._model_call_count(), before + 1)
            second_status, second = self._call(path="/v1/critique")
            self.assertEqual(second_status, 429, second)
            self.assertEqual(second["error"]["code"], "review_rate_limited")
            self.assertEqual(self._model_call_count(), before + 1)
        finally:
            self.aeonith.public_limiter = previous

    def test_unauthorized_missing_bearer_never_reaches_local_model(self):
        before = self._model_call_count()
        status, result = self._call(token=None)
        self.assertEqual(status, 401, result)
        self.assertEqual(result["error"]["code"], "unauthorized")
        self.assertNotIn("Lantern", json.dumps(result))
        self.assertEqual(self._model_call_count(), before)

    def test_foreign_origin_and_host_cannot_spoof_funnel(self):
        for kwargs in (
            {"origin": "https://attacker.example"},
            {"origin": None},
            {"host": "attacker.example"},
            {"host": "localhost"},
        ):
            with self.subTest(kwargs=kwargs):
                before = self._model_call_count()
                status, result = self._call(**kwargs)
                self.assertEqual(status, 403, result)
                self.assertEqual(result["error"]["code"], "forbidden_origin")
                self.assertEqual(self._model_call_count(), before)

    def test_paid_or_remote_provider_configuration_fails_closed(self):
        for changes in (
            {"AEONITH_PROVIDER_URL": "https://api.openai.com/v1/chat/completions"},
            {"AEONITH_PROVIDER_KIND": "openai-compatible"},
            {"AEONITH_PROVIDER_API_KEY": "do-not-send"},
            {"VERCEL": "1"},
        ):
            with self.subTest(changes=changes):
                before = self._model_call_count()
                status, result = self._call(config={**self.config, **changes})
                self.assertEqual(status, 503, result)
                self.assertEqual(result["status"], "provider_unavailable")
                self.assertEqual(result["error"]["code"], "provider_unavailable")
                self.assertEqual(self._model_call_count(), before)


if __name__ == "__main__":
    unittest.main()
