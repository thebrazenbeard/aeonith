"""CLI and endpoint boundary checks requiring no model credentials or network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from aeonith.providers import LocalOpenAICompatibleProvider


def run_cli(raw: str, env: dict | None = None, *, cli_args: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "aeonith", "review", "--input", "-", *cli_args],
        input=raw,
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
        timeout=10,
        check=False,
    )


class CliBoundaryTests(unittest.TestCase):
    def test_no_provider_returns_machine_readable_nonzero_status(self) -> None:
        payload = {"schema_version": "aeonith.review.v1", "work": {"text": "The bell rang twice."}}
        completed = run_cli(json.dumps(payload))
        self.assertEqual(3, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("provider_unavailable", result["status"])
        self.assertIsNone(result["assessment"])

    def test_malformed_json_is_controlled_invalid_request(self) -> None:
        completed = run_cli('{"schema_version": "aeonith.review.v1", bad}')
        self.assertEqual(2, completed.returncode, completed.stderr)
        self.assertEqual("invalid_request", json.loads(completed.stdout)["status"])
        self.assertNotIn("Traceback", completed.stderr)

    def test_environment_url_does_not_auto_enable_provider(self) -> None:
        payload = {"schema_version": "aeonith.review.v1", "work": {"text": "I left the gate open."}}
        completed = run_cli(json.dumps(payload), {"AEONITH_PROVIDER_URL": "https://invalid.example.test/v1/chat/completions"})
        self.assertEqual(3, completed.returncode, completed.stderr)
        self.assertEqual("provider_unavailable", json.loads(completed.stdout)["status"])

    def test_paid_provider_modes_and_credentials_flags_do_not_exist(self) -> None:
        payload = json.dumps({"schema_version": "aeonith.review.v1", "work": {"text": "A tide turned."}})
        for options in (
            ("--provider", "openai-responses"),
            ("--provider", "openai-compatible"),
            ("--provider", "local-openai-compatible", "--api-key-env", "PAID_KEY"),
            ("--provider", "local-openai-compatible", "--allow-external-disclosure"),
        ):
            with self.subTest(options=options):
                completed = run_cli(payload, cli_args=options)
                self.assertEqual(2, completed.returncode)
                self.assertEqual("", completed.stdout)
                self.assertIn("error:", completed.stderr)

    def test_local_mode_blocks_remote_endpoint_without_connecting(self) -> None:
        payload = json.dumps({"schema_version": "aeonith.review.v1", "work": {"text": "A tide turned."}})
        completed = run_cli(payload, cli_args=(
            "--provider", "local-openai-compatible",
            "--url", "https://api.openai.com/v1/chat/completions",
        ))
        self.assertEqual(2, completed.returncode, completed.stderr)
        self.assertEqual("invalid_request", json.loads(completed.stdout)["status"])

    def test_ambient_paid_url_never_overrides_local_default(self) -> None:
        # An invalid flag should be rejected before network transport even if
        # a formerly configured paid URL remains in the user's environment.
        payload = json.dumps({"schema_version": "aeonith.review.v1", "work": {"text": "A tide turned."}})
        completed = run_cli(payload, {"AEONITH_PROVIDER_URL": "https://api.openai.com/v1/chat/completions"},
                            cli_args=("--provider", "local-openai-compatible", "--max-output-tokens", "0"))
        self.assertEqual(2, completed.returncode)
        self.assertEqual("invalid_request", json.loads(completed.stdout)["status"])


class ProviderConfigurationTests(unittest.TestCase):
    def test_rejects_nonlocal_plain_http_even_without_key(self) -> None:
        with self.assertRaises(ValueError):
            LocalOpenAICompatibleProvider(url="http://example.com/v1/chat/completions", model="critic")

    def test_rejects_plain_http_localhost_with_credentials(self) -> None:
        with self.assertRaises(ValueError):
            LocalOpenAICompatibleProvider(url="http://127.0.0.1:9999/v1/chat/completions", model="critic", api_key="test-secret")

    def test_accepts_unauthed_loopback_without_connecting(self) -> None:
        provider = LocalOpenAICompatibleProvider(url="http://127.0.0.1:9999/v1/chat/completions", model="critic")
        self.assertEqual("critic", provider.model)

    def test_rejects_url_embedded_credentials(self) -> None:
        with self.assertRaises(ValueError):
            LocalOpenAICompatibleProvider(url="http://someone:secret@127.0.0.1:9999/v1/chat/completions", model="critic")

    def test_rejects_unsupported_scheme(self) -> None:
        with self.assertRaises(ValueError):
            LocalOpenAICompatibleProvider(url="file:///etc/passwd", model="critic")

    def test_rejects_unbounded_resource_parameters(self) -> None:
        with self.assertRaises(ValueError):
            LocalOpenAICompatibleProvider(url="http://127.0.0.1:9999/v1/chat/completions", model="critic", max_tokens=100_000)
        with self.assertRaises(ValueError):
            LocalOpenAICompatibleProvider(url="http://127.0.0.1:9999/v1/chat/completions", model="critic", timeout=0)


if __name__ == "__main__":
    unittest.main()
