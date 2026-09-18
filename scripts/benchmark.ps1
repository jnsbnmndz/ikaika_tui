# Times the frozen app across build variants and prints a comparison matrix.
#
#     .\script.ps1 benchmark [-Levels 0,1,2] [-Interpreter 3.14] [-Runs 9] [-UpdateReadme]
#
# INTERLEAVED, and the MINIMUM is the answer. Measuring all of one variant then all of the
# next charges whatever the machine was doing to whichever was under the clock - that
# turned a 2% difference into a 19% one between two runs. A round times every variant
# once and the rounds repeat. Nothing starts faster than it can, so the floor is the
# signal and everything above it is interference; the spread between repeat runs is
# printed, and a difference smaller than it is reported as no result.
#
# -UpdateReadme writes the table into README.md between the benchmark markers. The release
# workflow runs it after the build and before the push, so a published number describes
# the build being published.

[CmdletBinding()]
param(
    [ValidateSet('0', '1', '2')]
    [string[]]$Levels = @('0', '1', '2'),
    [string]$Interpreter = '',
    [int]$Runs = 9,
    [switch]$NoBuild,
    [switch]$UpdateReadme,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Host ''
    Write-Host '  benchmark - time the frozen app across build variants.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 benchmark [-Levels 0,1,2] [-Interpreter 3.14] [-Runs 9]'
    Write-Host '                           [-NoBuild] [-UpdateReadme]'
    Write-Host ''
    Write-Host '  Builds dist\<name>-<version>-O<level>\ per level, times --version, list'
    Write-Host '  and doctor, and reports the fastest run of each - interleaved, so'
    Write-Host '  background load does not land on whichever variant was under the clock.'
    Write-Host ''
    exit 0
}

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

$root = Split-Path -Parent $PSScriptRoot
$version = Format-AppVersion (Get-AppVersion)
$commands = @('--version', 'list', 'doctor')

$builds = [ordered]@{}
foreach ($level in $Levels) {
    $target = Join-Path $root "dist\dti-$version-O$level"
    if (-not $NoBuild) {
        Write-Host "  building -O$level ..." -ForegroundColor DarkGray
        $buildArgs = @('-Optimize', $level, '-Clean')
        if ($Interpreter) { $buildArgs += @('-Python', $Interpreter) }
        & (Join-Path $PSScriptRoot 'build-app.ps1') @buildArgs *> $null
        if ($LASTEXITCODE -ne 0) { throw "build-app failed at -O$level" }
        $built = Join-Path $root "dist\dti-$version"
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Move-Item $built $target
    }
    $exe = Join-Path $target 'dti.exe'
    if (-not (Test-Path $exe)) {
        $plain = Join-Path $root "dist\dti-$version\dti.exe"
        if ($NoBuild -and $Levels.Count -eq 1 -and (Test-Path $plain)) { $exe = $plain }
    }
    if (Test-Path $exe) {
        $builds["-O$level"] = $exe
    } else {
        Write-Host "  no build at $target - skipping -O$level" -ForegroundColor Yellow
    }
}
if ($builds.Count -eq 0) { throw 'nothing to measure' }

foreach ($exe in $builds.Values) {
    foreach ($command in $commands) { & $exe $command *> $null }
}

$samples = @{}
foreach ($name in $builds.Keys) {
    foreach ($command in $commands) { $samples["$name|$command"] = @() }
}
Write-Host "  timing $($builds.Count) build(s) x $($commands.Count) commands x $Runs rounds ..." -ForegroundColor DarkGray
foreach ($round in 1..$Runs) {
    foreach ($name in $builds.Keys) {
        foreach ($command in $commands) {
            $elapsed = (Measure-Command { & $builds[$name] $command *> $null }).TotalMilliseconds
            $samples["$name|$command"] += $elapsed
        }
    }
}

