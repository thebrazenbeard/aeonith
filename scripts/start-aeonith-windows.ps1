# Starts only Aeonith's loopback web service. Does NOT enable Tailscale Funnel.
# Requires Windows PowerShell 5.1+, Python 3.11+, and an EXISTING local Ollama
# installation with the named model. No downloads, paid APIs, or remote models.
[CmdletBinding()]
param(
    [string]$FunnelOrigin = '',
    [string]$Model = 'qwen2.5-coder:1.5b-instruct-q3_K_M',
    [ValidateSet('legacy', 'aeonith-critic')]
    [Alias('Profile')]
    [string]$ModelProfile = 'legacy',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [string]$PythonExe = '',
    [switch]$CopyTokenToClipboard
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows-only DPAPI launcher.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$stateDir = Join-Path $env:LOCALAPPDATA 'Aeonith'
$statePath = Join-Path $stateDir 'deployment.json'
$tokenPath = Join-Path $stateDir 'token.dpapi'
if ($ModelProfile -eq 'aeonith-critic') {
    if ($PSBoundParameters.ContainsKey('Model') -and $Model -ne 'aeonith-critic:0.1') {
        throw 'The Aeonith critic profile only supports aeonith-critic:0.1.'
    }
    $Model = 'aeonith-critic:0.1'
} else {
    # Preserve the historical default, but do not imply it is the literary
    # critic profile: its 800-token JSON-object pilot did not complete a
    # structurally valid review. Never switch models without an explicit opt-in.
    Write-Warning ('Legacy profile selected (800 tokens, JSON-object mode). ' +
        'The literary-critic structural pilot used -ModelProfile aeonith-critic ' +
        'with an already-installed aeonith-critic:0.1 model. No model is downloaded.')
}
# An alternate loopback port must not silently retarget an external Funnel.
if ($FunnelOrigin -and $Port -ne 8765) {
    throw 'Nondefault port with FunnelOrigin is not qualified.'
}

function Resolve-LocalPythonExecutable([string]$candidate) {
    if (-not [IO.Path]::IsPathRooted($candidate) -or
        $candidate.StartsWith('\\') -or $candidate.StartsWith('//') -or
        -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw 'Python must be an existing absolute local executable path.'
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if ($resolved.StartsWith('\\') -or $resolved.StartsWith('//') -or
        [IO.Path]::GetExtension($resolved) -ine '.exe') {
        throw 'UNC/device paths and non-executable Python locations are forbidden.'
    }
    $driveRoot = [IO.Path]::GetPathRoot($resolved)
    if (-not $driveRoot) {
        throw 'Python path has no drive root.'
    }
    $driveInfo = [IO.DriveInfo]::new($driveRoot)
    if ($driveInfo.DriveType -ne [IO.DriveType]::Fixed) {
        throw 'Python must be on a local fixed drive, not a network or removable drive.'
    }
    return $resolved
}

if ($PythonExe) {
    $python = Resolve-LocalPythonExecutable $PythonExe
} else {
    $pathPython = (Get-Command python.exe -CommandType Application -ErrorAction Stop).Source
    $python = Resolve-LocalPythonExecutable $pathPython
}
# A WindowsApps alias is not a working interpreter on every host; detect it
# before any model preload or local deployment-state mutation.
try { & $python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 2)' }
catch { throw 'Python 3.11+ must be runnable; use -PythonExe with a local interpreter.' }
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.11+ must be runnable; use -PythonExe with a local interpreter.'
}
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
    if ($null -eq $deployment -or -not $deployment.ProcessId -or
        -not $deployment.StartedUtc -or -not $deployment.PythonPath) { return $false }
    $recordedPort = 0
    if (-not [int]::TryParse(([string]$deployment.Port), [ref]$recordedPort) -or
        $recordedPort -lt 1024 -or $recordedPort -gt 65535) { return $false }
    $process = Get-Process -Id ([int]$deployment.ProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $false }
    try {
        $actualStart = $process.StartTime.ToUniversalTime().ToString('o')
        $actualPath = $process.Path
    } catch { return $false }
    if ($actualStart -ne $deployment.StartedUtc -or $actualPath -ine $deployment.PythonPath) {
        return $false
    }
    try {
        $cmdline = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $process.Id) -ErrorAction Stop).CommandLine
    } catch { return $false }
    return ($cmdline -match '(?i)(?:^|\s)-m\s+aeonith\.local_server(?:\s|$)' -and
            $cmdline -match ('(?i)(?:^|\s)--port\s+' + $recordedPort + '(?:\s|$)'))
}

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (Test-AeonithIdentity $previous) {
        if ($previous.Port -ne $Port) {
            throw ('Aeonith already runs on port ' + $previous.Port + '; stop that recorded process first.')
        }
        if ($previous.FunnelOrigin -ne $FunnelOrigin) {
            throw 'Aeonith is already running with a different origin; stop it explicitly first.'
        }
        if ($previous.Model -ne $Model) {
            throw 'Aeonith is already running with a different model; stop it explicitly first.'
        }
        # Older deployment records lack Profile. They are not proof of the
        # new launch settings; refuse to adopt them without an owned stop.
        if ([string]$previous.Profile -ne $ModelProfile) {
            throw 'Existing Aeonith profile differs or is unrecorded; stop it explicitly first.'
        }
        $currentListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq [int]$previous.ProcessId -and $_.LocalAddress -eq '127.0.0.1' }
        if ($null -eq $currentListener) {
            throw 'Recorded Aeonith process is not serving the owned loopback port.'
        }
        Write-Output ('Aeonith already running on 127.0.0.1:' + $Port + ' (PID ' + $previous.ProcessId +
            ', profile ' + $ModelProfile + ', model ' + $Model + ').')
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
$occupied = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($occupied.Count -gt 0) { throw ('Port ' + $Port + ' is in use; refusing to interrupt another service.') }

# Ollama unloads idle models after five minutes by default, which can make a
# cold CPU inference exceed the app's bounded 50-second timeout. Preload only
# the already-installed model, with no user content or generated text, and
# keep legacy models resident for 24 hours; the opt-in critic profile uses
# five minutes to reduce long GPU contention. This remains a local operation.
$keepAlive = '24h'
if ($ModelProfile -eq 'aeonith-critic') { $keepAlive = '5m' }
$warmPayload = @{ model = $Model; keep_alive = $keepAlive; stream = $false } | ConvertTo-Json
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
if ($ModelProfile -eq 'aeonith-critic') {
    # Observed single-lens structural pilot: schema-constrained 2,048 tokens.
    $settings['AEONITH_MAX_OUTPUT_TOKENS'] = '2048'
    $settings['AEONITH_STRUCTURED_OUTPUTS'] = 'true'
    $settings['AEONITH_LOCAL_JSON_MODE'] = 'false'
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
        -ArgumentList @('-m','aeonith.local_server','--host','127.0.0.1','--port',([string]$Port))
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
        $health = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $Port + '/healthz') -TimeoutSec 2
        $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
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
    Port = $Port
    FunnelOrigin = $FunnelOrigin
    Model = $Model
    Profile = $ModelProfile
}
$record | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output ('Aeonith ready on 127.0.0.1:' + $Port + ' (PID ' + $service.Id +
    ', profile ' + $ModelProfile + ', model ' + $Model + ').')
Write-Output 'This script has NOT enabled Funnel; public HTTPS must be separately verified and configured.'
