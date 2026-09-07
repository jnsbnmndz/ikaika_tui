# Sets up the two code-signing certificates an installer is signed with.
#
#     .\script.ps1 setup-signing                    both certificates
#     .\script.ps1 setup-signing -Which debug       just the debug one
#     .\script.ps1 setup-signing -Force             regenerate - a NEW signing identity
#     .\script.ps1 setup-signing -Yes               never ask; for CI
#
# For each certificate: use the one already here if it matches its committed checksum,
# otherwise fetch it from the shared link, otherwise generate one. Generation is last
# because a generated certificate is a NEW identity - every installer signed with the old
# one stops matching it - so it is what happens when there is genuinely nothing to fetch,
# not what happens when a link is merely misconfigured.
#
#
# THE PASSWORD IS SAVED BEFORE THE CERTIFICATE IS GENERATED
#
# Not after. A crash in between leaves a .pfx that nothing can ever open, because the
# password is not recoverable from the file - and the window is real, since generation
# writes to the user's certificate store and exports from it. Saving first can leave a
# password with no certificate, which is harmless: the next run generates one.
#
#
# WHAT ENDS UP WHERE
#
#   certs/release.pfx, certs/debug.pfx        gitignored - the private keys
#   .generic_configs/signing.env             gitignored - the password
#   .generic_configs/*.pfx.sha256            COMMITTED - the trust anchors
#   .generic_configs/share.env               COMMITTED - the links
#
# A new machine needs the password out of band. The link alone will not open the files,
# which is what makes committing it safe.
#
#
# UPLOADING IS A HUMAN STEP, AND SAYING SO IS THE POINT
#
# This does not upload anything. Handing a build script a Dropbox token means a token on
# disk with write access to the folder holding the signing keys, and the whole reason the
# password is out of band is that no single artefact should be enough. So it generates,
# records the checksum, and prints exactly what to upload and which key to paste the link
# into - and the checksum it just committed is what proves the next machine got that file
# and not something else.
#
# Requires PowerShell 7+.

