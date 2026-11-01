"""End-to-end offline tests for the one-command reader workflow."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aeonith.workflow import main


class FakeProvider:
    name = "local_fixture"
    constructions: list[dict] = []
    reviews: list[dict] = []

    def __init__(self, **kwargs):
        self.constructions.append(kwargs)

    def review(self, payload):
        self.reviews.append(payload)
        task = payload["task"]
        return {
            "lens_reviews": [
                {
                    "lens": lens,
                    "analysis": f"{lens} examines the text but is not an independent truth check.",
                    "basis": "textual",
                    "support": [{"source": "work", "quote": "sea"}],
                    "limitations": [],
                } for lens in task["lenses"]
            ],
            "synthesis": "A possible reading connects the sea to a changed perception.",
            "challenges": [],
            "uncertainties": ["A brief excerpt cannot settle the author's intentions."],
            "assessment": None,
        }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        FakeProvider.constructions.clear()
        FakeProvider.reviews.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manuscript = self.root / "draft.md"
        self.manuscript.write_text("Every dawn Mara looked at the 🌊 sea.", encoding="utf-8")

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--input", str(self.manuscript), *args])
        return code, out.getvalue(), err.getvalue()

    def test_no_provider_is_an_honest_readable_failure_and_no_network(self):
        with patch.dict(os.environ, {"AEONITH_PROVIDER_URL": "https://remote.example/v1/responses",
                                     "AEONITH_PROVIDER_MODEL": "ambient-model",
                                     "AEONITH_PROVIDER_API_KEY": "SYNTHETIC_DO_NOT_DISPLAY"}):
            code, output, error = self.invoke()
        self.assertEqual(code, 3)
        self.assertIn("No literary critique was generated", output)
        self.assertIn("provider_unavailable", output)
        self.assertNotIn("Every dawn", output)
        self.assertNotIn("SYNTHETIC_DO_NOT_DISPLAY", output + error)
        self.assertEqual(error, "")
        self.assertEqual(FakeProvider.reviews, [])

    def test_remote_provider_endpoint_rejected_before_invocation(self):
        code, output, error = self.invoke(
            "--provider", "local-openai-compatible",
            "--url", "https://remote.example/v1/chat/completions",
            "--model", "mock",
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("invalid manuscript or provider configuration", error)
        self.assertEqual(FakeProvider.constructions, [])

    def test_malformed_endpoint_reports_configuration_error_without_network(self):
        code, output, error = self.invoke(
            "--provider", "local-openai-compatible", "--url", "http://example.test/v1/chat/completions",
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("invalid manuscript or provider configuration", error)

    def test_explicit_local_provider_can_render(self):
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, output, error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions",
                "--model", "mock",
                "--title", "Wave", "--omit-temperature",
            )
        self.assertEqual(code, 0, error)
        self.assertIn("# Wave", output)
        self.assertIn("## Psychological", output)
        self.assertIn("## Overall synthesis", output)
        self.assertEqual(len(FakeProvider.reviews), 1)
        self.assertEqual(FakeProvider.reviews[0]["task"]["work"]["text"],
                         "Every dawn Mara looked at the 🌊 sea.")
        self.assertEqual(FakeProvider.constructions[0]["url"], "http://127.0.0.1:4242/v1/chat/completions")
        self.assertTrue(FakeProvider.constructions[0]["json_mode"])
        self.assertIsNone(FakeProvider.constructions[0]["temperature"])

    def test_opt_in_structured_mode_is_forwarded_to_provider(self):
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, _, error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions", "--model", "mock",
                "--structured-outputs",
            )
        self.assertEqual(code, 0, error)
        self.assertIs(FakeProvider.constructions[0]["structured_outputs"], True)

    def test_ambiguous_localhost_alias_is_rejected(self):
        code, output, error = self.invoke(
            "--provider", "local-openai-compatible",
            "--url", "http://localhost:4242/v1/chat/completions",
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("invalid manuscript or provider configuration", error)

    def test_ambient_remote_url_is_ignored_in_local_mode(self):
        with patch.dict(os.environ, {"AEONITH_PROVIDER_URL": "https://ambient.example/v1/responses",
                                     "AEONITH_PROVIDER_MODEL": "ambient-model"}), \
             patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, output, error = self.invoke("--provider", "local-openai-compatible")
        self.assertEqual(code, 0, error)
        self.assertIn("## Overall synthesis", output)
        self.assertEqual(FakeProvider.constructions[0]["url"], "http://127.0.0.1:5001/v1/chat/completions")
        self.assertEqual(FakeProvider.constructions[0]["model"], "local")

    def test_focus_lenses_are_passed_to_core_and_duplicate_lenses_rejected(self):
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, output, error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions",
                "--model", "local", "--lens", "symbolic", "--lens", "stylistic",
            )
        self.assertEqual(code, 0, error)
        self.assertEqual(FakeProvider.reviews[0]["task"]["lenses"], ["symbolic", "stylistic"])
        self.assertIn("## Symbolic", output)
        self.assertNotIn("## Psychological", output)
        FakeProvider.reviews.clear()
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            duplicate_code, _, duplicate_error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions",
                "--model", "local", "--lens", "symbolic", "--lens", "symbolic",
            )
        self.assertEqual(duplicate_code, 2)
        self.assertIn("invalid manuscript", duplicate_error)
        self.assertEqual(FakeProvider.reviews, [])

    def test_multiline_title_rejected_before_provider_invocation(self):
        for title in ("Good\n## Forged heading", "Good\u2028## Forged heading", "NUL\x00"):
            with self.subTest(title=repr(title)), patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
                code, output, error = self.invoke(
                    "--provider", "local-openai-compatible",
                    "--url", "http://127.0.0.1:4242/v1/chat/completions",
                    "--model", "local", "--title", title,
                )
            self.assertEqual(code, 2)
            self.assertEqual(output, "")
            self.assertNotIn("Forged heading", error)
            self.assertEqual(FakeProvider.reviews, [])

    def test_local_adapter_is_opt_in_and_json_report_is_machine_readable(self):
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, output, error = self.invoke(
                "--provider", "local-openai-compatible", "--format", "json",
                "--url", "http://127.0.0.1:4242/v1/chat/completions", "--model", "local",
            )
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["schema_version"], "aeonith.review.v1")
        self.assertTrue(FakeProvider.constructions[0]["json_mode"])

    def test_existing_output_file_never_overwritten_or_provider_invoked(self):
        output_path = self.root / "existing.md"
        output_path.write_text("DO NOT REPLACE", encoding="utf-8")
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, output, error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions",
                "--model", "local", "--output", str(output_path),
            )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertEqual(output_path.read_text(encoding="utf-8"), "DO NOT REPLACE")
        self.assertEqual(FakeProvider.reviews, [])
        self.assertIn("Could not reserve", error)

    def test_report_output_is_owner_only_on_posix(self):
        output_path = self.root / "review.md"
        code, output, error = self.invoke("--output", str(output_path))
        self.assertEqual(code, 3, error)
        self.assertEqual(output, "")
        self.assertIn("provider_unavailable", output_path.read_text(encoding="utf-8"))
        if os.name == "posix":
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

    def test_invalid_utf8_rejected_without_output_or_provider(self):
        self.manuscript.write_bytes(b"\xff\xfe")
        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", FakeProvider):
            code, output, error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions",
                "--model", "local",
            )
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertNotIn("Traceback", error)
        self.assertEqual(FakeProvider.reviews, [])

    def test_provider_failure_does_not_fabricate_criticism(self):
        class CrashingProvider(FakeProvider):
            def review(self, payload):
                raise RuntimeError("private manuscript and secret")

        with patch("aeonith.workflow.LocalOpenAICompatibleProvider", CrashingProvider):
            code, output, error = self.invoke(
                "--provider", "local-openai-compatible",
                "--url", "http://127.0.0.1:4242/v1/chat/completions",
                "--model", "local",
            )
        self.assertEqual(code, 4)
        self.assertIn("No literary critique was generated", output)
        self.assertNotIn("private manuscript", output + error)
        self.assertNotIn("secret", output + error)

    def test_module_cli_runs_offline_without_network(self):
        result = subprocess.run(
            [sys.executable, "-m", "aeonith.workflow", "--input", str(self.manuscript)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("No literary critique was generated", result.stdout)


if __name__ == "__main__":
    unittest.main()
