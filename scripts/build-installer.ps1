# Packages a frozen build into a Windows installer.
#
#     .\script.ps1 build-installer                  the debug build's installer
#     .\script.ps1 build-installer -Released        the official one
#
# It packages what `build-app` produced and refuses to guess: no folder for this version
# means the build has not been run, and building an installer around a stale folder is how
# a release ships the version before it.
#
# MAKENSIS IS FOUND, NOT ASSUMED TO BE ON PATH. The NSIS installer does not add itself to
# PATH, so `Get-Command makensis` says "not installed" on a machine where it plainly is -
# this looks where it actually lives, including the registry key its own installer writes.
# That mistake has already been made once in this session.
#
# The version reaches NSIS in two shapes because Windows needs both: `0.1.0+2` for people,
# and `0.1.0.2` for the file resource, which is four dot-separated numbers or nothing.
#
# Requires PowerShell 7+ and NSIS 3.

[CmdletBinding()]
param(
    # Package the official build, and put -released in the installer's name.
    [switch]$Released,
    # Sign the installer if a certificate is configured. Off by default: an unsigned
    # installer is an Unknown Publisher warning, not a broken installer.
    [switch]$Sign,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

$AppName = 'dti'
$AppTitle = 'Developer Toolbox Inventory'
$Publisher = 'Developer Toolbox Inventory'

if ($Help) {
    Write-Host ''
    Write-Host '  build-installer - package a frozen build into a Windows installer.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 build-installer [-Released] [-Sign]'
    Write-Host ''
    Write-Host '  Packages dist\<name>-<version>\, which build-app writes. Per-user'
    Write-Host '  install under LOCALAPPDATA, so it needs no admin prompt.'
    Write-Host ''
    Write-Host '  Needs NSIS 3. It is found where it installs itself, not on PATH.'
    Write-Host ''
    exit 0
}

# Where NSIS actually is. The registry key first - that is what its own installer wrote
# and it survives an install to a non-default location - then the two usual folders, then
# PATH for a portable copy somebody put there deliberately.
function Find-MakeNsis {
    foreach ($key in @('HKLM:\SOFTWARE\NSIS', 'HKLM:\SOFTWARE\WOW6432Node\NSIS')) {
        try {
            $base = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).'(default)'
            if ($base) {
                $candidate = Join-Path $base 'makensis.exe'
                if (Test-Path -LiteralPath $candidate) { return $candidate }
            }
        } catch { continue }
    }
    foreach ($candidate in @(
            "${env:ProgramFiles(x86)}\NSIS\makensis.exe",
            "$env:ProgramFiles\NSIS\makensis.exe")) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $onPath = Get-Command 'makensis' -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return ''
}

$root = Get-RepoRoot
$version = Get-AppVersion
$text = Format-AppVersion $version
$kind = if ($Released) { 'official' } else { 'debug' }

Write-Host ''
Write-Host "[1/5] Packaging $AppTitle $text ($kind)"

$makensis = Find-MakeNsis
if (-not $makensis) {
    Write-Host ''
    Write-Host '  NSIS is not on this machine.' -ForegroundColor Red
    Write-Host '    winget install NSIS.NSIS' -ForegroundColor Yellow
    Write-Host ''
    exit 1
}
Write-Host "[2/5] makensis: $makensis"

$sourceName = "$AppName-$text"
$source = Join-Path $root "dist\$sourceName"
# Named for the app, not the version - see build-app.
$exeName = "$AppName.exe"

if (-not (Test-Path -LiteralPath (Join-Path $source $exeName))) {
    Write-Host ''
    Write-Host "  No frozen build for $text at dist\$sourceName." -ForegroundColor Red
    Write-Host "    .\script.ps1 build-app$(if ($Released) { ' -Released' })" -ForegroundColor Yellow
    Write-Host ''
    exit 1
}
Write-Host "[3/5] Source: dist\$sourceName"

$suffix = if ($Released) { '-released' } else { '' }
$outDir = Join-Path $root 'dist'
# THE BUILD NUMBER IS IN THE FILENAME, and it has to be.
#
# This was `$($version.Name)`, so 0.1.1+4 and 0.1.1+5 both came out as
# dti-0.1.1-setup.exe. Two GitHub releases then carried an asset with one name, a browser
# saved the second as "dti-0.1.1-setup (1).exe", and the only way to tell which was which
# was to install one and ask it. That is exactly the confusion the global build number
# exists to prevent - a rebuild of the same source IS a different artifact - and the
# filename was the one place it was left out.
#
# `+` rather than a dot, matching the tag (v0.1.1+5) and the dist folder. If a host
# normalises it the two names still differ, which is the whole requirement.
$outFile = Join-Path $outDir "$AppName-$text-setup$suffix.exe"

# Four dot-separated numbers, which is the only shape VIProductVersion accepts. The build
# number is the fourth part, so the file's own properties agree with its name.
$viVersion = "$($version.Major).$($version.Minor).$($version.Patch).$($version.Build)"

$defines = @(
    "/DAPP_NAME=$AppName",
    "/DAPP_TITLE=$AppTitle",
    "/DPUBLISHER=$Publisher",
    "/DVERSION=$text",
    "/DVI_VERSION=$viVersion",
    "/DSOURCE_DIR=$source",
    "/DEXE_NAME=$exeName",
    "/DOUT_FILE=$outFile",
    # The script that edits PATH. Passed as a path rather than embedded in the
    # .nsi: it is a real PowerShell file that can be run and tested on its own,
    # which is how the PATH round trip was verified before an installer existed.
    "/DPATH_SCRIPT=$(Join-Path $PSScriptRoot 'lib\path-entry.ps1')"
)
if ($Released) { $defines += '/DRELEASED=1' }

Write-Host '[4/5] Compiling...'
& $makensis @defines (Join-Path $PSScriptRoot 'installer.nsi')
if ($LASTEXITCODE -ne 0) {
    Write-Host '  makensis failed - its output is above.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $outFile)) {
    Write-Host "  makensis reported success but $outFile is not there." -ForegroundColor Red
    exit 1
}

if ($Sign) {
    . (Join-Path $PSScriptRoot 'lib\signing.ps1')
    # Captured, not left on the pipeline: Invoke-SignFile returns a hashtable, and an
    # uncaptured return value here is printed as one between the build's own step lines.
    $signed = Invoke-SignFile -Path $outFile -Released:$Released -Description $AppTitle
    Write-SigningOutcome $signed 'the installer'
}

$size = [math]::Round((Get-Item -LiteralPath $outFile).Length / 1MB, 1)
Write-Host "[5/5] $outFile  ($size MB)"
Write-Host ''
exit 0