[CmdletBinding()]
# The password is a plain string on purpose, and SecureString would be theatre here: it
# has to be handed to signtool as /p on a command line and written to a file signtool
# can read, so it is plaintext at both ends whatever type it travels in. What actually
# protects it is that signing.env is gitignored and the value never leaves the machine.
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'Password', Justification = 'Ends up plaintext regardless - see the comment above')]
param(
    [ValidateSet('both', 'release', 'debug')]
    [string]$Which = 'both',
    # Use this password instead of a generated one. For adopting certificates that already
    # exist somewhere - a fresh setup should let it generate.
    [string]$Password = '',
    # The certificate subject. Must match everywhere: signtool fails if the publisher and
    # the subject disagree.
    [string]$Publisher = '',
    # Regenerate even when a valid certificate is already here. A new identity.
    [switch]$Force,
    # Assume yes. Nothing here is destructive except -Force, which this then allows.
    [switch]$Yes,
    # Fetch or use what is here, but NEVER generate. What CI runs.
    #
    # Generating on a build machine is the failure this exists to prevent: -Yes would
    # answer an unreachable link by minting a brand-new identity, so every release would
    # be signed by a different certificate that exists only in that runner and is thrown
    # away with it. Users would see the publisher change on every single update. Failing
    # is the correct outcome there.
    [switch]$FetchOnly,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\signing.ps1')

if ($Help) {
    Write-Host ''
    Write-Host '  setup-signing - the release and debug code-signing certificates.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 setup-signing [-Which both|release|debug] [-Password <pw>]'
    Write-Host '                               [-Publisher <subject>] [-Force] [-Yes]'
    Write-Host '                               [-FetchOnly]'
    Write-Host ''
    Write-Host '  Two certificates: a debug installer is signed with its own, so testing'
    Write-Host '  never touches the trust the release signature depends on. One password'
    Write-Host '  and one subject cover both - the publisher must match the certificate'
    Write-Host '  subject exactly or signtool fails.'
    Write-Host ''
    Write-Host '  Uses what is already here if it matches the committed checksum, else'
    Write-Host '  fetches the shared link, else generates. Generating is last: it is a'
    Write-Host '  new identity, and old installers stop matching it.'
    Write-Host ''
    Write-Host '  Config (.generic_configs/share.env, committed)'
    Write-Host '    share.cert           link the release .pfx is fetched from'
    Write-Host '    share.debugCert      link the debug .pfx is fetched from'
    Write-Host '    publisher            certificate subject, e.g. CN=Name, O=Org'
    Write-Host ''
    Write-Host '  The .pfx files and signing.env are secrets and are gitignored. The'
    Write-Host '  .sha256 sidecars are committed - that is what makes a download'
    Write-Host '  verifiable at all.'
    Write-Host ''
    exit 0
}

if ($FetchOnly -and $Force) {
    Write-Host '  -FetchOnly and -Force contradict each other: one forbids generating and' -ForegroundColor Red
    Write-Host '  the other does nothing but generate. Pick one.' -ForegroundColor Red
    exit 1
}

$root = Get-RepoRoot
$signingEnv = Get-SigningEnvPath
$shareEnv = Get-ShareEnvPath

Write-Host ''
Write-Host "[1/4] Signing setup for $root"

# The committed half of the configuration, written as a template on a first run so the
# keys are discoverable without reading this file.
if (-not (Test-Path -LiteralPath $shareEnv)) {
    Set-EnvValue $shareEnv 'publisher' $script:Publisher
    Set-EnvValue $shareEnv 'share.cert' ''
    Set-EnvValue $shareEnv 'share.debugCert' ''
    Write-Host "      wrote a template at $($script:ConfigsDirName)\share.env" -ForegroundColor DarkGray
}
if ($Publisher) {
    Set-EnvValue $shareEnv 'publisher' $Publisher
    Write-Host "      publisher set to $Publisher" -ForegroundColor DarkGray
}

# THE PASSWORD FIRST, for the reason in the header. An existing one is never replaced -
# doing so would orphan every certificate already generated with it.
$existingPassword = Get-CertPassword
if ($Password) {
    $password = $Password
} elseif ($existingPassword) {
    $password = $existingPassword
} else {
    $password = New-CertPassword
}

if ($password -ne $existingPassword) {
    Set-EnvValue $signingEnv 'windows.certPassword' $password
    if (-not (Test-Path -LiteralPath $signingEnv)) {
        throw "the password was not written to $signingEnv - refusing to generate a certificate nothing could open"
    }
    $check = Read-EnvFile $signingEnv
    if ($check['windows.certPassword'] -ne $password) {
        throw "$signingEnv does not read back the password just written to it"
    }
    Write-Host "[2/4] Password saved to $($script:ConfigsDirName)\signing.env (not committed)"
} else {
    Write-Host '[2/4] Using the password already in signing.env'
}

$kinds = switch ($Which) {
    'release' { @($true) }
    'debug' { @($false) }
    default { @($true, $false) }
}

Write-Host '[3/4] Certificates'
$generated = @()
$failed = @()

foreach ($released in $kinds) {
    $ctx = Get-CertContext -Released:$released
    $label = $ctx.Kind
    $here = Test-Path -LiteralPath $ctx.Path

    if ($here -and -not $Force) {
        if (Test-CertHash $ctx.Path $ctx.Path) {
            # No anchor yet for a certificate that is already here: record one, which is
            # the only thing that makes it verifiable elsewhere.
            $sidecar = Get-CertHashPath $ctx.Path
            if (-not (Test-Path -LiteralPath $sidecar)) {
                Write-Sha256To $ctx.Path $sidecar | Out-Null
                Write-Host "      $label - here already, recorded its checksum" -ForegroundColor DarkGray
            } else {
                Write-Host "      $label - here already and matches its checksum" -ForegroundColor DarkGray
            }
            continue
        }
        Write-Host "      $label - $($ctx.Name) does NOT match the committed checksum." -ForegroundColor Yellow
        Write-Host '        Same name, different file. Move it aside and run this again,' -ForegroundColor DarkGray
        Write-Host '        or use -Force to generate a new identity.' -ForegroundColor DarkGray
        $failed += $label
        continue
    }

    if ($Force -and $here) {
        if (-not $Yes) {
            Write-Host ''
            Write-Host "      -Force replaces the $label certificate with a NEW identity." -ForegroundColor Yellow
            Write-Host '      Everything already signed with the old one stops matching it.' -ForegroundColor Yellow
            $answer = Read-Host "      Replace the $label certificate? (y/N)"
            if ($answer -notmatch '^(?i)y') {
                Write-Host "      $label - left alone" -ForegroundColor DarkGray
                continue
            }
        }
        Remove-Item -LiteralPath $ctx.Path -Force
    }

    # Fetch before generate. A link that is merely misconfigured must not be answered by
    # minting a second identity for something that already has one.
    if (-not $Force -and $ctx.ShareUrl) {
        $fetch = Get-SharedCert $ctx
        if ($fetch.Ok) {
            Write-Host "      $label - fetched from the shared link, checksum matches" -ForegroundColor DarkGray
            continue
        }
        Write-Host "      $label - not fetched: $($fetch.Reason)" -ForegroundColor Yellow
    }

    if ($FetchOnly) {
        Write-Host "      $label - not here and not fetched, and -FetchOnly forbids generating" -ForegroundColor Red
        $failed += $label
        continue
    }

    if (-not $Force -and -not $Yes -and -not $ctx.ShareUrl) {
        Write-Host ''
        Write-Host "      No $label certificate, and $($ctx.ShareKey) is not set." -ForegroundColor Yellow
        $answer = Read-Host "      Generate a new $label certificate? (Y/n)"
        if ($answer -match '^(?i)n') {
            Write-Host "      $label - skipped" -ForegroundColor DarkGray
            $failed += $label
            continue
        }
    }

    $made = New-SigningPfx -PfxPath $ctx.Path -Password $password `
        -Subject $ctx.Publisher -FriendlyName $ctx.Friendly
    Write-Host "      $label - generated $($ctx.Name), checksum $($made.Hash.Substring(0, 12))..." -ForegroundColor Green
    $generated += $ctx
}

Write-Host '[4/4] Done'
Write-Host ''

if ($generated.Count) {
    Write-Host '  Upload these, then paste the links into share.env:' -ForegroundColor Cyan
    foreach ($ctx in $generated) {
        Write-Host "    $($script:CertsDirName)\$($ctx.Name)  ->  $($ctx.ShareKey)"
    }
    Write-Host ''
    Write-Host '  A Dropbox link copied from the web app ends in dl=0 and serves a preview' -ForegroundColor DarkGray
    Write-Host '  page. Paste it as it is - the fetch rewrites it to dl=1 and rejects the' -ForegroundColor DarkGray
    Write-Host '  download if a web page arrives instead of a certificate.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  COMMIT the .sha256 sidecars. They are what makes the download verifiable.' -ForegroundColor Cyan
    Write-Host '  Do NOT commit the .pfx files or signing.env.' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  The password has to reach another machine out of band - it is not in the' -ForegroundColor DarkGray
    Write-Host '  repository and cannot be recovered from the certificate.' -ForegroundColor DarkGray
    Write-Host ''
}

if ($failed.Count) {
    Write-Host "  Unresolved: $($failed -join ', ')" -ForegroundColor Yellow
    Write-Host '  Builds still work; their artifacts will be unsigned.' -ForegroundColor DarkGray
    Write-Host ''
    exit 1
}

$signtool = Find-SignTool
if ($signtool) {
    Write-Host "  signtool: $signtool" -ForegroundColor DarkGray
} else {
    Write-Host '  signtool.exe was not found - install the Windows SDK to sign anything.' -ForegroundColor Yellow
    Write-Host '    winget install Microsoft.WindowsSDK' -ForegroundColor DarkGray
}
Write-Host ''
exit 0
