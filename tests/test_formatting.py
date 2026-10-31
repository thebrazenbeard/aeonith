"""Presentation contract tests, intentionally without network or model calls."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "aeonith" / "formatting.py"
SPEC = importlib.util.spec_from_file_location("aeonith_isolated_formatting", MODULE_PATH)
assert SPEC and SPEC.loader
formatting = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formatting)


def sample_result() -> dict:
    return {
        "schema_version": "aeonith.review.v1",
        "status": "completed",
        "lens_reviews": [
            {
                "lens": "stylistic",
                "analysis": "The repeated beat accelerates the passage.",
                "basis": "textual",
                "support": [{"source": "work", "quote": "The bell rang."}],
                "limitations": [],
            },
            {
                "lens": "comparative",
                "analysis": "An influence claim cannot be established from this excerpt.",
                "basis": "insufficient_text",
                "support": [],
                "limitations": ["No comparative corpus is supplied."],
            },
        ],
        "synthesis": "Rhythm makes the scene urgent; further context is needed.",
        "challenges": [{"text": "Could the bell be reassuring?", "support": []}],
        "uncertainties": ["The speaker is unspecified."],
        "evidence_audit": [{"claim_id": "source-A", "status": "provided_unverified"}],
        "assessment": None,
    }


class ReviewFormattingTests(unittest.TestCase):
    def test_renders_lenses_evidence_synthesis_and_limitations(self) -> None:
        markdown = formatting.render_review_markdown(sample_result(), title="Bell Story")
        self.assertTrue(markdown.startswith("# Bell Story\n"))
        self.assertIn("## Stylistic", markdown)
        self.assertIn("Submitted text: “The bell rang.”", markdown)
        self.assertIn("## Comparative", markdown)
        self.assertIn("*Insufficient textual basis", markdown)
        self.assertIn("No comparative corpus is supplied.", markdown)
        self.assertIn("## Overall synthesis", markdown)
        self.assertIn("## Questions and counterreadings", markdown)
        self.assertIn("## Uncertainties", markdown)
        self.assertIn("`provided_unverified`", markdown)
        self.assertIn("not independently verified", markdown)

    def test_provider_failure_does_not_fabricate_critique(self) -> None:
        payload = {
            "schema_version": "aeonith.review.v1",
            "status": "provider_unavailable",
            "error": {"code": "provider_unavailable"},
        }
        markdown = formatting.render_review_markdown(payload)
        self.assertIn("No literary critique was generated", markdown)
        self.assertIn("Status: `provider_unavailable`", markdown)
        self.assertNotIn("Overall synthesis", markdown)
        self.assertNotIn("## Stylistic", markdown)
        completed = self._run_cli(json.dumps(payload))
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, markdown)

    def test_escapes_raw_markdown_and_html(self) -> None:
        payload = sample_result()
        payload["lens_reviews"][0]["analysis"] = (
            "<script>alert(1)</script>\n![unsafe](javascript:alert(1))\n# Fake heading\n1. Ordered injection"
            "\n---\n~~strike~~ $math$"
        )
        output = formatting.render_review_markdown(payload, title="<img src=x>")
        self.assertIn("&lt;img src=x&gt;", output)
        self.assertIn("&lt;script&gt;", output)
        self.assertNotIn("<script>", output)
        self.assertIn(r"\!\[unsafe\]\(javascript:alert\(1\)\)", output)
        self.assertIn(r"\# Fake heading", output)
        self.assertIn(r"1\. Ordered injection", output)
        self.assertIn(r"\---", output)
        self.assertIn(r"\~\~strike\~\~ \$math\$", output)

    def test_strips_terminal_and_bidi_controls(self) -> None:
        payload = sample_result()
        payload["lens_reviews"][0]["analysis"] = "Visible\x1b[31m red \x1b[0m\u202e reversal"
        output = formatting.render_review_markdown(payload)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\u202e", output)
        self.assertIn("Visible", output)

    def test_rejects_unsupported_lens_and_duplicates(self) -> None:
        for bad_lens in ("invented", "stylistic"):
            payload = sample_result()
            payload["lens_reviews"][1]["lens"] = bad_lens
            with self.subTest(lens=bad_lens), self.assertRaises(formatting.InvalidReview):
                formatting.render_review_markdown(payload)

    def test_rejects_missing_support_or_limitation(self) -> None:
        payload = sample_result()
        payload["lens_reviews"][0]["support"] = []
        with self.assertRaises(formatting.InvalidReview):
            formatting.render_review_markdown(payload)
        payload = sample_result()
        payload["lens_reviews"][1]["limitations"] = []
        with self.assertRaises(formatting.InvalidReview):
            formatting.render_review_markdown(payload)

    def test_provisional_assessment_is_explicitly_nonformal(self) -> None:
        payload = sample_result()
        payload["assessment"] = "SURVIVES"
        output = formatting.render_review_markdown(payload)
        self.assertIn("## Provisional proposition assessment", output)
        self.assertIn("not formal verification", output)

    def test_cli_stdin(self) -> None:
        completed = self._run_cli(json.dumps(sample_result()))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("## Overall synthesis", completed.stdout)
        self.assertEqual(completed.stderr, "")

    def test_cli_rejects_invalid_or_huge_json_without_traceback(self) -> None:
        for bad_input in (
            '{"x":1,"x":2}',
            '{"x":NaN}',
            '{"x":1e309}',
            "a" * (formatting.MAX_INPUT_BYTES + 1),
        ):
            with self.subTest(case=bad_input[:25]):
                completed = self._run_cli(bad_input)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertNotIn("Traceback", completed.stderr)

    def test_input_is_not_mutated(self) -> None:
        payload = sample_result()
        before = copy.deepcopy(payload)
        formatting.render_review_markdown(payload)
        self.assertEqual(payload, before)

    @staticmethod
    def _run_cli(raw: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(MODULE_PATH), "--input", "-"],
            input=raw,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
