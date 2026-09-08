# Freezes the app into a folder that runs without Python installed.
#
#     .\script.ps1 build-app                    a debug build
#     .\script.ps1 build-app -Released          the official one
#     .\script.ps1 build-app -Clean             throw the cache away first
#
# ONE FOLDER, not one file. A onefile build unpacks itself into a temp directory on every
# start, which for a terminal app is a visible pause before anything is drawn, and it
# leaves the unpacked copy behind when it is killed. The folder is also what NSIS wants:
# an installer copies a directory.
#
# VERSION IS ADDED AS DATA, and that is not optional. `presentation/branding.py` reads it
# to put the version in the header, and a frozen app has no repository around it - without
# this the header reads v0.0.0+0 and nothing fails, which is the worst way for it to be
# wrong. The build asserts the file made it in rather than trusting the flag.
#
# The output folder is named for the version, so two builds of different versions can sit
# beside each other and an installer names what it packaged:
#
#     dist/<name>-<x.y.z+n>/            what NSIS packages
#     build/                            PyInstaller's scratch, disposable
#
# PyInstaller is a BUILD-time dependency and is not installed for you: fetching a package
# in order to build is a decision, and a build tool that quietly pip-installs is one
# nobody can reason about. It says how to install it and stops.
#
# Requires PowerShell 7+.

[CmdletBinding()]
param(
    # Tag the artifact as the official build rather than a debug one.
    [switch]$Released,
    # Clear PyInstaller's cache and the work directory before building.
    [switch]$Clean,
    # Sign the payload exe if a certificate is configured. Off by default: an unsigned
    # build runs, it just shows an unknown publisher.
    [switch]$Sign,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

$AppName = 'dti'
# A SCRIPT, because that is what PyInstaller freezes. Its -m is --manifest, so naming
# the module made it demand a scriptname it never got - and pointing it at the package's
# own __main__.py is how a package gets imported twice under two names.
$EntryScript = 'scripts\launch.py'

if ($Help) {
    Write-Host ''
    Write-Host '  build-app - freeze the app into a folder that needs no Python.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 build-app [-Released] [-Clean]'
    Write-Host ''
    Write-Host '  Writes dist\<name>-<version>\ and leaves build\ behind as scratch.'
    Write-Host '  VERSION is bundled as data because the header reads it at runtime.'
    Write-Host ''
    Write-Host '  Needs PyInstaller in the environment doing the build:'
    Write-Host '    python -m pip install pyinstaller'
    Write-Host ''
    exit 0
}

$root = Get-RepoRoot
$version = Get-AppVersion
$text = Format-AppVersion $version
$kind = if ($Released) { 'official' } else { 'debug' }

Write-Host ''
Write-Host "[1/5] Building $AppName $text ($kind)"

# The interpreter that is going to do the building, and the one whose packages get frozen.
# A checkout's own .venv where there is one, because that is where textual is - a global
# python would freeze an app missing its only dependency and only say so at runtime.
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

$probe = & $python -c "import PyInstaller, sys; sys.stdout.write(PyInstaller.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '  PyInstaller is not in the environment doing the build.' -ForegroundColor Red
    Write-Host "    $python -m pip install pyinstaller" -ForegroundColor Yellow
    Write-Host ''
    Write-Verbose "$probe"
    exit 1
}
Write-Host "[2/5] PyInstaller $probe"

# THE EXE IS NAMED FOR THE APP, THE FOLDER FOR THE VERSION.
#
# PyInstaller takes one --name and uses it for both, which gave a
# `dti-0.1.0+2.exe` - a command whose name changes every release. That is no use
# on PATH, which the installer now adds the install directory to, and it makes a
# Start Menu shortcut that breaks on every upgrade.
#
# So it freezes as `dti` into a scratch directory and the whole folder is moved to
# the versioned name. Moving the FOLDER rather than renaming the exe inside it:
# `_internal` is resolved relative to the executable, so the two travel together.
$outName = "$AppName-$text"
$dist = Join-Path $root 'dist'
$work = Join-Path $root 'build'
$staging = Join-Path $work 'frozen'
$target = Join-Path $dist $outName

if ($Clean -and (Test-Path -LiteralPath $target)) {
    Remove-Item -LiteralPath $target -Recurse -Force
}

# `;` is the separator on Windows - PyInstaller uses os.pathsep, and the ':' in every
# Linux example is a path on this platform, so "VERSION:." silently adds nothing.
$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--onedir',
    '--console',
    '--name', $AppName,
    '--distpath', $staging,
    '--workpath', $work,
    '--specpath', $work,
    '--add-data', "$(Join-Path $root 'VERSION');.",
    '--collect-all', 'textual',
    '--paths', $root,
    (Join-Path $root $EntryScript)
)
if ($Clean) { $arguments = @($arguments[0..1]) + @('--clean') + @($arguments[2..($arguments.Count - 1)]) }

Write-Host '[3/5] Freezing...'
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    Write-Host '  PyInstaller failed - its output is above.' -ForegroundColor Red
    exit 1
}

# Into place: the versioned folder is what the installer packages and what a second
# build of another version sits beside. Removed first, because Move-Item onto an
# existing directory nests the source inside it rather than replacing it.
$frozen = Join-Path $staging $AppName
if (-not (Test-Path -LiteralPath $frozen)) {
    Write-Host "  PyInstaller reported success but $frozen is not there." -ForegroundColor Red
    exit 1
}
if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dist | Out-Null
Move-Item -LiteralPath $frozen -Destination $target

# Asserted, not assumed. --add-data reports nothing when a source path is wrong, and the
# runtime fallback for a missing VERSION is a plausible-looking version number.
$bundled = @(Get-ChildItem -LiteralPath $target -Recurse -Filter 'VERSION' -File -ErrorAction SilentlyContinue)
if (-not $bundled.Count) {
    Write-Host '  VERSION did not make it into the bundle.' -ForegroundColor Red
    Write-Host '  The app would start and report v0.0.0+0, so this is a failure.' -ForegroundColor Yellow
    exit 1
}
Write-Host "[4/5] VERSION bundled at $($bundled[0].FullName.Substring($target.Length + 1))"

$exe = Join-Path $target "$AppName.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Host "  No $AppName.exe in $target." -ForegroundColor Red
    exit 1
}
# Signed here rather than only in build-installer: the exe inside the package is what
# people actually launch, and an unsigned payload inside a signed installer still warns.
if ($Sign) {
    . (Join-Path $PSScriptRoot 'lib\signing.ps1')
    $signed = Invoke-SignFile -Path $exe -Released:$Released -Description $AppName
    Write-SigningOutcome $signed "$AppName.exe"
}

$size = [math]::Round(((Get-ChildItem -LiteralPath $target -Recurse -File |
            Measure-Object -Property Length -Sum).Sum / 1MB), 1)

Write-Host "[5/5] $target  ($size MB)"
Write-Host ''
Write-Host "  Next: .\script.ps1 build-installer$(if ($Released) { ' -Released' })$(if ($Sign) { ' -Sign' })" -ForegroundColor DarkGray
Write-Host ''
exit 0
