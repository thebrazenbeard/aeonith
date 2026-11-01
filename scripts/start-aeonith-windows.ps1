# Starts only Aeonith's loopback web service. Does NOT enable Tailscale Funnel.
# Requires Windows PowerShell 5.1+, Python 3.11+, and an EXISTING local Ollama
# installation with the named model. No downloads, paid APIs, or remote models.
[CmdletBinding()]
param(
    [string]$FunnelOrigin = '',
    [string]$Model = 'qwen2.5-coder:1.5b-instruct-q3_K_M',
    [switch]$CopyTokenToClipboard
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows-only DPAPI launcher.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$stateDir = Join-Path $env:LOCALAPPDATA 'Aeonith'
$statePath = Join-Path $stateDir 'deployment.json'
$tokenPath = Join-Path $stateDir 'token.dpapi'
$port = 8765
$python = (Get-Command python.exe -CommandType Application -ErrorAction Stop).Source
$ollama = (Get-Command ollama.exe -CommandType Application -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'aeonith\local_server.py'))) {
    throw 'Run this script from the Aeonith source checkout.'
}

# The only supported public host is an EXACT operator-supplied .ts.net origin.
# Validate using the same Python parser that will enforce incoming requests.
if ($FunnelOrigin) {
    Push-Location $repoRoot
    try {
        & $python -c 'import sys; from aeonith.local_server import _funnel_host; assert _funnel_host(sys.argv[1])' $FunnelOrigin
        if ($LASTEXITCODE -ne 0) { throw 'Invalid Funnel origin; refusing to start.' }
    } finally { Pop-Location }
}

function Test-AeonithIdentity($deployment) {
    if ($null -eq $deployment -or $deployment.Port -ne 8765) { return $false }
    $process = Get-Process -Id ([int]$deployment.ProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    try {
        $actualStart = $process.StartTime.ToUniversalTime().ToString('o')
        $actualPath = $process.Path
    } catch { return $false }
    return ($actualStart -eq $deployment.StartedUtc -and
            $actualPath -ieq $deployment.PythonPath)
}

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (Test-AeonithIdentity $previous) {
        if ($previous.FunnelOrigin -ne $FunnelOrigin) {
            throw 'Aeonith is already running with a different origin; stop it explicitly first.'
        }
        $currentListener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq [int]$previous.ProcessId -and $_.LocalAddress -eq '127.0.0.1' }
        if ($null -eq $currentListener) {
            throw 'Recorded Aeonith process is not serving the owned loopback port.'
        }
        Write-Output ('Aeonith already running on 127.0.0.1:8765 (PID ' + $previous.ProcessId + ').')
        if (-not $CopyTokenToClipboard) { return }
    } elseif (Get-Process -Id ([int]$previous.ProcessId) -ErrorAction SilentlyContinue) {
        throw 'Saved Aeonith PID now belongs to another process. Refusing to replace state.'
    } else {
        # Preserve a stale record for diagnosis instead of deleting it.
        Move-Item -LiteralPath $statePath -Destination ($statePath + '.stale-' + [guid]::NewGuid().ToString('N'))
    }
}

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $tokenPath)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $newToken = [Convert]::ToBase64String($bytes)
    $protectedToken = ConvertTo-SecureString -String $newToken -AsPlainText -Force |
        ConvertFrom-SecureString
    Set-Content -LiteralPath $tokenPath -Value $protectedToken -Encoding ASCII -NoNewline
    $newToken = $null
}

# Windows DPAPI: decryption is bound to this user profile, not a machine-wide
# plaintext secret. Never print the token, include it in argv, or commit it.
$secret = Get-Content -LiteralPath $tokenPath -Raw -Encoding ASCII | ConvertTo-SecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
if ($token.Length -lt 32 -or -not $token.IsNormalized()) {
    throw 'The protected service token is invalid.'
}
if ($CopyTokenToClipboard) {
    Set-Clipboard -Value $token
    Write-Output 'Token copied to the local clipboard. Paste into Aeonith, then clear clipboard history.'
}
if (Test-AeonithIdentity $previous) { $token = $null; return }

