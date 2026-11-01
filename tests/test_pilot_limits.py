"""Local-service resource bounds; all providers are fakes, with no network."""

from __future__ import annotations

import json
import unittest

from aeonith.service import MAX_BODY_BYTES, _construct_provider, is_ready, process_review


TOKEN = "t" * 48
ENV = {
    "AEONITH_SERVICE_TOKEN": TOKEN,
    "AEONITH_ENABLE_LIVE_REVIEWS": "true",
    "AEONITH_PROVIDER_KIND": "local-openai-compatible",
    "AEONITH_PROVIDER_URL": "http://127.0.0.1:5001/v1/chat/completions",
    "AEONITH_PROVIDER_MODEL": "local",
}
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
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


class LocalLimitTests(unittest.TestCase):
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
                self.assertEqual(result["error"]["code"], "review_limit_exceeded")
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
        self.assertEqual(result["error"]["code"], "review_limit_exceeded")
        self.assertEqual(provider.calls, 0)

    def test_configured_lens_cap_prevents_excessive_work(self):
        provider = CountingProvider()
        status, result = run({
            "schema_version": "aeonith.review.v1", "work": {"text": "A"},
            "lenses": ["symbolic", "philosophical"],
        }, env={**ENV, "AEONITH_MAX_LENSES": "1"}, provider=provider)
        self.assertEqual(status, 413)
        self.assertEqual(result["error"]["code"], "review_limit_exceeded")
        self.assertEqual(provider.calls, 0)

    def test_invalid_host_limits_fail_closed_before_local_inference(self):
        for key, value in (
            ("AEONITH_MAX_LENSES", "0"),
            ("AEONITH_MAX_LENSES", "15"),
            ("AEONITH_MAX_OUTPUT_TOKENS", "0"),
            ("AEONITH_MAX_OUTPUT_TOKENS", "999999"),
            ("AEONITH_MAX_OUTPUT_TOKENS", "garbage"),
            ("AEONITH_PROVIDER_TIMEOUT_SECONDS", "nan"),
            ("AEONITH_PROVIDER_TIMEOUT_SECONDS", "61"),
            ("AEONITH_LOCAL_JSON_MODE", "invalid"),
            ("AEONITH_STRUCTURED_OUTPUTS", "yes"),
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

    def test_local_json_mode_can_be_disabled_for_older_runners(self):
        self.assertTrue(_construct_provider(ENV).json_mode)
        no_json_mode = {**ENV, "AEONITH_LOCAL_JSON_MODE": "false"}
        self.assertTrue(is_ready(no_json_mode))
        self.assertFalse(_construct_provider(no_json_mode).json_mode)

    def test_remote_provider_urls_cannot_activate_review_service(self):
        for url in (
            "https://api.openai.com/v1/responses",
            "https://ai-gateway.vercel.sh/v1/responses",
            "https://provider.example.test/v1/chat/completions",
            "http://192.168.1.10:5001/v1/chat/completions",
            "http://127.0.0.1.evil.test:5001/v1/chat/completions",
            "http://user:pass@127.0.0.1:5001/v1/chat/completions",
            "http://127.0.0.1:5001/v1/chat/completions?token=wrong",
            "http://127.0.0.1:5001/v1/chat/completions#fragment",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_ready({**ENV, "AEONITH_PROVIDER_URL": url}))

    def test_paid_provider_kind_and_key_never_activate_service(self):
        for changes in (
            {"AEONITH_PROVIDER_KIND": "openai-responses"},
            {"AEONITH_PROVIDER_KIND": "openai-compatible"},
            {"AEONITH_PROVIDER_API_KEY": "synthetic-key"},
            {"AEONITH_PROVIDER_URL": "https://api.openai.com/v1/responses",
             "AEONITH_PROVIDER_API_KEY": "synthetic-key"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(is_ready({**ENV, **changes}))

    def test_local_fake_provider_workflow_remains_compatible_without_cloud_ledger(self):
        self.assertTrue(is_ready(ENV))
        provider = _construct_provider(ENV)
        self.assertEqual(provider.url, ENV["AEONITH_PROVIDER_URL"])
        self.assertIsNone(provider.api_key)
        status, result = run({"schema_version": "aeonith.review.v1", "work": "A",
                              "lenses": ["symbolic"]}, provider=CountingProvider())
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
