"""Plain manuscript request creation tests without third-party dependencies."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "aeonith" / "text_input.py"
SPEC = importlib.util.spec_from_file_location("aeonith_isolated_text_input", MODULE_PATH)
assert SPEC and SPEC.loader
text_input = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(text_input)


class TextInputTests(unittest.TestCase):
    def test_request_matches_minimal_work_contract(self) -> None:
        expected_text = "The bell rang.\nNobody answered."
        self.assertEqual(
            text_input.make_request(expected_text, title="Bell Story"),
            {"schema_version": "aeonith.review.v1", "work": {"title": "Bell Story", "text": expected_text}},
        )

    def test_preserves_unicode_and_newlines_via_stdin(self) -> None:
        submitted = "Écho\nA bell…\n"
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--input", "-", "--title", "L’écho"],
            input=submitted,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        obj = json.loads(completed.stdout)
        self.assertEqual(obj["work"]["text"], submitted)
        self.assertEqual(obj["work"]["title"], "L’écho")

    def test_rejects_empty_nul_or_oversized_manuscript(self) -> None:
        for manuscript in ("", "   ", "one\x00two", "a" * (text_input.MAX_TEXT_CHARS + 1)):
            with self.subTest(length=len(manuscript)), self.assertRaises(text_input.TextInputError):
                text_input.make_request(manuscript)

    def test_rejects_title_longer_than_core_accepts(self) -> None:
        with self.assertRaises(text_input.TextInputError):
            text_input.make_request("hello", title="x" * 501)

    def test_rejects_non_utf8_without_leaking_content(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--input", "-"],
            input=b"\xffprivate manuscript bytes",
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, b"")
        self.assertNotIn(b"private manuscript", completed.stderr)

    def test_cli_input_over_limit_is_rejected(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--input", "-"],
            input=b"a" * (text_input.MAX_MANUSCRIPT_BYTES + 1),
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, b"")


if __name__ == "__main__":
    unittest.main()