$rows = @()
$spread = 0.0
foreach ($name in $builds.Keys) {
    $tree = Split-Path -Parent $builds[$name]
    $size = (Get-ChildItem $tree -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
    $row = [ordered]@{ Build = $name; 'Size MB' = [math]::Round($size, 1) }
    foreach ($command in $commands) {
        $times = @($samples["$name|$command"] | Sort-Object)
        $row[$command] = [math]::Round($times[0])
        $spread = [math]::Max($spread, $times[-1] - $times[0])
    }
    $rows += [pscustomobject]$row
}

$runtime = if ($Interpreter) { "CPython $Interpreter" } else {
    "CPython $(& (Join-Path $root '.venv\Scripts\python.exe') -c 'import platform;print(platform.python_version())')"
}
$where = if ($env:GITHUB_ACTIONS) { 'a GitHub runner' } else { 'a developer machine' }
$runtime = "$runtime, $where"

Write-Host ''
Write-Host "  benchmark - dti $version on $runtime" -ForegroundColor Cyan
Write-Host "  fastest of $Runs interleaved rounds, milliseconds" -ForegroundColor DarkGray
Write-Host ''
$rows | Format-Table -AutoSize

$verdict = ''
if ($rows.Count -gt 1) {
    $baseline = $rows[0]
    $largest = 0.0
    foreach ($row in $rows[1..($rows.Count - 1)]) {
        $deltas = foreach ($command in $commands) {
            $change = $row.$command - $baseline.$command
            $largest = [math]::Max($largest, [math]::Abs($change))
            $sign = if ($change -gt 0) { '+' } else { '' }
            "{0} {1}{2:N0} ms" -f $command, $sign, $change
        }
        Write-Host "  $($row.Build) vs $($baseline.Build):  $($deltas -join '   ')"
    }
    $roundedSpread = [math]::Round($spread)
    $roundedLargest = [math]::Round($largest)
    $verdict = if ($largest -lt $spread) {
        "Every difference here is smaller than the $roundedSpread ms spread between repeat runs of one build, so none of it is a result."
    } else {
        "Largest difference $roundedLargest ms, against a $roundedSpread ms spread between repeat runs of one build."
    }
    Write-Host ''
    Write-Host "  $verdict" -ForegroundColor DarkGray
    Write-Host ''
}

if ($UpdateReadme) {
    $readme = Join-Path $root 'README.md'
    $startMark = '<!-- benchmark:start -->'
    $endMark = '<!-- benchmark:end -->'
    $text = Get-Content -LiteralPath $readme -Raw
    $startAt = $text.IndexOf($startMark)
    $endAt = $text.IndexOf($endMark)
    if ($startAt -lt 0 -or $endAt -lt $startAt) {
        Write-Host '  README.md has no benchmark markers - nothing written.' -ForegroundColor Yellow
    } else {
        $table = @()
        $table += "``dti $version`` on $runtime, fastest of $Runs interleaved rounds, in milliseconds."
        $table += ''
        $table += '| Build | Size MB | ' + ($commands -join ' | ') + ' |'
        $table += '|---|---|' + (($commands | ForEach-Object { '---' }) -join '|') + '|'
        foreach ($row in $rows) {
            $cells = $commands | ForEach-Object { $row.$_ }
            $table += "| ``$($row.Build)`` | $($row.'Size MB') | " + ($cells -join ' | ') + ' |'
        }
        if ($verdict) { $table += ''; $table += "_$($verdict)_" }
        $table += ''
        $table += '_Generated by `.\script.ps1 benchmark -UpdateReadme`; do not edit by hand._'
        $body = $startMark + "`n" + ($table -join "`n") + "`n" + $endMark
        $updated = $text.Substring(0, $startAt) + $body + $text.Substring($endAt + $endMark.Length)
        Set-Content -LiteralPath $readme -Value $updated -NoNewline -Encoding utf8
        Write-Host '  README.md updated between the benchmark markers.' -ForegroundColor DarkGray
    }
}

if ($env:GITHUB_STEP_SUMMARY) {
    $summary = @("## Startup benchmark - $version on $runtime", '',
                 "Fastest of $Runs interleaved rounds, milliseconds.", '')
    $summary += '| Build | Size MB | ' + ($commands -join ' | ') + ' |'
    $summary += '|---|---|' + (($commands | ForEach-Object { '---' }) -join '|') + '|'
    foreach ($row in $rows) {
        $cells = $commands | ForEach-Object { $row.$_ }
        $summary += "| $($row.Build) | $($row.'Size MB') | " + ($cells -join ' | ') + ' |'
    }
    if ($verdict) { $summary += ''; $summary += $verdict }
    $summary -join "`n" | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Encoding utf8 -Append
}