# Never start a local model download. Require the exact already-installed
# model name and an active loopback OpenAI-compatible Ollama endpoint.
$names = @(& $ollama list | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
if ($LASTEXITCODE -ne 0 -or $names -notcontains $Model) {
    throw 'The selected model is not installed locally. No download attempted.'
}
Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 4 | Out-Null
$occupied = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
if ($occupied.Count -gt 0) { throw 'Port 8765 is in use; refusing to interrupt another service.' }

# Ollama unloads idle models after five minutes by default, which can make a
# cold CPU inference exceed the app's bounded 50-second timeout. Preload only
# the already-installed model, with no user content or generated text, and
# keep it resident for 24 hours. This uses existing local RAM, not a paid API.
$warmPayload = @{ model = $Model; keep_alive = '24h'; stream = $false } | ConvertTo-Json
$warmResult = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' `
    -Method Post -ContentType 'application/json' -Body $warmPayload -TimeoutSec 90
if ($warmResult.done -ne $true) {
    throw 'Ollama did not confirm model preload; Aeonith was not started.'
}

$settings = @{
    AEONITH_SERVICE_TOKEN = $token
    AEONITH_PROVIDER_KIND = 'local-openai-compatible'
    AEONITH_PROVIDER_URL = 'http://127.0.0.1:11434/v1/chat/completions'
    AEONITH_PROVIDER_MODEL = $Model
    AEONITH_ENABLE_LIVE_REVIEWS = 'true'
    AEONITH_FUNNEL_ORIGIN = $FunnelOrigin
    AEONITH_MAX_LENSES = '1'
    AEONITH_MAX_OUTPUT_TOKENS = '800'
    AEONITH_PROVIDER_TIMEOUT_SECONDS = '50'
    AEONITH_LOCAL_JSON_MODE = 'true'
    AEONITH_STRUCTURED_OUTPUTS = 'false'
}
# Hosted provider and billing-era credentials are forbidden, even if inherited
# from the operator's interactive PowerShell session.
$blocked = @('AEONITH_PROVIDER_API_KEY','AI_GATEWAY_API_KEY','VERCEL_OIDC_TOKEN',
    'AEONITH_REQUIRE_VERCEL_GATEWAY_OIDC','AEONITH_ADMISSION_REDIS_URL',
    'AEONITH_ADMISSION_REDIS_TOKEN','AEONITH_ALLOWED_PROVIDER_URLS','VERCEL','VERCEL_ENV')
$saved = @{}
foreach ($name in (@($settings.Keys) + $blocked)) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$service = $null
try {
    foreach ($name in $blocked) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    foreach ($name in $settings.Keys) {
        [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
    }
    $service = Start-Process -FilePath $python -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden `
        -ArgumentList @('-m','aeonith.local_server','--host','127.0.0.1','--port','8765')
} finally {
    foreach ($name in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
    $token = $null
    $settings['AEONITH_SERVICE_TOKEN'] = $null
}
if ($null -eq $service) { throw 'Aeonith did not launch.' }

$ready = $false
for ($attempt = 0; $attempt -lt 16; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($service.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/healthz' -TimeoutSec 2
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq $service.Id -and $_.LocalAddress -eq '127.0.0.1' }
        if ($health.status -eq 'ok' -and $null -ne $listener) { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    if (-not $service.HasExited) { Stop-Process -Id $service.Id -ErrorAction SilentlyContinue }
    throw 'Aeonith failed the owned-loopback health and PID check. No public listener was changed.'
}
$record = @{
    ProcessId = $service.Id
    StartedUtc = $service.StartTime.ToUniversalTime().ToString('o')
    PythonPath = $python
    Port = $port
    FunnelOrigin = $FunnelOrigin
    Model = $Model
}
$record | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output ('Aeonith ready on 127.0.0.1:8765 (PID ' + $service.Id + ').')
Write-Output 'This script has NOT enabled Funnel; public HTTPS must be separately verified and configured.'
