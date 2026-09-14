# Fetches, verifies and uses the two code-signing certificates.
#
# A .pfx arrives over a share link from a machine nobody here controls, so the committed
# per-file SHA-256 sidecar is the only thing that can tell it from a same-named different
# file. The links are secrets and the checksums are what gets committed:
# docs/decisions/0003.

Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'app-version.ps1')

$script:ConfigsDirName = '.dti_configs'
$script:CertsDirName = 'certs'
$script:Publisher = 'CN=Developer Toolbox Inventory, O=DTI'

function Get-ConfigsDir {
    $dir = Join-Path (Get-RepoRoot) $script:ConfigsDirName
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    return $dir
}

function Get-SigningEnvPath { return Join-Path (Get-ConfigsDir) 'signing.env' }
function Get-ShareEnvPath { return Join-Path (Get-ConfigsDir) 'share.env' }

function Read-EnvFile([string]$Path) {
    $values = @{}
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        $text = "$line".Trim()
        if (-not $text -or $text.StartsWith('#')) { continue }
        $split = $text.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $text.Substring(0, $split).Trim()
        $value = $text.Substring($split + 1).Trim()
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = @()
    if (Test-Path -LiteralPath $Path) { $lines = @(Get-Content -LiteralPath $Path) }

    $written = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $text = "$($lines[$i])".Trim()
        if ($text.StartsWith('#')) { continue }
        $split = $text.IndexOf('=')
        if ($split -lt 1) { continue }
        if ($text.Substring(0, $split).Trim() -eq $Key) {
            $lines[$i] = "$Key=$Value"
            $written = $true
            break
        }
    }
    if (-not $written) { $lines += "$Key=$Value" }

    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    [IO.File]::WriteAllLines($Path, $lines, (New-Object Text.UTF8Encoding $false))
}

function Get-ShareUrl([string]$Key, [string]$Variable) {
    $saved = Read-EnvFile (Get-SigningEnvPath)
    if ($saved[$Key]) { return $saved[$Key] }
    if ($saved[$Variable]) { return $saved[$Variable] }
    $value = [Environment]::GetEnvironmentVariable($Variable)
    if ($value) { return "$value".Trim() }
    return ''
}

function Get-CertContext([switch]$Released) {
    $share = Read-EnvFile (Get-ShareEnvPath)
    $name = if ($Released) { 'release.pfx' } else { 'debug.pfx' }
    $shareKey = if ($Released) { 'share.cert' } else { 'share.debugCert' }
    $shareVar = if ($Released) { 'DTI_CERT_SHARE_URL' } else { 'DTI_DEBUG_CERT_SHARE_URL' }
    $publisher = if ($share['publisher']) { $share['publisher'] } else { $script:Publisher }

    return @{
        Kind      = if ($Released) { 'release' } else { 'debug' }
        Path      = Join-Path (Join-Path (Get-RepoRoot) $script:CertsDirName) $name
        Name      = $name
        ShareUrl  = Get-ShareUrl $shareKey $shareVar
        ShareKey  = $shareKey
        ShareVar  = $shareVar
        Publisher = $publisher
        Friendly  = "DTI $(if ($Released) { 'release' } else { 'debug' }) signing"
    }
}

function Get-CertHashPath([string]$PfxPath) {
    return Join-Path (Get-ConfigsDir) ((Split-Path -Leaf $PfxPath) + '.sha256')
}

function Write-Sha256To([string]$Path, [string]$SidecarPath) {
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
    $line = "$hash  $(Split-Path -Leaf $Path)"
    [IO.File]::WriteAllText($SidecarPath, "$line`n", (New-Object Text.UTF8Encoding $false))
    return $hash
}

function Read-Sha256Sidecar([string]$SidecarPath) {
    if (-not (Test-Path -LiteralPath $SidecarPath)) { return '' }
    $first = "$(Get-Content -LiteralPath $SidecarPath -TotalCount 1)".Trim()
    if (-not $first) { return '' }
    return ($first -split '\s+')[0].ToLower()
}

function Test-CertHash([string]$CandidatePath, [string]$PfxPath) {
    $sidecar = Get-CertHashPath $PfxPath
    $expected = Read-Sha256Sidecar $sidecar
    if (-not $expected) { return $true }
    if (-not (Test-Path -LiteralPath $CandidatePath)) { return $false }
    $actual = (Get-FileHash -LiteralPath $CandidatePath -Algorithm SHA256).Hash.ToLower()
    return ($actual -eq $expected)
}

function Get-RawShareUrl([string]$ShareUrl) {
    if (-not $ShareUrl) { return '' }
    $url = "$ShareUrl".Trim()

    if ($url -match '(?i)dl\.dropboxusercontent\.com') { return $url }

    if ($url -match '(?i)dropbox\.com') {
        if ($url -match '(?i)([?&])dl=[01]') {
            return ($url -replace '(?i)([?&])dl=[01]', '${1}dl=1')
        }
        $separator = if ($url.Contains('?')) { '&' } else { '?' }
        return "$url${separator}dl=1"
    }

    if ($url -match '(?i)1drv\.ms|onedrive\.live\.com|sharepoint\.com|-my\.sharepoint') {
        if ($url -match '(?i)([?&])download=1') { return $url }
        $separator = if ($url.Contains('?')) { '&' } else { '?' }
        return "$url${separator}download=1"
    }

    return $url
}

