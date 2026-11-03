# Source-only candidate for a bounded, private VN1 qualification run.
# This file does not install a service or alter the existing 8765 deployment.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedHead,
    [ValidateRange(1024, 65535)][int]$Port = 8766,
    [ValidateRange(60, 180)][int]$ReviewTimeoutSeconds = 125,
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-PortUnused([int]$CheckPort) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $CheckPort -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 0) { throw 'Sidecar port is already in use; refusing to attach or replace it.' }
}

function ListenerSnapshot([int]$CheckPort) {
    return @(
        Get-NetTCPConnection -State Listen -LocalPort $CheckPort -ErrorAction SilentlyContinue |
        Sort-Object LocalAddress, OwningProcess |
        ForEach-Object { '{0}:{1}' -f $_.LocalAddress, $_.OwningProcess }
    ) -join '|'
}

function OwnedProcess([int]$ProcessId, [datetime]$ExpectedStart, [string]$PythonPath, [int]$CheckPort) {
    if ($ProcessId -le 0) { return $false }
    $live = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $live) { return $false }
    try {
        if ([math]::Abs(($live.StartTime - $ExpectedStart).TotalSeconds) -gt 2) { return $false }
        $cim = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $ProcessId) -ErrorAction Stop
        if ($null -eq $cim -or [string]::IsNullOrWhiteSpace($cim.CommandLine)) { return $false }
        $argsMatch = ('-E\s+-B\s+-S\s+-m\s+aeonith\.local_server\s+--host\s+127\.0\.0\.1\s+--port\s+{0}(\s|$)' -f $CheckPort)
        return ($cim.ExecutablePath -ieq $PythonPath -and $cim.CommandLine -match $argsMatch)
    } catch { return $false }
}

if ($env:OS -ne 'Windows_NT') { throw 'This qualification harness is Windows-only.' }
if ($Port -ne 8766) { throw 'Only the isolated sidecar port 8766 is permitted.' }
if ($ExpectedHead -cnotmatch '^[0-9a-f]{40}$') { throw 'ExpectedHead must be an exact lowercase 40-character commit SHA.' }
$resolvedRoot = (Resolve-Path -LiteralPath $RepositoryRoot -ErrorAction Stop).Path
$git = (Get-Command git.exe -ErrorAction Stop).Source
$python = (Get-Command python.exe -ErrorAction Stop).Source
$actualHead = (& $git -C $resolvedRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualHead -cne $ExpectedHead) {
    throw 'Exact source checkout does not match ExpectedHead.'
}
$status = @(& $git -C $resolvedRoot status --porcelain --untracked-files=all --ignored=matching)
if ($LASTEXITCODE -ne 0 -or $status.Count -gt 0) {
    throw 'Source checkout has modified, untracked or ignored files; qualification requires a pristine checkout.'
}
Assert-PortUnused $Port
$primaryBefore = ListenerSnapshot 8765
if ([string]::IsNullOrWhiteSpace($primaryBefore)) {
    throw 'Existing service on port 8765 was not observed; refusing sidecar qualification.'
}

# Restore each inherited setting to its exact previous presence/value when done.
$configuration = @{
    'AEONITH_SERVICE_TOKEN' = $null
    'AEONITH_PROVIDER_KIND' = 'local-openai-compatible'
    'AEONITH_PROVIDER_URL' = 'http://127.0.0.1:11434/v1/chat/completions'
    'AEONITH_PROVIDER_MODEL' = 'aeonith-critic:0.1'
    'AEONITH_MODEL_PROFILE' = 'aeonith-critic'
    'AEONITH_ENABLE_LIVE_REVIEWS' = 'true'
    'AEONITH_FUNNEL_ORIGIN' = ''
    'AEONITH_MAX_LENSES' = '1'
    'AEONITH_MAX_OUTPUT_TOKENS' = '2048'
    'AEONITH_PROVIDER_TIMEOUT_SECONDS' = '110'
    'AEONITH_LOCAL_JSON_MODE' = 'false'
    'AEONITH_STRUCTURED_OUTPUTS' = 'true'
}
$cloudSettings = @(
    'AEONITH_PROVIDER_API_KEY', 'AI_GATEWAY_API_KEY', 'VERCEL_OIDC_TOKEN',
    'AEONITH_REQUIRE_VERCEL_GATEWAY_OIDC', 'AEONITH_ADMISSION_REDIS_URL',
    'AEONITH_ADMISSION_REDIS_TOKEN', 'AEONITH_ALLOWED_PROVIDER_URLS',
    'VERCEL', 'VERCEL_ENV'
)
foreach ($key in $cloudSettings) { $configuration[$key] = '' }

