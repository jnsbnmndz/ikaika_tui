# Packages a frozen build into a Windows installer.
#
#     .\script.ps1 build-installer [-Released] [-Sign]
#
# NSIS is found where it installs itself, not on PATH. The version reaches it in two
# shapes because Windows wants both: `0.1.0+2` for people and four numbers for the
# resource table.

[CmdletBinding()]
param(
    [switch]$Released,
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
$outFile = Join-Path $outDir "$AppName-$text-setup$suffix.exe"

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
    $signed = Invoke-SignFile -Path $outFile -Released:$Released -Description $AppTitle
    Write-SigningOutcome $signed 'the installer'
}

$size = [math]::Round((Get-Item -LiteralPath $outFile).Length / 1MB, 1)
Write-Host "[5/5] $outFile  ($size MB)"
Write-Host ''
exit 0
