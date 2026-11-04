"""Static contract for the optional one-click Windows token recovery wrapper.

The wrapper is an operator convenience, never a bypass of Aeonith's bearer
authorization or a mechanism for enabling/changing the running service.
"""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "copy-aeonith-token-windows.cmd"
INDEX = ROOT / "public" / "index.html"


class WindowsTokenOneClickTests(unittest.TestCase):
    def test_token_field_explains_same_machine_recovery(self):
        """An operator must not assume a remote browser has VN1's clipboard."""
        page = INDEX.read_text(encoding="utf-8")
        self.assertIn('id="service-token"', page)
        self.assertIn('id="token-note"', page)
        self.assertIn("copy-aeonith-token-windows.cmd", page)
        self.assertIn("same Windows account", page)
        self.assertIn("clipboard stays on that Windows computer", page)
        self.assertIn("does not restart Aeonith", page)
        self.assertIn("Never put the token in a URL, chat, or screenshot", page)

    @unittest.skipUnless(os.name == "nt", "Windows cmd.exe contract")
    def test_one_click_recovers_with_empty_path_and_missing_token(self):
        """A broken PATH must not bypass the shipped PowerShell interpreter.

        An isolated LOCALAPPDATA has no Aeonith state, so this can assert the
        helper's own failure message without reading a real token or setting
        the operator's clipboard.
        """
        system_root = Path(os.environ["SystemRoot"])
        cmd = system_root / "System32" / "cmd.exe"
        with tempfile.TemporaryDirectory(prefix="aeonith-empty-token-") as state:
            environment = os.environ.copy()
            environment["PATH"] = ""
            environment["LOCALAPPDATA"] = state
            result = subprocess.run(
                [str(cmd), "/d", "/c", str(WRAPPER)],
                input="\n", capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
                env=environment, check=False,
            )
        self.assertEqual(result.returncode, 1)
        combined = result.stdout + result.stderr
        self.assertIn("No existing Aeonith token for this Windows user", combined)
        self.assertNotIn("is not recognized as an internal or external command", combined)

    def test_one_click_runs_only_checked_in_dpapi_recovery(self):
        source = WRAPPER.read_text(encoding="utf-8")
        attributes = (ROOT / "scripts" / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("copy-aeonith-token-windows.cmd text eol=crlf", attributes)
        self.assertIn("%~dp0copy-aeonith-token-windows.ps1", source)
        self.assertIn('%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', source)
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
