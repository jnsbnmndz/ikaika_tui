# Gets this machine ready to run, test and build the app.
#
#     .\script.ps1 setup-dev-env [-Build] [-Lint]
#
# Tools the gate runs are declared in pyproject so `uv sync` installs them rather than
# pruning them - docs/pitfalls.md 3.4.

[CmdletBinding()]
param(
    [switch]$Build,
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

$packages = @('-e', $root)
if ($Build) { $packages += 'pyinstaller' }
if ($Lint) { $packages += 'ruff' }

Write-Host "[3/4] Installing: $($packages -join ' ')"
if ($uv) {
    & uv pip install --python $venvPython @packages
} else {
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install @packages
}
if ($LASTEXITCODE -ne 0) {
    Write-Host '  The install failed - its output is above.' -ForegroundColor Red
    exit 1
}

$probe = & $venvPython -c "import textual, company_tui, sys; sys.stdout.write(textual.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host '  Installed, but the packages do not import:' -ForegroundColor Red
    Write-Host "    $probe" -ForegroundColor DarkGray
    exit 1
}
Write-Host "[4/4] textual $probe, company_tui importable"

Write-Host ''
if ($Build) {
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
