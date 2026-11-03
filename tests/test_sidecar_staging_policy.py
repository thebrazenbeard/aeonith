"""Source contract for the optional, private Windows sidecar qualifier.

This does not claim a live VN1 test; the script must be reviewed before use.
"""

from pathlib import Path
import re
import unittest

from aeonith.core import critique


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qualify-aeonith-sidecar-windows.ps1"


class SidecarStagingPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_exact_checkout_and_loopback_port(self):
        self.assertIn("[Parameter(Mandatory = $true)][string]$ExpectedHead", self.source)
        self.assertIn("[int]$Port = 8766", self.source)
        self.assertIn("if ($Port -ne 8766)", self.source)
        self.assertIn("[string]::IsNullOrWhiteSpace($primaryBefore)", self.source)
        self.assertIn("127.0.0.1", self.source)
        self.assertIn("git", self.source)
        self.assertIn("rev-parse", self.source)
        self.assertIn("--untracked-files=all", self.source)
        self.assertIn("--ignored=matching", self.source)

    def test_separate_ephemeral_token_and_no_persistent_state(self):
        self.assertIn("RandomNumberGenerator", self.source)
        self.assertIn("AEONITH_SERVICE_TOKEN", self.source)
        self.assertIn("'AEONITH_MODEL_PROFILE' = 'aeonith-critic'", self.source)
        self.assertIn("& $python -E -B -S -c", self.source)
        self.assertIn("'-E', '-B', '-S', '-m'", self.source)
        self.assertNotIn("'PYTHONPATH'", self.source)
        self.assertIn("Start-Process", self.source)
        for forbidden in ("deployment.json", "token.dpapi", "CopyTokenToClipboard",
                          "Start-Aeonith-Windows", "Stop-Aeonith-Windows", "tailscale",
                          "-FunnelOrigin", "-RedirectStandardOutput", "-RedirectStandardError"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), self.source.lower())

    def test_pid_and_listener_custody_and_cleanup(self):
        for required in ("Get-NetTCPConnection", "Get-CimInstance", "Get-Process",
                         ".Kill()", ".WaitForExit(", "finally", "OwnedProcess", "StartTime",
                         "-State Listen", "-LocalPort $Port"):
            with self.subTest(required=required):
                self.assertIn(required, self.source)
        self.assertNotIn("Stop-Process", self.source)

    def test_only_sanitized_receipt_not_prose(self):
        self.assertIn("ConvertTo-Json", self.source)
        self.assertIn("quote_supported_lenses", self.source)
        self.assertIn("structural_status", self.source)
        self.assertIn("$result.lens_reviews", self.source)
        self.assertIn("$_.source -eq 'work'", self.source)
        self.assertIn("$receipt.quote_supported_lenses -ge 1", self.source)
        self.assertNotIn("work_quote", self.source)
        self.assertNotRegex(self.source, re.compile(r"Write-(Host|Output)\s+\$result\b", re.I))
        self.assertNotIn("Write-Output $token", self.source)

    def test_actual_core_result_uses_work_anchored_support(self):
        class SyntheticGroundedProvider:
            name = "sidecar_test_double"

            def review(self, payload):
                return {
                    "lens_reviews": [{
                        "lens": "symbolic",
                        "analysis": "The mirror contrasts prediction with memory.",
                        "basis": "textual",
                        "support": [{"source": "work", "quote": "yesterday's rain"}],
                        "limitations": [],
                    }],
                    "synthesis": "The synthetic mirror foregrounds unreliable time.",
                }

        result = critique({
            "schema_version": "aeonith.review.v1",
            "work": {"text": "The glass held yesterday's rain."},
            "lenses": ["symbolic"],
        }, SyntheticGroundedProvider())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["lens_reviews"][0]["support"], [
            {"source": "work", "quote": "yesterday's rain"},
        ])


if __name__ == "__main__":
    unittest.main()
