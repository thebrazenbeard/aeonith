"""Prove the paid HTTP dispatch cannot bypass distributed admission."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from aeonith.service import is_ready, process_review


TOKEN = "private-test-service-secret-" + "s" * 32
REQUEST_ID = "508c86e9-bfda-461d-b0fd-f5e6418d547a"
ENV = {
    "VERCEL": "1",
    "AEONITH_SERVICE_TOKEN": TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "openai-responses",
    "AEONITH_PROVIDER_URL": "https://api.openai.com/v1/responses",
    "AEONITH_PROVIDER_MODEL": "test-model",
    "AEONITH_PROVIDER_API_KEY": "not-a-real-api-key",
    "AEONITH_ADMISSION_REDIS_URL": "https://test-ledger-123.upstash.io",
    "AEONITH_ADMISSION_REDIS_TOKEN": "not-a-real-redis-token",
    "AEONITH_DAILY_REVIEW_LIMIT": "2",
}
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Content-Type": "application/json",
    "X-Aeonith-Disclosure": "accepted",
    "X-Aeonith-Request-Id": REQUEST_ID,
}
BODY = json.dumps({
    "schema_version": "aeonith.review.v1",
    "work": {"text": "A clock stopped. Nobody noticed."},
    "lenses": ["symbolic"],
}).encode()


class FakeProvider:
    name = "test_injected_provider"

    def __init__(self):
        self.calls = 0

    def review(self, _payload):
        self.calls += 1
        return {
            "lens_reviews": [{
                "lens": "symbolic",
                "analysis": "The stopped clock may suggest an unnoticed ending.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "A clock stopped."}],
                "limitations": ["A fragment cannot establish the entire story."],
            }],
            "synthesis": "The clock invites readings about unnoticed change.",
            "assessment": None,
            "challenges": [],
            "uncertainties": [],
        }


class ServiceAdmissionIntegrationTests(unittest.TestCase):
    def test_hosted_readiness_requires_durable_gate_configuration(self):
        self.assertTrue(is_ready(ENV))
        for missing in ("AEONITH_ADMISSION_REDIS_URL", "AEONITH_ADMISSION_REDIS_TOKEN",
                        "AEONITH_DAILY_REVIEW_LIMIT"):
            with self.subTest(missing=missing):
                self.assertFalse(is_ready({k: v for k, v in ENV.items() if k != missing}))

    def test_reservation_denial_never_invokes_even_an_injected_provider(self):
        fake = FakeProvider()
        denial = {"schema_version": "aeonith.review.v1", "status": "invalid_request",
                  "error": {"code": "daily_budget_exhausted", "message": "Limit reached"}}
        for status in (409, 429, 503):
            with self.subTest(status=status):
                with patch("aeonith.service.admit_request", return_value=(status, denial)) as gate:
                    code, _ = process_review(BODY, HEADERS, ENV, provider=fake)
                self.assertEqual(code, status)
                gate.assert_called_once()
        self.assertEqual(fake.calls, 0)

    def test_hosted_auth_validation_and_disclosure_precede_reservation(self):
        fake = FakeProvider()
        cases = (
            (BODY, {**HEADERS, "Authorization": "Bearer invalid"}, 401),
            (b"{broken-json", HEADERS, 400),
            (b'{"schema_version":"aeonith.review.v1","work":{"text":"A"},"lenses":["not_a_lens"]}', HEADERS, 400),
            (BODY, {k: v for k, v in HEADERS.items() if k != "X-Aeonith-Disclosure"}, 403),
        )
        for body, headers, expected in cases:
            with self.subTest(expected=expected):
                with patch("aeonith.service.admit_request") as gate:
                    code, _ = process_review(body, headers, ENV, provider=fake)
                self.assertEqual(code, expected)
                gate.assert_not_called()
        self.assertEqual(fake.calls, 0)

    def test_actual_http_path_reserves_before_constructing_provider(self):
        fake = FakeProvider()
        sequence = []

        def reserve(headers, env):
            sequence.append("admission")
            self.assertEqual(headers["X-Aeonith-Request-Id"], REQUEST_ID)
            self.assertEqual(env["AEONITH_DAILY_REVIEW_LIMIT"], "2")
            return None, None

        def construct(_env):
            sequence.append("construct")
            return fake

        with patch("aeonith.service.admit_request", side_effect=reserve), \
             patch("aeonith.service._construct_provider", side_effect=construct):
            code, result = process_review(BODY, HEADERS, ENV)
        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(sequence, ["construct", "admission", "construct"])


if __name__ == "__main__":
    unittest.main()
