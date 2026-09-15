# Freezes the app into a folder that runs without Python installed.
#
#     .\script.ps1 build-app [-Released] [-Clean] [-Sign] [-Optimize 0|1|2] [-Python 3.14]
#
# Writes dist\<name>-<version>\ and leaves build\ as scratch. Onedir, not onefile: the
# installer copies a directory, and `_internal` is found by directory rather than by exe
# name. VERSION is added as data because a frozen app has no repository to read it from,
# and the build asserts it arrived rather than trusting the flag.
#
# -Optimize and -Python are levers to be measured, not assumed: scriptsenchmark.ps1.

[CmdletBinding()]
param(
    [switch]$Released,
    [switch]$Clean,
    [switch]$Sign,
    [ValidateSet('0', '1', '2')]
    [string]$Optimize = '0',
    [string]$Python = '',
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

$AppName = 'dti'
$EntryScript = 'scripts\launch.py'

if ($Help) {
    Write-Host ''
    Write-Host '  build-app - freeze the app into a folder that needs no Python.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 build-app [-Released] [-Clean] [-Sign] [-Optimize 0|1|2]'
    Write-Host ''
    Write-Host '  Writes dist\<name>-<version>\ and leaves build\ behind as scratch.'
    Write-Host '  VERSION is bundled as data because the header reads it at runtime.'
    Write-Host '  -Optimize is bytecode level: 1 drops asserts, 2 also drops docstrings.'
    Write-Host '  scripts\benchmark.ps1 measures one level against another.'
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
Write-Host "[1/5] Building $AppName $text ($kind, -O$Optimize)"

$interpreter = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $interpreter)) { $interpreter = 'python' }

$launcher = $interpreter
$prefix = @()
if ($Python) {
    if (-not (Get-Command 'uv' -ErrorAction SilentlyContinue)) {
        Write-Host ''
        Write-Host "  -Python $Python needs uv, which is not on PATH." -ForegroundColor Red
        Write-Host '    https://docs.astral.sh/uv/' -ForegroundColor Yellow
        Write-Host ''
        exit 1
    }
    $launcher = 'uv'
    $prefix = @('run', '--python', $Python, '--no-project',
                '--with', 'pyinstaller', '--with', 'textual>=8.2,<9', '--', 'python')
}

$probe = @(& $launcher @prefix -c "import PyInstaller, sys; sys.stdout.write(PyInstaller.__version__)" 2>&1)
$version_line = "$($probe | Where-Object { "$_".Trim() } | Select-Object -Last 1)".Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '  PyInstaller is not in the environment doing the build.' -ForegroundColor Red
    Write-Host "    $interpreter -m pip install pyinstaller" -ForegroundColor Yellow
    Write-Host ''
    Write-Verbose "$probe"
    exit 1
}
Write-Host "[2/5] PyInstaller $version_line$(if ($Python) { " on CPython $Python" })"

$outName = "$AppName-$text"
$dist = Join-Path $root 'dist'
$work = Join-Path $root 'build'
$staging = Join-Path $work 'frozen'
$target = Join-Path $dist $outName

if ($Clean -and (Test-Path -LiteralPath $target)) {
    Remove-Item -LiteralPath $target -Recurse -Force
}

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
    '--optimize', $Optimize,
    (Join-Path $root $EntryScript)
)
if ($Clean) { $arguments = @($arguments[0..1]) + @('--clean') + @($arguments[2..($arguments.Count - 1)]) }

Write-Host '[3/5] Freezing...'
& $launcher @prefix @arguments
if ($LASTEXITCODE -ne 0) {
    Write-Host '  PyInstaller failed - its output is above.' -ForegroundColor Red
    exit 1
}

$frozen = Join-Path $staging $AppName
if (-not (Test-Path -LiteralPath $frozen)) {
    Write-Host "  PyInstaller reported success but $frozen is not there." -ForegroundColor Red
    exit 1
}
if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dist | Out-Null
Move-Item -LiteralPath $frozen -Destination $target

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
