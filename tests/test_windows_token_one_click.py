"""Static contract for the optional one-click Windows token recovery wrapper.

The wrapper is an operator convenience, never a bypass of Aeonith's bearer
authorization or a mechanism for enabling/changing the running service.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "copy-aeonith-token-windows.cmd"


class WindowsTokenOneClickTests(unittest.TestCase):
    def test_one_click_runs_only_checked_in_dpapi_recovery(self):
        source = WRAPPER.read_text(encoding="utf-8")
        attributes = (ROOT / "scripts" / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("copy-aeonith-token-windows.cmd text eol=crlf", attributes)
        self.assertIn("%~dp0copy-aeonith-token-windows.ps1", source)
        self.assertIn("powershell.exe", source.lower())
        self.assertIn("-NoProfile", source)
        self.assertIn("-ExecutionPolicy Bypass", source)
        self.assertIn("-File", source)
        self.assertNotIn("-Command", source)

    def test_quick_access_does_not_expose_token_or_change_services(self):
        source = WRAPPER.read_text(encoding="utf-8").lower()
        for forbidden in (
            "token.dpapi", "authorization:", "bearer ", "curl", "invoke-restmethod",
            "start-aeonith-windows.ps1", "stop-aeonith-windows.ps1", "set-clipboard",
            "https://", "http://", "tailscale", "ollama", "git clone",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
