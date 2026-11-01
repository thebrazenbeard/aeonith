"""Static safety guardrails for the optional Windows operator scripts.

The tests neither need PowerShell nor touch Tailscale, credentials, devices,
local models, or billable services. Real host tests remain mandatory.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
START = (ROOT / "scripts" / "start-aeonith-windows.ps1").read_text(encoding="utf-8")
STOP = (ROOT / "scripts" / "stop-aeonith-windows.ps1").read_text(encoding="utf-8")


class WindowsLauncherPolicyTests(unittest.TestCase):
    def test_token_is_dpapi_encrypted_outside_repository_and_never_echoed(self):
        self.assertIn("Join-Path $env:LOCALAPPDATA 'Aeonith'", START)
        self.assertIn("'token.dpapi'", START)
        self.assertIn("ConvertFrom-SecureString", START)
        self.assertIn("ConvertTo-SecureString", START)
        self.assertIn("SecureStringToBSTR", START)
        self.assertIn("ZeroFreeBSTR", START)
        self.assertIn("CopyTokenToClipboard", START)
        self.assertNotIn("Write-Output $token", START)

    def test_model_is_literal_loopback_and_preinstalled(self):
        self.assertIn("Get-Command ollama.exe", START)
        self.assertIn("$ollama list", START)
        self.assertIn("127.0.0.1:11434/v1/chat/completions", START)
        self.assertIn("AEONITH_MAX_LENSES = '1'", START)
        self.assertIn("AEONITH_PROVIDER_TIMEOUT_SECONDS = '50'", START)
        self.assertIn("Port 8765 is in use", START)

    def test_public_origin_is_explicit_and_listener_stays_loopback(self):
        self.assertIn("from aeonith.local_server import _funnel_host", START)
        self.assertIn("AEONITH_FUNNEL_ORIGIN = $FunnelOrigin", START)
        self.assertIn("'127.0.0.1'", START)
        self.assertNotIn("0.0.0.0", START)

    def test_stop_checks_pid_start_time_path_and_command_before_kill(self):
        for marker in ("StartedUtc", "PythonPath", "ProcessId",
                       "Get-CimInstance Win32_Process", "CommandLine",
                       "Stop-Process -Id $target.Id"):
            with self.subTest(marker=marker):
                self.assertIn(marker, STOP)
        self.assertNotIn("Stop-Process -Name", STOP)

    def test_scripts_do_not_change_tailscale_or_billing(self):
        for source in (START, STOP):
            with self.subTest(source=source[:80]):
                self.assertNotIn("tailscale funnel --", source.lower())
                self.assertNotIn("tailscale funnel reset", source.lower())
                self.assertNotIn("ollama pull", source.lower())
                self.assertNotIn("api.openai.com", source.lower())
                self.assertNotIn("SetEnvironmentVariable($name, $settings[$name], 'Machine')", source)


if __name__ == "__main__":
    unittest.main()
