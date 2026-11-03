"""Static safety guardrails for the optional Windows operator scripts.

The tests neither need PowerShell nor touch Tailscale, credentials, devices,
local models, or billable services. Real host tests remain mandatory.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
START = (ROOT / "scripts" / "start-aeonith-windows.ps1").read_text(encoding="utf-8")
STOP = (ROOT / "scripts" / "stop-aeonith-windows.ps1").read_text(encoding="utf-8")
COPY = (ROOT / "scripts" / "copy-aeonith-token-windows.ps1").read_text(encoding="utf-8") if (ROOT / "scripts" / "copy-aeonith-token-windows.ps1").exists() else ""


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

    def test_token_recovery_does_not_require_restarting_or_reconfiguring_service(self):
        self.assertIn("Join-Path $env:LOCALAPPDATA 'Aeonith'", COPY)
        self.assertIn("'token.dpapi'", COPY)
        self.assertIn("ConvertTo-SecureString", COPY)
        self.assertIn("SecureStringToBSTR", COPY)
        self.assertIn("ZeroFreeBSTR", COPY)
        self.assertIn("Set-Clipboard -Value $token", COPY)
        for forbidden in ("Start-Process", "Stop-Process", "Set-Content", "Invoke-RestMethod", "Write-Output $token", "tailscale", "ollama", "python.exe"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, COPY)

    def test_model_is_literal_loopback_and_preinstalled(self):
        self.assertIn("Get-Command ollama.exe", START)
        self.assertIn("$ollama list", START)
        self.assertIn("127.0.0.1:11434/v1/chat/completions", START)
        self.assertIn("AEONITH_MAX_LENSES = '1'", START)
        self.assertIn("AEONITH_PROVIDER_TIMEOUT_SECONDS = '50'", START)
        self.assertIn("$keepAlive = '24h'", START)
        self.assertIn("'http://127.0.0.1:11434/api/generate'", START)
        self.assertIn("' is in use; refusing to interrupt another service.'", START)

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
        for source in (START, STOP, COPY):
            with self.subTest(source=source[:80]):
                self.assertNotIn("tailscale funnel --", source.lower())
                self.assertNotIn("tailscale funnel reset", source.lower())
                self.assertNotIn("ollama pull", source.lower())
                self.assertNotIn("api.openai.com", source.lower())
                self.assertNotIn("SetEnvironmentVariable($name, $settings[$name], 'Machine')", source)

    def test_opt_in_critic_profile_uses_pilot_settings_without_legacy_change(self):
        self.assertIn("[ValidateSet('legacy', 'aeonith-critic')]", START)
        self.assertIn("[Alias('Profile')]", START)
        self.assertIn("[string]$ModelProfile = 'legacy'", START)
        self.assertIn("$Model = 'aeonith-critic:0.1'", START)
        self.assertIn("AEONITH_MAX_OUTPUT_TOKENS = '800'", START)
        self.assertIn("AEONITH_STRUCTURED_OUTPUTS = 'false'", START)
        self.assertIn("$settings['AEONITH_MAX_OUTPUT_TOKENS'] = '2048'", START)
        self.assertIn("$settings['AEONITH_STRUCTURED_OUTPUTS'] = 'true'", START)
        self.assertIn("$settings['AEONITH_LOCAL_JSON_MODE'] = 'false'", START)
        self.assertIn("$previous.Profile -ne $ModelProfile", START)
        self.assertIn("[string]$previous.Profile", START)
        self.assertIn("$keepAlive = '5m'", START)

    def test_legacy_profile_is_explicitly_warned_not_silently_upgraded(self):
        self.assertIn("[string]$ModelProfile = 'legacy'", START)
        self.assertIn("Write-Warning ('Legacy profile selected", START)
        self.assertIn("The literary-critic structural pilot used -ModelProfile aeonith-critic", START)
        self.assertIn("No model is downloaded.", START)
        # The status must make model/profile differences visible even when
        # an already-owned listener is reused without restarting it.
        self.assertIn("', profile ' + $ModelProfile + ', model ' + $Model", START)

    def test_alternate_loopback_port_is_checked_and_owned_on_stop(self):
        self.assertIn('[ValidateRange(1024, 65535)]', START)
        self.assertIn('[int]$Port = 8765', START)
        self.assertIn('Port = $Port', START)
        self.assertIn("'--port',([string]$Port)", START)
        self.assertIn("'http://127.0.0.1:' + $Port + '/healthz'", START)
        self.assertIn('FunnelOrigin -and $Port -ne 8765', START)
        self.assertIn('if ($previous.Port -ne $Port)', START)
        self.assertIn('[int]::TryParse(([string]$saved.Port)', STOP)
        self.assertIsNotNone(re.search(r'CommandLine.*?--port', STOP, re.S))

    def test_explicit_and_path_python_require_verified_local_executable(self):
        self.assertIn('[string]$PythonExe', START)
        self.assertIn('Test-Path -LiteralPath $candidate -PathType Leaf', START)
        self.assertIn('IsPathRooted($candidate)', START)
        self.assertIn('DriveType', START)
        self.assertIn('Fixed', START)
        self.assertIn('sys.version_info', START)
        self.assertIn('Python 3.11+', START)


if __name__ == "__main__":
    unittest.main()
