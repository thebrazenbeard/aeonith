"""The batch CLI must not leak private prose or select a remote model."""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from aeonith import book_cli


class FakeLocalProvider:
    calls = []
    constructions = []
    bad_at = None

    def __init__(self, **settings):
        self.timeout = settings["timeout"]
        self.settings = settings
        self.constructions.append(settings)

    def review(self, payload):
        text = payload["task"]["work"]["text"]
        self.calls.append(payload)
        quote = "NOT IN SOURCE" if len(self.calls) == self.bad_at else text[:12]
        return {
            "lens_reviews": [
                {
                    "lens": lens,
                    "analysis": "An unresolved consequence is shown.",
                    "basis": "textual",
                    "support": [{"source": "work", "quote": quote}],
                    "limitations": [],
                }
                for lens in payload["task"]["lenses"]
            ],
            "synthesis": "Only supplied words were reviewed.",
            "uncertainties": [],
        }


class BookCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = (
            "Canto I\nA door opened onto an empty room.\n"
            "Canto II\nSomeone waited for a voice that never came.\n"
        )
        self.input_path = self.root / "book.md"
        self.output_path = self.root / "review.json"
        self.input_path.write_text(self.source, encoding="utf-8")
        FakeLocalProvider.calls.clear()
        FakeLocalProvider.constructions.clear()
        FakeLocalProvider.bad_at = None

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
             patch("aeonith.book_cli.LocalOpenAICompatibleProvider", FakeLocalProvider):
            code = book_cli.main([
                "--input", str(self.input_path),
                "--output", str(self.output_path),
                *arguments,
            ])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_no_provider_is_honest_and_private(self):
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")
        self.assertNotIn("empty room", stderr)
        self.assertEqual(FakeLocalProvider.calls, [])
        result = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "provider_unavailable")
        self.assertEqual(result["attempted_segments"], 0)
        self.assertIsNone(result["whole_book_synthesis"])

    def test_one_lens_is_default_and_each_canto_is_reviewed(self):
        code, stdout, stderr = self.invoke(
            "--provider", "local-openai-compatible",
            "--url", "http://127.0.0.1:5001/v1/chat/completions",
            "--max-segments", "2",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertNotIn("empty room", stderr)
        result = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "segments_completed")
        self.assertEqual(result["completed_segments"], 2)
        self.assertEqual(result["completed_chars"], len(self.source))
        self.assertIsNone(result["whole_book_synthesis"])
        self.assertEqual(len(FakeLocalProvider.calls), 2)
        self.assertTrue(all(call["task"]["lenses"] == ["symbolic"]
                            for call in FakeLocalProvider.calls))
        self.assertTrue(all(entry["review"]["status"] == "completed"
                            for entry in result["reviews"]))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.output_path.stat().st_mode), 0o600)

    def test_existing_output_never_overwritten_or_invoked(self):
        self.output_path.write_text("DO NOT OVERWRITE", encoding="utf-8")
        code, stdout, stderr = self.invoke("--provider", "local-openai-compatible")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn(self.source, stderr)
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "DO NOT OVERWRITE")
        self.assertEqual(FakeLocalProvider.calls, [])

    def test_private_review_output_cannot_be_written_into_git_checkout(self):
        checkout = Path(book_cli.__file__).resolve().parents[1]
        unsafe_output = checkout / "private-review-must-not-appear.json"
        self.assertFalse(unsafe_output.exists())
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
             patch("aeonith.book_cli.LocalOpenAICompatibleProvider", FakeLocalProvider):
            code = book_cli.main([
                "--input", str(self.input_path), "--output", str(unsafe_output),
                "--provider", "local-openai-compatible",
            ])
        self.assertEqual(code, 2)
        self.assertFalse(unsafe_output.exists())
        self.assertEqual(FakeLocalProvider.calls, [])
        self.assertNotIn(self.source, stderr.getvalue())

    def test_bad_budget_and_duplicate_lenses_rejected_before_model(self):
        for arguments in (
            ("--max-segments", "1"),
            ("--chunk-chars", "12001"),
            ("--max-total-seconds", "0"),
            ("--max-output-tokens", "9000"),
            ("--lens", "symbolic", "--lens", "symbolic"),
        ):
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.invoke(
                    "--provider", "local-openai-compatible", *arguments
                )
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertNotIn(self.source, stderr)
                self.assertFalse(self.output_path.exists())
                self.assertEqual(FakeLocalProvider.calls, [])

    def test_checkpoint_excludes_private_prefix_and_marker(self):
        secret = "PRIVATE_PREFIX_SHOULD_NOT_REACH_MODEL"
        self.input_path.write_text(secret + "[ps]" + self.source, encoding="utf-8")
        code, stdout, stderr = self.invoke(
            "--provider", "local-openai-compatible", "--after-marker", "[ps]",
            "--max-segments", "2",
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertNotIn(secret, stderr)
        self.assertEqual("".join(call["task"]["work"]["text"]
                                 for call in FakeLocalProvider.calls), self.source)
        self.assertNotIn(secret, self.output_path.read_text(encoding="utf-8"))
        self.assertNotIn("[ps]", self.output_path.read_text(encoding="utf-8"))

    def test_missing_or_duplicate_checkpoint_fails_preflight(self):
        for source in ("No checkpoint", "One[ps]Two[ps]Three"):
            with self.subTest(source=source):
                self.input_path.write_text(source, encoding="utf-8")
                code, stdout, stderr = self.invoke(
                    "--after-marker", "[ps]", "--provider", "local-openai-compatible"
                )
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertNotIn(source, stderr)
                self.assertFalse(self.output_path.exists())
                self.assertEqual(FakeLocalProvider.calls, [])

    def test_invalid_model_output_reports_partial_without_leak(self):
        FakeLocalProvider.bad_at = 2
        code, stdout, stderr = self.invoke(
            "--provider", "local-openai-compatible", "--max-segments", "2"
        )
        self.assertEqual(code, 5)
        self.assertEqual(stdout, "")
        self.assertNotIn(self.source, stderr)
        result = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["completed_segments"], 1)
        self.assertEqual(result["attempted_segments"], 2)
        self.assertEqual(len(FakeLocalProvider.calls), 2)

    def test_local_provider_rejects_remote_url_before_output_reservation(self):
        # Exercise the real endpoint validator, not the mocked provider.
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = book_cli.main([
                "--input", str(self.input_path), "--output", str(self.output_path),
                "--provider", "local-openai-compatible",
                "--url", "https://example.org/v1/chat/completions",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn(self.source, stderr.getvalue())
        self.assertFalse(self.output_path.exists())

    def test_ambient_remote_provider_configuration_is_not_used(self):
        with patch.dict(os.environ, {
            "AEONITH_PROVIDER_URL": "https://example.org/v1/chat/completions",
            "AEONITH_PROVIDER_MODEL": "remote",
            "AEONITH_PROVIDER_API_KEY": "secret",
        }):
            code, _, stderr = self.invoke("--provider", "local-openai-compatible")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(FakeLocalProvider.constructions[0]["url"],
                         "http://127.0.0.1:5001/v1/chat/completions")
        self.assertEqual(FakeLocalProvider.constructions[0]["model"], "local")

    def test_deadline_expiry_prevents_another_local_call(self):
        local = FakeLocalProvider(timeout=45)
        with patch("aeonith.book_cli.time.monotonic", side_effect=[10.0, 12.0]):
            budget = book_cli._DeadlineProvider(local, 1)
            with self.assertRaises(TimeoutError):
                budget.review({"task": {"work": {"text": "no call"}}})
        self.assertEqual(FakeLocalProvider.calls, [])


if __name__ == "__main__":
    unittest.main()
