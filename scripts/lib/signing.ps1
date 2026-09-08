# Code signing: the two certificates, where they come from, and how a file gets signed.
#
# Two certificates, not one - a release identity and a debug one. A debug installer is
# signed too, so a test build is not an Unknown Publisher either, but with its own
# certificate, so nothing about a test build touches the trust built up for the real
# release signature. Both share one password and one subject, because the publisher must
# match the certificate subject exactly or signtool refuses; only the FILE differs.
#
#
# UNSIGNED IS A WARNING, NOT A FAILURE
#
# Every function here reports what happened and returns; none of them throw. An unsigned
# installer works - it shows an Unknown Publisher prompt - so a machine without the
# Windows SDK, or without the certificate, must still be able to produce a build. The
# caller decides how loudly to say it, and saying nothing is not one of the options.
#
#
# WHAT IS COMMITTED AND WHAT IS NOT
#
#   certs/*.pfx                     NO  - the private key
#   .dti_configs/signing.env        NO  - the password
#   .dti_configs/*.pfx.sha256       YES - deliberately, see below
#   .dti_configs/share.env          YES - the links, which alone open nothing
#
# The checksums are the point of the split. A .pfx arrives over a shared link from a
# machine nobody here controls, and a same-named file is not the same file; the committed
# sidecar is the only thing that can tell the difference. The link is safe to commit
# because the password is not there - fetching the file gets you a container you cannot
# open.
#
# THE SIDECAR IS ABSENT ON A FIRST BOOTSTRAP, AND ABSENT MEANS "RECORD ONE". That is the
# only sane reading, and it is also the failure mode: point the sidecar path at somewhere
# the anchor is not and every arrival reads as a first bootstrap, so the integrity check
# quietly becomes a no-op and starts recording whatever it was handed. It is therefore
# reached only through Get-CertHashPath, never rebuilt at a call site. This has cost the
# sibling project two silent breakages.
#
#
# THE SHARE LINK IS NORMALISED PER HOST, BECAUSE RAW CONTENT IS NOT THE DEFAULT
#
# A share link opens a web page. Fetching it gives you HTML - a preview page, a sign-in
# form - with a 200 status, and writing that to cert.pfx produces a file that fails much
# later inside signtool with an error about the certificate rather than about the download.
# Each host spells "give me the bytes" differently: Dropbox wants dl=1, OneDrive and
# SharePoint want download=1. Get-RawShareUrl knows the spellings; Get-SharedFile checks
# what actually arrived rather than trusting any of them.
#
# Requires PowerShell 7+.

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


# Reads a `key=value` file into a hashtable. Missing file is an empty table, not an error:
# every caller has a defensible answer for "not configured" and none of them wants a throw.
#
# Values are NOT trimmed of quotes beyond one matched pair, and `#` only starts a comment
# at the beginning of a line - a password can legitimately contain one, and stripping from
# the first `#` anywhere truncated it silently.
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

# Sets one key, leaving every other line as it was.
#
# Key by key rather than rewriting the file: signing.env may hold values this code knows
# nothing about, and a wholesale rewrite drops them. Creates the file when it is absent -
# a first run has nowhere to write, and the sibling project's version of this returned
# quietly in that case, so a generated password went nowhere and left two .pfx files
# nothing could ever open while the run printed "saved".
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


# Which certificate a build is signed with, and everything that follows from that choice.
#
# One function rather than a released/debug branch at each call site: the file, the
# checksum anchor and the share link all have to agree about which identity is in play,
# and three separate conditionals is how they stop agreeing.
function Get-CertContext([switch]$Released) {
    $share = Read-EnvFile (Get-ShareEnvPath)
    $name = if ($Released) { 'release.pfx' } else { 'debug.pfx' }
    $shareKey = if ($Released) { 'share.cert' } else { 'share.debugCert' }
    $publisher = if ($share['publisher']) { $share['publisher'] } else { $script:Publisher }

    return @{
        Kind      = if ($Released) { 'release' } else { 'debug' }
        Path      = Join-Path (Join-Path (Get-RepoRoot) $script:CertsDirName) $name
        Name      = $name
        ShareUrl  = if ($share.ContainsKey($shareKey)) { $share[$shareKey] } else { '' }
        ShareKey  = $shareKey
        Publisher = $publisher
        Friendly  = "DTI $(if ($Released) { 'release' } else { 'debug' }) signing"
    }
}

# The committed trust anchor for one certificate. certs/ is gitignored as a directory, and
# git cannot un-ignore a single file inside an excluded directory - so the sidecar cannot
# live beside the .pfx and has to be somewhere committable. See the header.
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