$restore = @{}
foreach ($key in $configuration.Keys) {
    $restore[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 48
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$configuration['AEONITH_SERVICE_TOKEN'] = [Convert]::ToBase64String($bytes)
[Array]::Clear($bytes, 0, $bytes.Length)

$child = $null
$childStart = [datetime]::MinValue
$cleanupVerified = $false
$receipt = [ordered]@{
    schema_version = 'aeonith.sidecar-qualification.v1'
    source_head = $actualHead
    port = $Port
    provider = 'aeonith-critic:0.1'
    status = 'not_started'
    structural_status = 'not_run'
    quote_supported_lenses = 0
    cleanup_verified = $false
    primary_unchanged = $false
}
try {
    foreach ($key in $configuration.Keys) {
        [Environment]::SetEnvironmentVariable($key, $configuration[$key], 'Process')
    }
    Push-Location -LiteralPath $resolvedRoot
    try {
        # Enforces the sibling timeout patch before any server process is started.
        # -E rejects inherited PYTHON* injection, -B suppresses pyc writes,
        # -S skips all site packages and their startup hooks. -m loads only
        # from the verified working directory and stdlib.
        & $python -E -B -S -c 'from aeonith.service import _review_settings; import os; assert _review_settings(os.environ)[2] == 110.0'
        if ($LASTEXITCODE -ne 0) { throw 'Source does not support the required critic timeout.' }
        Assert-PortUnused $Port
        $child = Start-Process -FilePath $python -ArgumentList @(
            '-E', '-B', '-S', '-m', 'aeonith.local_server', '--host', '127.0.0.1', '--port', [string]$Port
        ) -WorkingDirectory $resolvedRoot -WindowStyle Hidden -PassThru
        $childStart = $child.StartTime
    } finally { Pop-Location }
    if ($null -eq $child -or -not (OwnedProcess $child.Id $childStart $python $Port)) {
        throw 'Sidecar process identity was not established.'
    }
    $url = 'http://127.0.0.1:{0}' -f $Port
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 250
        $owner = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($owner.Count -eq 0) { continue }
        if (@($owner | Where-Object { $_.OwningProcess -ne $child.Id }).Count -gt 0) {
            throw 'Port ownership differs from the launched sidecar.'
        }
        try {
            $health = Invoke-RestMethod -Uri ($url + '/healthz') -Method Get -TimeoutSec 3
            if ($health.status -eq 'ok' -and $health.review_configured -eq $true) {
                $ready = $true
                break
            }
        } catch { }
    }
    if (-not $ready) { throw 'Sidecar failed private readiness check.' }
    $receipt.status = 'ready'
    $request = @{
        schema_version = 'aeonith.review.v1'
        work = @{
            title = 'Synthetic Mirror'
            text = 'At dusk, the watchmaker returned the mirror. It shows tomorrow, she said, but the glass held yesterday''s rain.'
        }
        lenses = @('symbolic')
    } | ConvertTo-Json -Depth 5 -Compress
    $headers = @{ Authorization = ('Bearer ' + $configuration['AEONITH_SERVICE_TOKEN']) }
    try {
        $result = Invoke-RestMethod -Uri ($url + '/api/review') -Method Post `
            -ContentType 'application/json' -Headers $headers -Body $request `
            -TimeoutSec $ReviewTimeoutSeconds
        foreach ($lens in @($result.lens_reviews)) {
            if (@($lens.support | Where-Object { $_.source -eq 'work' }).Count -gt 0) {
                $receipt.quote_supported_lenses++
            }
        }
        if ($result.status -eq 'completed' -and $receipt.quote_supported_lenses -ge 1) {
            $receipt.status = 'smoke_complete'
            $receipt.structural_status = 'quote_grounded'
        } else {
            $receipt.status = 'smoke_failed'
            $receipt.structural_status = 'missing_quote_or_invalid_result'
        }
    } catch {
        # Intentionally do not print exception text, request body or provider prose.
        $receipt.status = 'smoke_failed'
        $receipt.structural_status = 'request_failed'
    }
} catch {
    $receipt.status = 'qualification_failed'
    $receipt.structural_status = 'preflight_or_readiness_failed'
} finally {
    foreach ($key in $restore.Keys) {
        [Environment]::SetEnvironmentVariable($key, $restore[$key], 'Process')
    }
    $headers = $null
    $configuration['AEONITH_SERVICE_TOKEN'] = $null
    $cleanupVerified = ($null -eq $child)
    if ($null -ne $child) {
        # Start-Process -PassThru supplied this native Process object/handle.
        # Use that handle, never a stop-by-PID operation (PID recycle race), including
        # when the optional CIM command-line check above failed. A started
        # child remains our cleanup responsibility even on readiness failure.
        try {
            if (-not $child.HasExited) { $child.Kill() }
            [void]$child.WaitForExit(8000)
            $cleanupVerified = $child.HasExited
        } catch { $cleanupVerified = $false }
        finally { $child.Dispose() }
    }
    $receipt.cleanup_verified = ($cleanupVerified -and @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -eq 0)
    $receipt.primary_unchanged = ((ListenerSnapshot 8765) -ceq $primaryBefore)
    $receipt | ConvertTo-Json -Compress -Depth 5
    if ($receipt.status -ne 'smoke_complete' -or -not $receipt.cleanup_verified -or -not $receipt.primary_unchanged) {
        throw 'Sidecar qualification failed; only a sanitized receipt was emitted.'
    }
}
