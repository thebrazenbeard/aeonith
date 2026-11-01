"""Adversarial contract checks for the loopback-only Aeonith service.

These use a fake provider and an in-memory HTTP handler. No network, real
credentials, paid inference, or external manuscripts are involved.
"""

from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from unittest.mock import patch

from aeonith.service import MAX_BODY_BYTES, authorize, process_review
from api.review import handler as ReviewHandler


TOKEN = "s" * 48
DEFAULT_ENV = {
    "AEONITH_SERVICE_TOKEN": TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "local-openai-compatible",
    "AEONITH_PROVIDER_URL": "http://127.0.0.1:5001/v1/chat/completions",
    "AEONITH_PROVIDER_MODEL": "local",
}
BASE_REQUEST = b'{"schema_version":"aeonith.review.v1","work":{"title":"Example","text":"The last bell rang."}}'


class CountingProvider:
    name = "counting_test_provider"

    def __init__(self, exception: Exception | None = None) -> None:
        self.calls = 0
        self.exception = exception

    def review(self, _payload):
        self.calls += 1
        if self.exception:
            raise self.exception
        return {"lens_reviews": [], "synthesis": "", "uncertainties": []}


def headers(**extra: str) -> dict[str, str]:
    value = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    value.update(extra)
    return value


def call_http(body: bytes, configured: dict[str, str],
              sent_headers: list[tuple[str, str]]) -> tuple[int, dict, str, int]:
    """Call the real BaseHTTPRequestHandler without opening a socket."""
    instance = ReviewHandler.__new__(ReviewHandler)
    instance.rfile = io.BytesIO(body)
    instance.wfile = io.BytesIO()
    instance.request_version = "HTTP/1.1"
    instance.requestline = "POST /api/review HTTP/1.1"
    instance.command = "POST"
    instance.path = "/api/review"
    instance.client_address = ("127.0.0.1", 0)
    message = Message()
    for key, value in sent_headers:
        message.add_header(key, value)
    instance.headers = message
    with patch.dict("os.environ", configured, clear=True):
        instance.do_POST()
    encoded = instance.wfile.getvalue()
    head, tail = encoded.split(b"\r\n\r\n", 1)
    status_line = head.split(b"\r\n", 1)[0]
    status = int(status_line.split()[1])
    return status, json.loads(tail), head.decode("ascii", "replace"), instance.rfile.tell()


class ServiceAuthenticationTests(unittest.TestCase):
    def test_unconfigured_service_fails_closed(self):
        self.assertEqual(authorize(headers(), {} )[0], 503)
        self.assertEqual(authorize(headers(), {"AEONITH_SERVICE_TOKEN": "weak"})[0], 503)

    def test_bad_token_rejected_even_with_malformed_manuscript(self):
        fake = CountingProvider()
        code, result = process_review(b"{unparseable-private-passage",
                                      headers(Authorization="Bearer invalid"),
                                      DEFAULT_ENV, provider=fake)
        self.assertEqual(code, 401)
        self.assertEqual(result["error"]["code"], "unauthorized")
        self.assertEqual(fake.calls, 0)

    def test_lowercase_header_names_and_repeated_auth_are_handled(self):
        self.assertEqual(authorize({"authorization": f"Bearer {TOKEN}"}, DEFAULT_ENV)[0], None)
        # Duplicate header names with different letter case must not silently
        # authorize one of the conflicting values.
        duplicated = {"Authorization": f"Bearer {TOKEN}", "authorization": "Bearer invalid"}
        self.assertEqual(authorize(duplicated, DEFAULT_ENV)[0], 401)

    def test_handler_unauthorized_before_body_read(self):
        status, data, head, bytes_read = call_http(
            b"PRIVATE BODY MUST NOT BE READ", DEFAULT_ENV,
            [("Authorization", "Bearer invalid"), ("Content-Length", "29")],
        )
        self.assertEqual(status, 401)
        self.assertEqual(bytes_read, 0)
        self.assertNotIn("PRIVATE BODY", json.dumps(data))
        self.assertIn("Cache-Control: no-store", head)
        self.assertNotIn("Access-Control-Allow-Origin", head)


