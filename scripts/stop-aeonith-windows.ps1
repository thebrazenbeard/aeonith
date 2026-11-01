# Stops ONLY the Aeonith process recorded by start-aeonith-windows.ps1.
# It does not reset Tailscale, stop Ollama, or affect other local services.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
$statePath = Join-Path (Join-Path $env:LOCALAPPDATA 'Aeonith') 'deployment.json'
if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Output 'No Aeonith process is registered. Nothing stopped.'
    return
}
$saved = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($saved.Port -ne 8765 -or -not $saved.ProcessId -or -not $saved.StartedUtc -or -not $saved.PythonPath) {
    throw 'Deployment state is incomplete. Refusing process termination.'
}
$target = Get-Process -Id ([int]$saved.ProcessId) -ErrorAction SilentlyContinue
if ($null -eq $target) {
    Write-Output 'Recorded Aeonith process is already stopped. Preserving state for inspection.'
    return
}
try {
    $sameProcess = ($target.StartTime.ToUniversalTime().ToString('o') -eq $saved.StartedUtc -and
        $target.Path -ieq $saved.PythonPath)
} catch { $sameProcess = $false }
if (-not $sameProcess) {
    throw 'Recorded PID belongs to an unexpected process. Nothing was terminated.'
}
$actual = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $target.Id) -ErrorAction Stop
if ($actual.CommandLine -notmatch '(?i)(?:^|\s)-m\s+aeonith\.local_server(?:\s|$)' -or
        $actual.CommandLine -notmatch '(?i)--port\s+8765(?:\s|$)') {
    throw 'Command-line identity is not Aeonith port 8765. Nothing was terminated.'
}
Stop-Process -Id $target.Id -ErrorAction Stop
try { Wait-Process -Id $target.Id -Timeout 10 -ErrorAction SilentlyContinue } catch { }
if (Get-Process -Id $target.Id -ErrorAction SilentlyContinue) {
    throw 'Process still running. Preserving deployment record.'
}
Remove-Item -LiteralPath $statePath -ErrorAction Stop
Write-Output 'Owned Aeonith process stopped. Ollama and all unrelated services are untouched.'
Write-Output 'IMPORTANT: If Funnel is enabled, turn off ONLY its Aeonith listener separately.'
