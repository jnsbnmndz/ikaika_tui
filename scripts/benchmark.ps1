# Times the frozen app at each optimisation level and prints a comparison matrix.
#
# WHY THIS EXISTS
#
# The app has to start on low-end machines, and the only honest way to choose between
# build settings is to measure one against another on the machine that matters. A number
# quoted from somebody's blog is about their laptop.
#
# It times the SCRIPTABLE commands rather than the interactive one, because those are the
# ones that can be timed: `--version`, `list` and `doctor` start, do their work and exit.
# The TUI waits for a key, so wall-clock on it measures the person, not the program. What
# `--version` measures is the part every command pays - bootloader, _internal, interpreter
# start, and the import graph - which is exactly the part a slow machine feels.
#
# MEDIAN, NOT MEAN, AND A WARM-UP FIRST
#
# The first run of a freshly built tree pays for the filesystem cache; including it
# measures the disk. One mean outlier from a virus scanner moves an average and does not
# move a median.
#
# Requires PowerShell 7+ and PyInstaller.

[CmdletBinding()]
param(
    # Which levels to build and compare.
    [ValidateSet('0', '1', '2')]
    [string[]]$Levels = @('0', '1', '2'),
    # Runs per command per level, after a warm-up.
    [int]$Runs = 7,
    # Skip building and measure whatever is already under dist\.
    [switch]$NoBuild,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host ''
    Write-Host '  benchmark - time the frozen app at each optimisation level.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 benchmark [-Levels 0,1,2] [-Runs 7] [-NoBuild]'
    Write-Host ''
    Write-Host '  Builds dist\<name>-<version>-O<level>\ per level and prints a matrix.'
    Write-Host '  Times --version, list and doctor: the commands that start and exit.'
    Write-Host ''
    exit 0
}

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

$root = Split-Path -Parent $PSScriptRoot
$version = Format-AppVersion (Get-AppVersion)
$commands = @('--version', 'list', 'doctor')

function Measure-Command-Median {
    param([string]$Exe, [string]$Argument, [int]$Count)
    # Warm-up, discarded: the first run of a fresh tree measures the disk cache.
    & $Exe $Argument *> $null
    $times = 1..$Count | ForEach-Object {
        (Measure-Command { & $Exe $Argument *> $null }).TotalMilliseconds
    }
    $sorted = @($times | Sort-Object)
    [pscustomobject]@{
        Median = $sorted[[int]($sorted.Count / 2)]
        Min    = $sorted[0]
    }
}

$rows = @()
foreach ($level in $Levels) {
    $target = Join-Path $root "dist\dti-$version-O$level"

    if (-not $NoBuild) {
        Write-Host ""
        Write-Host "  building -O$level ..." -ForegroundColor DarkGray
        & (Join-Path $PSScriptRoot 'build-app.ps1') -Optimize $level -Clean *> $null
        if ($LASTEXITCODE -ne 0) { throw "build-app failed at -O$level" }
        # build-app always writes dist\dti-<version>; moved aside so the levels can sit
        # side by side and be re-measured without rebuilding.
        $built = Join-Path $root "dist\dti-$version"
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Move-Item $built $target
    }

    $exe = Join-Path $target 'dti.exe'
    if (-not (Test-Path $exe)) {
        Write-Host "  no build at $target - skipping -O$level" -ForegroundColor Yellow
        continue
    }

    $size = (Get-ChildItem $target -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
    $files = (Get-ChildItem $target -Recurse -File).Count
    $row = [ordered]@{ Level = "-O$level"; 'Size MB' = [math]::Round($size, 1); Files = $files }
    foreach ($command in $commands) {
        $result = Measure-Command-Median -Exe $exe -Argument $command -Count $Runs
        $row[$command] = [math]::Round($result.Median)
    }
    $rows += [pscustomobject]$row
}

Write-Host ""
Write-Host "  benchmark - dti $version, median of $Runs runs, milliseconds" -ForegroundColor Cyan
Write-Host ""
$rows | Format-Table -AutoSize

# The comparison is the point: a level that is not faster is a level not worth shipping.
if ($rows.Count -gt 1) {
    $baseline = $rows[0]
    foreach ($row in $rows[1..($rows.Count - 1)]) {
        $deltas = foreach ($command in $commands) {
            $change = $row.$command - $baseline.$command
            $percent = if ($baseline.$command) { 100 * $change / $baseline.$command } else { 0 }
            # The sign is written in rather than formatted: .NET alignment takes a signed
            # integer for padding, so "{0,+5}" is a parse error and not a plus sign.
            $sign = if ($change -gt 0) { '+' } else { '' }
            "{0} {1}{2:N0} ms ({3}{4:N1}%)" -f $command, $sign, $change, $sign, $percent
        }
        Write-Host "  $($row.Level) vs $($baseline.Level):  $($deltas -join '   ')"
    }
    Write-Host ""
}

if ($env:GITHUB_STEP_SUMMARY) {
    $summary = @("## Startup benchmark - $version", '', "Median of $Runs runs, milliseconds.", '')
    $summary += '| Level | Size MB | Files | ' + ($commands -join ' | ') + ' |'
    $summary += '|---|---|---|' + (($commands | ForEach-Object { '---' }) -join '|') + '|'
    foreach ($row in $rows) {
        $cells = $commands | ForEach-Object { $row.$_ }
        $summary += "| $($row.Level) | $($row.'Size MB') | $($row.Files) | " + ($cells -join ' | ') + ' |'
    }
    $summary -join "`n" | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Encoding utf8 -Append
}
