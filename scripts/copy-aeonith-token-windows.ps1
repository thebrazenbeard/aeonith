# Copies the EXISTING DPAPI-protected Aeonith bearer into this Windows user's
# clipboard. Does not start, stop, probe, or reconfigure a service or model.
# Invoke only from the Windows account that originally launched Aeonith.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows-only DPAPI token recovery.' }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required.' }
$stateDir = Join-Path $env:LOCALAPPDATA 'Aeonith'
$tokenPath = Join-Path $stateDir 'token.dpapi'
if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
    throw 'No existing Aeonith token for this Windows user. Use the normal launcher first.'
}

# DPAPI decryption is bound to the owner user profile. Never send the secret
# across HTTP, include it in argv, write it to another file, or print it.
$secret = Get-Content -LiteralPath $tokenPath -Raw -Encoding ASCII | ConvertTo-SecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
try {
    if ($token.Length -lt 32 -or -not $token.IsNormalized()) {
        throw 'The protected Aeonith token is invalid.'
    }
    Set-Clipboard -Value $token
} finally {
    $token = $null
}
Write-Output ('Aeonith token copied to this Windows account clipboard. ' +
    'Paste it into the Service access token field in a trusted browser, ' +
    'then clear clipboard history. The service was not changed.')
