"""Pilot cost-exposure bounds; all providers are local fakes, with no network."""

from __future__ import annotations

import json
import unittest

from aeonith.service import MAX_BODY_BYTES, _construct_provider, is_ready, process_review


TOKEN = "t" * 48
ENV = {
    "AEONITH_SERVICE_TOKEN": TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "openai-responses",
    "AEONITH_PROVIDER_URL": "https://provider.example.test/v1/responses",
    "AEONITH_PROVIDER_MODEL": "synthetic-test-model",
    "AEONITH_PROVIDER_API_KEY": "not-a-real-credential",
    # Readiness is now deliberately false on Vercel without a configured
    # distributed admission gate. These are syntactically valid test fixtures.
    "AEONITH_ADMISSION_REDIS_URL": "https://test-ledger-123.upstash.io",
    "AEONITH_ADMISSION_REDIS_TOKEN": "not-a-real-redis-token",
    "AEONITH_DAILY_REVIEW_LIMIT": "2",
}
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "X-Aeonith-Disclosure": "accepted",
}


class CountingProvider:
    name = "pilot_test_fake"

    def __init__(self) -> None:
        self.calls = 0

    def review(self, payload):
        self.calls += 1
        return {
            "lens_reviews": [
                {
                    "lens": lens,
                    "analysis": "The passage repeats a letter, inviting a minimal textual observation.",
                    "basis": "textual",
                    "support": [{"source": "work", "quote": "A"}],
                    "limitations": [],
                }
                for lens in payload["task"]["lenses"]
            ],
            "synthesis": "Only a narrow reading is warranted from a repeated letter.",
            "challenges": [],
            "uncertainties": [],
            "assessment": None,
        }


def run(request: dict, *, env: dict | None = None, provider: CountingProvider | None = None):
    return process_review(
        json.dumps(request).encode("utf-8"), HEADERS,
        ENV if env is None else env,
        provider=provider,
    )