function Test-LooksLikeHtml([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $bytes = Get-Content -LiteralPath $Path -AsByteStream -TotalCount 512 -ErrorAction SilentlyContinue
    if (-not $bytes -or $bytes.Count -lt 1) { return $false }
    if ($bytes[0] -eq 0x30) { return $false }
    $text = [Text.Encoding]::ASCII.GetString($bytes)
    return ($text -match '(?i)<!doctype|<html|<head|<script|<meta')
}

function Get-SharedCert([hashtable]$Ctx) {
    if (-not $Ctx.ShareUrl) {
        return @{ Ok = $false; Reason = "no link - set $($Ctx.ShareKey) in $($script:ConfigsDirName)/signing.env, or $($Ctx.ShareVar) in the environment" }
    }
    $url = Get-RawShareUrl $Ctx.ShareUrl
    $temp = Join-Path ([IO.Path]::GetTempPath()) "dti-cert-$([guid]::NewGuid().ToString('n')).tmp"

    try {
        Invoke-WebRequest -Uri $url -OutFile $temp -MaximumRedirection 10 -ErrorAction Stop | Out-Null
    } catch {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
        return @{ Ok = $false; Reason = "the download failed: $($_.Exception.Message)" }
    }

    if (Test-LooksLikeHtml $temp) {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        return @{ Ok = $false; Reason = 'the link answered with a web page, not a file - it needs to be a direct/raw share link' }
    }
    if (-not (Test-CertHash $temp $Ctx.Path)) {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        return @{ Ok = $false; Reason = 'what arrived does not match the committed checksum - same name, different file' }
    }

    $dir = Split-Path -Parent $Ctx.Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    Move-Item -LiteralPath $temp -Destination $Ctx.Path -Force
    return @{ Ok = $true; Reason = '' }
}

function New-SigningPfx {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'Password', Justification = 'Read from a gitignored env file; it is plaintext before it arrives here')]
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingConvertToSecureStringWithPlainText', '', Justification = 'Export-PfxCertificate requires a SecureString and the source is already plaintext')]
    param(
        [Parameter(Mandatory)][string]$PfxPath,
        [Parameter(Mandatory)][string]$Password,
        [Parameter(Mandatory)][string]$Subject,
        [Parameter(Mandatory)][string]$FriendlyName
    )

    $dir = Split-Path -Parent $PfxPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    $cert = New-SelfSignedCertificate -Type Custom -Subject $Subject `
        -KeyUsage DigitalSignature -FriendlyName $FriendlyName `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')

    $secure = ConvertTo-SecureString -String $Password -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $PfxPath -Password $secure | Out-Null
    Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -ErrorAction SilentlyContinue

    $hash = Write-Sha256To $PfxPath (Get-CertHashPath $PfxPath)
    return @{ Ok = $true; Hash = $hash }
}

function New-CertPassword {
    $bytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Get-CertPassword {
    $saved = Read-EnvFile (Get-SigningEnvPath)
    if ($saved['windows.certPassword']) { return $saved['windows.certPassword'] }
    if ($saved['DTI_CERT_PASSWORD']) { return $saved['DTI_CERT_PASSWORD'] }
    if ($env:DTI_CERT_PASSWORD) { return $env:DTI_CERT_PASSWORD }
    return ''
}

function Find-SignTool {
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'x64' } else { 'x86' }
    $kitsBin = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsBin) {
        $found = Get-ChildItem -LiteralPath $kitsBin -Recurse -Filter 'signtool.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\$arch\\" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    $onPath = Get-Command 'signtool.exe' -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return ''
}

function Invoke-SignFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [switch]$Released,
        [string]$Description = 'Developer Toolbox Inventory'
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return @{ Signed = $false; Reason = "there is no file at $Path" }
    }

    $ctx = Get-CertContext -Released:$Released
    if (-not (Test-Path -LiteralPath $ctx.Path)) {
        return @{ Signed = $false; Reason = "no $($ctx.Kind) certificate at $($ctx.Name) - run setup-signing" }
    }
    if (-not (Test-CertHash $ctx.Path $ctx.Path)) {
        return @{ Signed = $false; Reason = "$($ctx.Name) does not match its committed checksum" }
    }

    $password = Get-CertPassword
    if (-not $password) {
        return @{ Signed = $false; Reason = "no certificate password - it belongs in $($script:ConfigsDirName)/signing.env, which is not committed" }
    }

    $signtool = Find-SignTool
    if (-not $signtool) {
        return @{ Signed = $false; Reason = 'signtool.exe was not found - install the Windows SDK' }
    }

    $arguments = @('sign', '/f', $ctx.Path, '/p', $password, '/fd', 'SHA256')
    if ($Description) { $arguments += @('/d', $Description) }
    $arguments += $Path

    $out = & $signtool @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        return @{ Signed = $false; Reason = "signtool failed: $(@($out) -join ' ')" }
    }
    return @{ Signed = $true; Reason = ''; Kind = $ctx.Kind }
}

function Write-SigningOutcome([hashtable]$Result, [string]$What) {
    if ($Result.Signed) {
        Write-Host "  signed $What with the $($Result.Kind) certificate" -ForegroundColor DarkGray
    } else {
        Write-Host "  $What is UNSIGNED - $($Result.Reason)" -ForegroundColor Yellow
        Write-Host '  It still installs; Windows will call the publisher unknown.' -ForegroundColor DarkGray
    }
}
