# Gets this machine ready to run, test and build the app.
#
#     .\script.ps1 setup-dev-env                 the virtualenv and the dependencies
#     .\script.ps1 setup-dev-env -Build          and the tools needed to package it
#     .\script.ps1 setup-dev-env -Lint           and the linters
#
# Idempotent: run it again after pulling and it installs whatever is newly needed and
# leaves the rest alone.
#
# GitHub Actions calls this file, which is why it has to work on a machine with nothing
# on it. A workflow that installs dependencies its own way in YAML is a second answer to
# what this project needs, and the runner is the only place it gets tested.
#
#
# uv IF IT IS THERE, pip IF IT IS NOT
#
# The repository is uv-managed - there is a uv.lock - so uv is the fast, exact path. But
# `.venv` created by uv has NO pip in it, so anything reaching for `python -m pip` inside
# that environment fails with "No module named pip", which is how PyInstaller came to be
# installed into the wrong interpreter once already. So: uv installs through `uv pip
# install --python .venv\Scripts\python.exe`, and the pip path is only for a machine
# without uv, where the venv is made by python itself and does have pip.
#
# Requires PowerShell 7+.

[CmdletBinding()]
param(
    # Also install PyInstaller, and say what else packaging needs.
    [switch]$Build,
    # Also install ruff, so check-all stops reporting SKIP for it.
    [switch]$Lint,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

if ($Help) {
    Write-Host ''
    Write-Host '  setup-dev-env - make this machine able to run, test and build the app.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 setup-dev-env [-Build] [-Lint]'
    Write-Host ''
    Write-Host '  Creates .venv and installs the project into it. Uses uv when it is'
    Write-Host '  present and pip when it is not - a uv-made venv has no pip in it.'
    Write-Host ''
    Write-Host '  -Build adds PyInstaller and reports whether NSIS and signtool are'
    Write-Host '  here; neither can be installed without a package manager, so it'
    Write-Host '  prints the winget line rather than pretending to.'
    Write-Host '  -Lint adds ruff.'
    Write-Host ''
    Write-Host '  Safe to run again. GitHub Actions runs this same file.'
    Write-Host ''
    exit 0
}

$root = Get-RepoRoot
$venv = Join-Path $root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

Write-Host ''
Write-Host "[1/4] $root"

$uv = Get-Command 'uv' -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($uv) {
        Write-Host '[2/4] Creating .venv with uv'
        & uv venv --directory $root
        if ($LASTEXITCODE -ne 0) { Write-Host '  uv venv failed.' -ForegroundColor Red; exit 1 }
    } else {
        $python = Get-Command 'python' -ErrorAction SilentlyContinue
        if (-not $python) {
            Write-Host ''
            Write-Host '  No python and no uv on this machine.' -ForegroundColor Red
            Write-Host '    winget install astral-sh.uv' -ForegroundColor Yellow
            Write-Host '    winget install Python.Python.3.13' -ForegroundColor Yellow
            Write-Host ''
            exit 1
        }
        Write-Host '[2/4] Creating .venv with python -m venv'
        & $python.Source -m venv $venv
        if ($LASTEXITCODE -ne 0) { Write-Host '  venv creation failed.' -ForegroundColor Red; exit 1 }
    }
} else {
    Write-Host '[2/4] .venv is already here'
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "  There is still no interpreter at $venvPython." -ForegroundColor Red
    exit 1
}

# A RUNNING COPY BLOCKS THE INSTALL, and the error it produces names neither the app nor
# the process. Reinstalling the package replaces the console-script launchers in
# .venv\Scripts, and Windows refuses to delete a .exe that is executing - so an open TUI
# in another terminal makes this fail with "failed to remove file ... Access is denied
# (os error 5)". That is a locked file, not a broken environment, so it is worth saying
# which process to close.
# Snapshotted into a plain object in the SAME pipeline, because Process.Path is a live
# read against the OS rather than a cached value: a process that exits between the filter
# and the report answers with an empty string, so the message named a pid and no path.
$scriptsDir = Join-Path $venv 'Scripts'
$holders = @(Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($scriptsDir, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { [pscustomobject]@{ Id = $_.Id; Path = $_.Path } })
if ($holders.Count) {
    Write-Host ''
    Write-Host '  Something from this .venv is still running, and Windows will not let the' -ForegroundColor Yellow
    Write-Host '  installer replace a file that is executing:' -ForegroundColor Yellow
    foreach ($holder in $holders) {
        Write-Host "    pid $($holder.Id)  $($holder.Path)" -ForegroundColor DarkGray
    }
    Write-Host '  Close it and run this again.' -ForegroundColor Yellow
    Write-Host ''
    exit 1
}

# Editable, so an edit to company_tui is picked up without reinstalling - and so the
# console entry points exist, which is what the tests import through.
$packages = @('-e', $root)
if ($Build) { $packages += 'pyinstaller' }
if ($Lint) { $packages += 'ruff' }

Write-Host "[3/4] Installing: $($packages -join ' ')"
if ($uv) {
    # --python, pointed at the venv's interpreter. Without it uv resolves an interpreter
    # of its own choosing and the packages land somewhere the build never looks.
    & uv pip install --python $venvPython @packages
} else {
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install @packages
}
if ($LASTEXITCODE -ne 0) {
    Write-Host '  The install failed - its output is above.' -ForegroundColor Red
    exit 1
}

# Asserted rather than assumed: an install can report success and still leave the import
# broken, and the next thing to notice would be a frozen app missing its only dependency.
$probe = & $venvPython -c "import textual, company_tui, sys; sys.stdout.write(textual.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host '  Installed, but the packages do not import:' -ForegroundColor Red
    Write-Host "    $probe" -ForegroundColor DarkGray
    exit 1
}
Write-Host "[4/4] textual $probe, company_tui importable"

Write-Host ''
if ($Build) {
    # Reported, not installed. Both are machine-wide installers that need elevation, and a
    # setup script that silently elevates is one nobody can predict.
    $nsis = @("${env:ProgramFiles(x86)}\NSIS\makensis.exe", "$env:ProgramFiles\NSIS\makensis.exe") |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if ($nsis) {
        Write-Host "  NSIS:     $nsis" -ForegroundColor DarkGray
    } else {
        Write-Host '  NSIS is not here - build-installer needs it.' -ForegroundColor Yellow
        Write-Host '    winget install NSIS.NSIS' -ForegroundColor DarkGray
    }

    . (Join-Path $PSScriptRoot 'lib\signing.ps1')
    $signtool = Find-SignTool
    if ($signtool) {
        Write-Host "  signtool: $signtool" -ForegroundColor DarkGray
    } else {
        Write-Host '  signtool is not here - builds work, artifacts will be unsigned.' -ForegroundColor Yellow
        Write-Host '    winget install Microsoft.WindowsSDK' -ForegroundColor DarkGray
    }
    Write-Host ''
}

Write-Host '  Next: .\script.ps1 check-all' -ForegroundColor DarkGray
Write-Host ''
exit 0
