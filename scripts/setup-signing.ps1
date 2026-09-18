# Sets up the two code-signing certificates an installer is signed with.
#
#     .\script.ps1 setup-signing [-FetchOnly]
#
# Uses the certificate already present when it matches its committed checksum, fetches it
# when it does not, and only generates one when there is nothing to fetch - generating is
# a NEW identity, and every installer signed with the old one stops matching it.
# docs/decisions/0003 is why the share links are secrets.

[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'Password', Justification = 'Ends up plaintext regardless - see the comment above')]
param(
    [ValidateSet('both', 'release', 'debug')]
    [string]$Which = 'both',
    [string]$Password = '',
    [string]$Publisher = '',
    [switch]$Force,
    [switch]$Yes,
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
    Write-Host '  Config (.dti_configs/signing.env, gitignored)'
    Write-Host '    share.cert           link the release .pfx is fetched from'
    Write-Host '    share.debugCert      link the debug .pfx is fetched from'
    Write-Host '    windows.certPassword the password both .pfx files are protected with'
    Write-Host ''
    Write-Host '  Config (.dti_configs/share.env, committed)'
    Write-Host '    publisher            certificate subject, e.g. CN=Name, O=Org'
    Write-Host ''
    Write-Host '  A runner has no gitignored file, so the same three values are read from'
    Write-Host '  DTI_CERT_SHARE_URL, DTI_DEBUG_CERT_SHARE_URL and DTI_CERT_PASSWORD.'
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

if (-not (Test-Path -LiteralPath $shareEnv)) {
    Set-EnvValue $shareEnv 'publisher' $script:Publisher
    Write-Host "      wrote a template at $($script:ConfigsDirName)\share.env" -ForegroundColor DarkGray
}

$stale = Read-EnvFile $shareEnv
foreach ($key in @('share.cert', 'share.debugCert')) {
    if (-not $stale[$key]) { continue }
    Set-EnvValue $signingEnv $key $stale[$key]
    Set-EnvValue $shareEnv $key ''
    Write-Host "      moved $key out of share.env (committed) into signing.env" -ForegroundColor Yellow
    Write-Host '        that link was in the repository - rotate it when you can' -ForegroundColor DarkGray
}
if ($Publisher) {
    Set-EnvValue $shareEnv 'publisher' $Publisher
    Write-Host "      publisher set to $Publisher" -ForegroundColor DarkGray
}

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
        Write-Host "      No $label certificate, and no $($ctx.ShareKey) to fetch one from." -ForegroundColor Yellow
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
    Write-Host '  Upload these, then put each link in signing.env - and in the' -ForegroundColor Cyan
    Write-Host '  repository secrets, which is where CI reads it from:' -ForegroundColor Cyan
    foreach ($ctx in $generated) {
        Write-Host "    $($script:CertsDirName)\$($ctx.Name)  ->  $($ctx.ShareKey)  /  $($ctx.ShareVar)"
    }
    Write-Host ''
    Write-Host '  A Dropbox link copied from the web app ends in dl=0 and serves a preview' -ForegroundColor DarkGray
    Write-Host '  page. Paste it as it is - the fetch rewrites it to dl=1 and rejects the' -ForegroundColor DarkGray
    Write-Host '  download if a web page arrives instead of a certificate.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  COMMIT the .sha256 sidecars. They are what makes the download verifiable.' -ForegroundColor Cyan
    Write-Host '  Do NOT commit the .pfx files or signing.env.' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  The password and the links have to reach another machine out of band -' -ForegroundColor DarkGray
    Write-Host '  none of them is in the repository, and the password cannot be recovered' -ForegroundColor DarkGray
    Write-Host '  from the certificate.' -ForegroundColor DarkGray
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
