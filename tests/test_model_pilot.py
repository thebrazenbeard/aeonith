"""A model pilot must never mistake structural success for literary quality."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.model_pilot import CASES, run_pilot
from aeonith.private_output import PrivateOutputError


class GroundedFake:
    name = "fake_local"

    def __init__(self):
        self.calls = 0

    def review(self, payload):
        self.calls += 1
        task = payload["task"]
        quote = task["work"]["text"].split(" ")[0]
        return {
            "assessment": None,
            "lens_reviews": [
                {
                    "lens": lens,
                    "analysis": f"The opening word establishes a localized detail for {lens}.",
                    "basis": "textual",
                    "support": [{"source": "work", "quote": quote}],
                    "limitations": [],
                }
                for lens in task["lenses"]
            ],
            "synthesis": "The sentence leaves its central reversal open to competing readings.",
            "challenges": [],
            "uncertainties": ["A short source cannot establish the author's intention."],
        }


class RefusingFake:
    name = "fake_failed"

    def review(self, payload):
        raise RuntimeError("SECRET TOKEN private manuscript text")


class InvalidQuoteFake(GroundedFake):
    def review(self, payload):
        result = super().review(payload)
        result["lens_reviews"][0]["support"] = [
            {"source": "work", "quote": "A passage that never existed"}
        ]
        return result


class InsufficientFake(GroundedFake):
    def review(self, payload):
        result = super().review(payload)
        result["lens_reviews"][0] = {
            "lens": payload["task"]["lenses"][0],
            "analysis": "The source cannot establish a historical location.",
            "basis": "insufficient_text",
            "support": [],
            "limitations": ["No date or locale is provided."],
        }
        return result


class PilotTests(unittest.TestCase):
    def test_real_core_and_auditor_path_counts_every_attempt(self):
        provider = GroundedFake()
        report = run_pilot(provider, model="private-model-name", repeats=3,
                           lenses=("symbolic", "stylistic"), cases=(CASES[0],))
        self.assertEqual(provider.calls, 3)
        self.assertEqual(report["summary"], {
            "attempts": 3, "completed": 3, "structural_pass": 3,
            "structural_fail": 0, "provider_or_model_failures": 0,
        })
        self.assertEqual(report["semantic_quality"], "UNASSESSED")
        self.assertEqual(len(report["attempts"]), 3)
        for attempt in report["attempts"]:
            self.assertEqual(attempt["status"], "completed")
            self.assertEqual(attempt["structural_status"], "pass")
            self.assertEqual(attempt["quote_supported_lenses"], 2)
            self.assertEqual([v["lens"] for v in attempt["lens_outcomes"]],
                             ["symbolic", "stylistic"])
            self.assertGreaterEqual(attempt["elapsed_seconds"], 0)
        serialized = json.dumps(report)
        self.assertNotIn("private-model-name", serialized)
        self.assertNotIn(CASES[0]["text"], serialized)
        self.assertNotIn("The opening word establishes", serialized)

    def test_provider_failure_sanitized_and_all_attempts_preserved(self):
        report = run_pilot(RefusingFake(), model="local", repeats=2,
                           lenses=("symbolic",), cases=(CASES[0],))
        self.assertEqual(report["summary"]["attempts"], 2)
        self.assertEqual(report["summary"]["provider_or_model_failures"], 2)
        self.assertEqual([x["status"] for x in report["attempts"]],
                         ["provider_error", "provider_error"])
        self.assertNotIn("SECRET TOKEN", json.dumps(report))

    def test_fabricated_quotes_are_invalid_and_not_completed(self):
        report = run_pilot(InvalidQuoteFake(), model="local", repeats=1,
                           lenses=("symbolic",), cases=(CASES[0],))
        self.assertEqual(report["summary"]["completed"], 0)
        self.assertEqual(report["attempts"][0]["status"], "invalid_provider_output")
        self.assertEqual(report["attempts"][0]["quote_supported_lenses"], 0)

    def test_honest_insufficiency_is_not_fabricated_textual_support(self):
        report = run_pilot(InsufficientFake(), model="local", repeats=1,
                           lenses=("historical_cultural",), cases=(CASES[0],))
        self.assertEqual(report["summary"]["structural_pass"], 1)
        outcome = report["attempts"][0]["lens_outcomes"][0]
        self.assertEqual(outcome["basis"], "insufficient_text")
        self.assertEqual(outcome["work_quote_count"], 0)
        self.assertEqual(outcome["limitation_count"], 1)

    def test_reject_invalid_counts_and_lenses_without_provider_calls(self):
        provider = GroundedFake()
        for repeats, lenses in ((0, ("symbolic",)), (11, ("symbolic",)),
                                (1, ()), (1, ("invented",)),
                                (1, ("symbolic", "symbolic"))):
            with self.subTest(repeats=repeats, lenses=lenses):
                with self.assertRaises(ValueError):
                    run_pilot(provider, model="local", repeats=repeats,
                              lenses=lenses, cases=(CASES[0],))
        self.assertEqual(provider.calls, 0)

    def test_reject_unregistered_private_text_before_provider_use(self):
        provider = GroundedFake()
        private = {"id": "private", "title": "unshared", "text": "SECRET MANUSCRIPT"}
        with self.assertRaises(ValueError):
            run_pilot(provider, model="local", cases=(private,))
        self.assertEqual(provider.calls, 0)

    def test_cli_rejects_remote_endpoint_without_any_request(self):
        command = [sys.executable, "-m", "evaluation.model_pilot", "--model", "local",
                   "--url", "https://example.com/v1/chat/completions"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_help_and_exclusive_output_behavior(self):
        command = [sys.executable, "-m", "evaluation.model_pilot", "--help"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--repeats", result.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            from evaluation.model_pilot import write_report_exclusive

            path = Path(tmp) / "sanitized.json"
            if os.name == "nt":
                with self.assertRaisesRegex(PrivateOutputError, "Windows private output"):
                    write_report_exclusive(path, {"semantic_quality": "UNASSESSED"})
                self.assertFalse(path.exists())
                return
            write_report_exclusive(path, {"semantic_quality": "UNASSESSED"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"semantic_quality": "UNASSESSED"})
            with self.assertRaises(FileExistsError):
                write_report_exclusive(path, {"attempts": []})

    @unittest.skipUnless(os.name == "posix", "POSIX private reporter boundary")
    def test_report_rejects_git_checkout_and_symlink_parent_before_write(self):
        from evaluation.model_pilot import write_report_exclusive
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / "checkout"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            target = checkout / "private-report.json"
            with self.assertRaisesRegex(PrivateOutputError, "Git checkout"):
                write_report_exclusive(target, {"secret": "do-not-persist"})
            self.assertFalse(target.exists())
            linked = root / "linked"
            linked.symlink_to(root, target_is_directory=True)
            with self.assertRaises(OSError):
                write_report_exclusive(linked / "private-report.json", {"attempts": []})
            self.assertFalse((root / "private-report.json").exists())

    def test_cli_denies_unqualified_windows_output_before_model_call(self):
        from evaluation import model_pilot
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pilot.json"
            with patch("aeonith.private_output._is_windows", return_value=True), \
                 patch.object(model_pilot, "run_pilot", return_value={
                     "summary": {"attempts": 1, "structural_pass": 1},
                     "semantic_quality": "UNASSESSED",
                 }) as run, \
                 self.assertRaises(SystemExit) as raised:
                model_pilot.main(["--model", "local-tag", "--output", str(path)])
            self.assertEqual(raised.exception.code, 2)
            run.assert_not_called()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