class PilotLimitTests(unittest.TestCase):
    def test_http_body_limit_is_bounded_below_cli_megabyte_budget(self):
        self.assertEqual(MAX_BODY_BYTES, 64 * 1024)
        provider = CountingProvider()
        status, result = process_review(b"x" * (MAX_BODY_BYTES + 1), HEADERS, ENV,
                                        provider=provider)
        self.assertEqual(status, 413)
        self.assertEqual(result["error"]["code"], "payload_too_large")
        self.assertEqual(provider.calls, 0)

    def test_rejects_work_longer_than_twelve_thousand_characters_before_model(self):
        for work in ("A" * 12_001, {"text": "A" * 12_001, "title": "Long"}):
            with self.subTest(work_type=type(work).__name__):
                provider = CountingProvider()
                status, result = run({"schema_version": "aeonith.review.v1", "work": work}, provider=provider)
                self.assertEqual(status, 413)
                self.assertEqual(result["error"]["code"], "pilot_limit_exceeded")
                self.assertEqual(provider.calls, 0)

    def test_work_boundary_allows_twelve_thousand_characters(self):
        provider = CountingProvider()
        status, result = run({
            "schema_version": "aeonith.review.v1",
            "work": {"text": "A" * 12_000},
            "lenses": ["symbolic"],
        }, provider=provider)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(provider.calls, 1)

    def test_rejects_oversized_context_before_model(self):
        provider = CountingProvider()
        status, result = run({
            "schema_version": "aeonith.review.v1", "work": {"text": "A"},
            "context": "C" * 2_001,
        }, provider=provider)
        self.assertEqual(status, 413)
        self.assertEqual(result["error"]["code"], "pilot_limit_exceeded")
        self.assertEqual(provider.calls, 0)

    def test_configured_lens_cap_prevents_excessive_work(self):
        provider = CountingProvider()
        status, result = run({
            "schema_version": "aeonith.review.v1", "work": {"text": "A"},
            "lenses": ["symbolic", "philosophical"],
        }, env={**ENV, "AEONITH_MAX_LENSES": "1"}, provider=provider)
        self.assertEqual(status, 413)
        self.assertEqual(result["error"]["code"], "pilot_limit_exceeded")
        self.assertEqual(provider.calls, 0)

    def test_invalid_host_limits_fail_closed_before_paid_inference(self):
        for key, value in (
            ("AEONITH_MAX_LENSES", "0"),
            ("AEONITH_MAX_LENSES", "15"),
            ("AEONITH_MAX_OUTPUT_TOKENS", "0"),
            ("AEONITH_MAX_OUTPUT_TOKENS", "999999"),
            ("AEONITH_MAX_OUTPUT_TOKENS", "garbage"),
            ("AEONITH_PROVIDER_TIMEOUT_SECONDS", "nan"),
            ("AEONITH_PROVIDER_TIMEOUT_SECONDS", "61"),
        ):
            with self.subTest(variable=key, value=value):
                env = {**ENV, key: value}
                provider = CountingProvider()
                self.assertFalse(is_ready(env))
                status, _ = run({"schema_version": "aeonith.review.v1", "work": "A"},
                                env=env, provider=provider)
                self.assertEqual(status, 503)
                self.assertEqual(provider.calls, 0)

    def test_bounded_provider_timeout_and_output_are_server_selected(self):
        provider = _construct_provider({
            **ENV, "AEONITH_MAX_OUTPUT_TOKENS": "1024",
            "AEONITH_PROVIDER_TIMEOUT_SECONDS": "20",
        })
        self.assertEqual(provider.max_tokens, 1024)
        self.assertEqual(provider.timeout, 20.0)
        self.assertLessEqual(_construct_provider(ENV).max_tokens, 8192)
        self.assertLessEqual(_construct_provider(ENV).timeout, 50)

    def test_vercel_responses_endpoint_is_exact_allowlisted(self):
        hosted = {**ENV, "VERCEL": "1"}
        self.assertFalse(is_ready(hosted))
        provider = CountingProvider()
        code, _ = run({"schema_version": "aeonith.review.v1", "work": "A"},
                      env=hosted, provider=provider)
        self.assertEqual(code, 503)
        self.assertEqual(provider.calls, 0)
        self.assertTrue(is_ready({**hosted, "AEONITH_PROVIDER_URL": "https://api.openai.com/v1/responses"}))

    def test_custom_exact_endpoint_requires_explicit_host_allowlist(self):
        hosted = {**ENV, "VERCEL_ENV": "production"}
        self.assertFalse(is_ready(hosted))
        permitted = {**hosted, "AEONITH_ALLOWED_PROVIDER_URLS": ENV["AEONITH_PROVIDER_URL"]}
        self.assertTrue(is_ready(permitted))
        self.assertFalse(is_ready({**hosted, "AEONITH_ALLOWED_PROVIDER_URLS": "https://provider.example.test/"}))

    def test_hosted_allowlist_does_not_override_https_and_secret_safety(self):
        for url in (
            "http://localhost:8000/v1/responses",
            "http://127.0.0.1:8000/v1/responses",
            "https://provider.example.test/v1/responses?token=embedded",
            "https://provider.example.test/v1/responses#fragment",
            "https://user:password@provider.example.test/v1/responses",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_ready({
                    **ENV, "VERCEL_ENV": "production",
                    "AEONITH_PROVIDER_URL": url,
                    "AEONITH_ALLOWED_PROVIDER_URLS": url,
                }))

    def test_hosted_vercel_gateway_requires_oidc_to_keep_project_budget_lane(self):
        gateway = "https://ai-gateway.vercel.sh/v1/responses"
        hosted = {**ENV, "VERCEL": "1", "AEONITH_PROVIDER_URL": gateway}
        # A conventional key is explicitly insufficient on Vercel: otherwise
        # this request would escape a project-scoped OIDC spending budget.
        self.assertFalse(is_ready(hosted))
        with_oidc = {**hosted, "VERCEL_OIDC_TOKEN": "nonsecret-test-oidc-token"}
        self.assertTrue(is_ready(with_oidc))
        self.assertEqual(_construct_provider(with_oidc).api_key, "nonsecret-test-oidc-token")
        self.assertFalse(is_ready({**hosted, "AEONITH_PROVIDER_API_KEY": ""}))

    def test_oidc_token_is_never_forwarded_to_other_provider_host(self):
        gateway = "https://ai-gateway.vercel.sh/v1/responses"
        env = {
            **ENV, "VERCEL": "1", "VERCEL_OIDC_TOKEN": "nonsecret-test-oidc-token",
            "AEONITH_PROVIDER_API_KEY": "",
            "AEONITH_PROVIDER_URL": "https://api.openai.com/v1/responses",
        }
        self.assertFalse(is_ready(env))
        self.assertIsNone(_construct_provider(env).api_key)
        self.assertTrue(is_ready({**env, "AEONITH_PROVIDER_URL": gateway}))

    def test_local_fake_provider_workflow_remains_compatible(self):
        self.assertTrue(is_ready(ENV))
        self.assertEqual(_construct_provider(ENV).url, ENV["AEONITH_PROVIDER_URL"])


if __name__ == "__main__":
    unittest.main()