class ServicePayloadHardeningTests(unittest.TestCase):
    def test_client_selected_provider_destination_or_secret_is_rejected(self):
        for forbidden in ("url", "model", "api_key", "provider"):
            with self.subTest(forbidden=forbidden):
                fake = CountingProvider()
                request = json.loads(BASE_REQUEST)
                request[forbidden] = "https://metadata.invalid/"
                code, _ = process_review(json.dumps(request).encode(), headers(),
                                         DEFAULT_ENV, provider=fake)
                self.assertEqual(code, 400)
                self.assertEqual(fake.calls, 0)

    def test_content_type_must_be_json(self):
        fake = CountingProvider()
        code, _ = process_review(BASE_REQUEST, headers(**{"Content-Type": "text/plain"}),
                                 DEFAULT_ENV, provider=fake)
        self.assertEqual(code, 415)
        self.assertEqual(fake.calls, 0)

    def test_oversized_body_rejected_before_provider(self):
        fake = CountingProvider()
        code, _ = process_review(b"x" * (MAX_BODY_BYTES + 1), headers(),
                                 DEFAULT_ENV, provider=fake)
        self.assertEqual(code, 413)
        self.assertEqual(fake.calls, 0)

    def test_duplicate_and_nonfinite_json_rejected(self):
        payloads = (
            b'{"schema_version":"aeonith.review.v1","schema_version":"aeonith.review.v1","work":{"text":"t"}}',
            b'{"schema_version":"aeonith.review.v1","work":{"text":"t"},"context":NaN}',
            b'{"schema_version":"aeonith.review.v1","work":{"text":"t"},"context":1e999}',
        )
        for raw in payloads:
            with self.subTest(raw=raw[:60]):
                fake = CountingProvider()
                code, _ = process_review(raw, headers(), DEFAULT_ENV, provider=fake)
                self.assertEqual(code, 400)
                self.assertEqual(fake.calls, 0)

    def test_handler_rejects_missing_repeated_or_chunked_body_length(self):
        cases = (
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Type", "application/json")], 411),
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Length", "2"),
              ("Content-Length", "3")], 411),
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Length", "4"),
              ("Transfer-Encoding", "chunked")], 400),
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Length", "4"),
              ("Transfer-Encoding", ""), ("Transfer-Encoding", "chunked")], 400),
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Length", "9_4")], 400),
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Length", "+94")], 400),
            ([("Authorization", f"Bearer {TOKEN}"),
              ("Content-Length", str(MAX_BODY_BYTES + 1))], 413),
        )
        for sent, expected in cases:
            with self.subTest(expected=expected, sent=sent):
                code, _, head, read_count = call_http(BASE_REQUEST, DEFAULT_ENV, sent)
                self.assertEqual(code, expected)
                self.assertEqual(read_count, 0)
                self.assertNotIn("Access-Control-Allow-Origin", head)

    def test_local_model_requires_no_external_disclosure(self):
        fake = CountingProvider()
        sent = headers()
        code, result = process_review(BASE_REQUEST, sent, DEFAULT_ENV, provider=fake)
        # Fake returns an invalid critique, but model invocation is allowed:
        # local-only routing does not require a third-party disclosure flag.
        self.assertEqual(code, 502)
        self.assertEqual(result["status"], "invalid_provider_output")
        self.assertEqual(fake.calls, 1)

    def test_paid_or_remote_model_configuration_rejected_before_dispatch(self):
        for changes in (
            {"AEONITH_PROVIDER_URL": "https://api.openai.com/v1/responses"},
            {"AEONITH_PROVIDER_URL": "https://ai-gateway.vercel.sh/v1/responses"},
            {"AEONITH_PROVIDER_URL": "http://192.168.1.10:5001/v1/chat/completions"},
            {"AEONITH_PROVIDER_API_KEY": "synthetic-credential"},
            {"AEONITH_PROVIDER_KIND": "openai-responses"},
        ):
            with self.subTest(changes=changes):
                fake = CountingProvider()
                code, result = process_review(BASE_REQUEST, headers(),
                                              {**DEFAULT_ENV, **changes}, provider=fake)
                self.assertEqual(code, 503)
                self.assertEqual(result["status"], "provider_unavailable")
                self.assertEqual(fake.calls, 0)

    def test_operator_must_explicitly_enable_model_calls(self):
        fake = CountingProvider()
        env = {**DEFAULT_ENV, "AEONITH_ENABLE_LIVE_REVIEWS": "false"}
        code, _ = process_review(BASE_REQUEST, headers(), env, provider=fake)
        self.assertEqual(code, 503)
        self.assertEqual(fake.calls, 0)

    def test_missing_model_configuration_fails_closed_even_with_injected_provider(self):
        fake = CountingProvider()
        env = {**DEFAULT_ENV, "AEONITH_PROVIDER_MODEL": ""}
        code, _ = process_review(BASE_REQUEST, headers(), env, provider=fake)
        self.assertEqual(code, 503)
        self.assertEqual(fake.calls, 0)

    def test_provider_failure_and_malformed_private_json_are_sanitized(self):
        fake = CountingProvider(RuntimeError("secret-provider-key and manuscript-private-canary"))
        code, result = process_review(BASE_REQUEST, headers(), DEFAULT_ENV, provider=fake)
        self.assertEqual(code, 502)
        self.assertEqual(fake.calls, 1)
        serialized = json.dumps(result)
        self.assertNotIn("secret-provider-key", serialized)
        self.assertNotIn("manuscript-private-canary", serialized)

        bad = b'{"schema_version":"aeonith.review.v1","work":"secret-manuscript-canary" INVALID}'
        code, result = process_review(bad, headers(), DEFAULT_ENV, provider=fake)
        self.assertEqual(code, 400)
        self.assertNotIn("secret-manuscript-canary", json.dumps(result))
        self.assertEqual(fake.calls, 1)

    def test_core_invalid_request_diagnostic_does_not_echo_private_evidence_refs(self):
        private_ref = "PRIVATE-MANUSCRIPT-REFERENCE-CANARY"
        payload = {
            "schema_version": "aeonith.review.v1",
            "work": {"title": "Original work", "text": "The last bell rang."},
            "claims": [{
                "id": "one", "text": "A claim",
                "evidence": [
                    {"kind": "USER", "ref": private_ref},
                    {"kind": "USER", "ref": private_ref},
                ],
            }],
        }
        fake = CountingProvider()
        code, result = process_review(json.dumps(payload).encode(), headers(), DEFAULT_ENV,
                                      provider=fake)
        self.assertEqual(code, 400)
        self.assertNotIn(private_ref, json.dumps(result))
        self.assertEqual(fake.calls, 0)


if __name__ == "__main__":
    unittest.main()