# True when the file matches its recorded anchor, or when there is no anchor yet.
#
# -LiteralPath throughout: a certs directory reached through a profile path containing
# glob metacharacters - and this repository lives under a folder literally named
# "GitHub(jnsbnmndz)" - does not resolve as a wildcard, and a path that fails to resolve
# reads as a missing file, which is the "first bootstrap" branch again.
function Test-CertHash([string]$CandidatePath, [string]$PfxPath) {
    $sidecar = Get-CertHashPath $PfxPath
    $expected = Read-Sha256Sidecar $sidecar
    if (-not $expected) { return $true }
    if (-not (Test-Path -LiteralPath $CandidatePath)) { return $false }
    $actual = (Get-FileHash -LiteralPath $CandidatePath -Algorithm SHA256).Hash.ToLower()
    return ($actual -eq $expected)
}


# Turns a share link into one that answers with the file's bytes.
#
# Dropbox: dl=1. A link copied from the web app ends in dl=0, and the newer /scl/fi/ links
# carry an rlkey that is part of the credential - so the parameter is REPLACED in place and
# every other one is kept, rather than the query being rebuilt.
# OneDrive and SharePoint: download=1, appended.
# Anything else is returned untouched, because a plain HTTPS path to a file already is raw
# and appending a parameter to it is how a working link stops working.
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

# True when the bytes look like a web page rather than a certificate.
#
# This is the check that matters. Every host answers a bad or expired link with 200 and an
# HTML body, so the download "succeeds" and the failure surfaces later inside signtool,
# talking about the certificate. A PFX is DER: it starts with an ASN.1 SEQUENCE, 0x30.
function Test-LooksLikeHtml([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $bytes = Get-Content -LiteralPath $Path -AsByteStream -TotalCount 512 -ErrorAction SilentlyContinue
    if (-not $bytes -or $bytes.Count -lt 1) { return $false }
    if ($bytes[0] -eq 0x30) { return $false }
    $text = [Text.Encoding]::ASCII.GetString($bytes)
    return ($text -match '(?i)<!doctype|<html|<head|<script|<meta')
}

# Downloads a certificate from its share link, and refuses to keep anything it cannot
# vouch for. Reports; never throws.
#
# The download goes to a temporary file and is promoted only after both checks pass -
# writing straight to certs/release.pfx and validating afterwards leaves a bad file in the
# place everything downstream reads from.
function Get-SharedCert([hashtable]$Ctx) {
    if (-not $Ctx.ShareUrl) {
        return @{ Ok = $false; Reason = "$($Ctx.ShareKey) is not set in $($script:ConfigsDirName)/share.env" }
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


# Generates a self-signed code-signing certificate and records its checksum.
#
# The key usage matters and is easy to get subtly wrong: a certificate without the code
# signing EKU (1.3.6.1.5.5.7.3.3) is accepted by New-SelfSignedCertificate and then
# rejected by signtool. The empty 2.5.29.19 marks it as an end entity rather than a CA.
#
# The .pfx is the only copy that matters, so the certificate is removed from the user's
# store afterwards - leaving it there means a second run finds a store full of near
# duplicates and no way to tell which one the file came from.
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

# 32 random bytes, base64. Not a prompt: this protects a local file that is itself a
# secret, so a memorable password buys nothing and asking for one invites somebody to
# reuse a real password in a file that lives on disk in the clear.
function New-CertPassword {
    $bytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Get-CertPassword {
    $saved = Read-EnvFile (Get-SigningEnvPath)
    if ($saved['windows.certPassword']) { return $saved['windows.certPassword'] }
    if ($saved['DTI_CERT_PASSWORD']) { return $saved['DTI_CERT_PASSWORD'] }
    # The environment wins nothing here, but CI has no gitignored file to read - so a
    # value passed in through the environment is honoured and never written to disk.
    if ($env:DTI_CERT_PASSWORD) { return $env:DTI_CERT_PASSWORD }
    return ''
}


# signtool.exe, which is not on PATH on any machine that has not put it there.
#
# It ships inside the Windows SDK at a version-numbered path, so PATH is checked LAST -
# the same shape of mistake as makensis, where "not installed" was reported on a machine
# where it plainly was. The newest SDK wins, and the architecture is matched because the
# x86 copy on a 64-bit machine works but is the wrong one to prefer.
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

# Signs one file, and says what happened.
#
# /fd SHA256 because SHA-1 authenticode is rejected outright by current Windows. /d is the
# name a UAC prompt shows. No timestamp server is used: signing has to work offline, and a
# timestamp only matters for a signature meant to outlive its certificate, which a
# self-signed one is not.
#
# signtool's output is captured rather than streamed - it prints the whole certificate on
# success, which is noise, and on failure the text is the only useful part.
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

# Prints the outcome of a signing attempt the one way, so both build commands say it
# identically. Reported, never omitted - a build whose artifacts are unsigned has to say
# so, because the difference only shows up on somebody else's machine.
function Write-SigningOutcome([hashtable]$Result, [string]$What) {
    if ($Result.Signed) {
        Write-Host "  signed $What with the $($Result.Kind) certificate" -ForegroundColor DarkGray
    } else {
        Write-Host "  $What is UNSIGNED - $($Result.Reason)" -ForegroundColor Yellow
        Write-Host '  It still installs; Windows will call the publisher unknown.' -ForegroundColor DarkGray
    }
}
