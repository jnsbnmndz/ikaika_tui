# Times the frozen app across build variants and prints a comparison matrix.
#
# WHY THIS EXISTS
#
# The app has to start on low-end machines, and the only honest way to choose between
# build settings is to measure them against each other on the machine that matters. A
# number quoted from somebody's blog is about their laptop.
#
# It times the SCRIPTABLE commands rather than the interactive one, because those are the
# ones that can be timed: `--version`, `list` and `doctor` start, do their work and exit.
# The TUI waits for a key, so wall-clock on it measures the person. What `--version`
# measures is the part every command pays - bootloader, _internal, interpreter start and
# the import graph - which is exactly the part a slow machine feels.
#
#
# INTERLEAVED, AND THE MINIMUM IS THE ANSWER
#
# The first version measured all of -O0, then all of -O1, then all of -O2, and reported
# the median. Run twice it said -O1 was 2% faster and then that it was 19% faster, which
# is not a finding about -O1: it is something else on the machine waking up during one
# block. Measuring variants in blocks attributes whatever the machine was doing to
# whichever variant happened to be under the clock.
#
# So a round times every variant once, and the rounds repeat. Drift and background load
# now land on all of them together rather than on one.
#
# The reported figure is the MINIMUM, not the median. Nothing makes a process start faster
# than it can, so every millisecond above the floor is interference. The median of a noisy
# run measures the noise, and this table gets published.
#
# `Spread` is the honest part: the gap between a variant's fastest and slowest run. When
# the difference between two variants is smaller than that, the table says so rather than
# letting a reader infer a result the data does not support.
#
# Requires PowerShell 7+, PyInstaller, and uv when -Interpreter is used.

[CmdletBinding()]
param(
    # Which bytecode levels to build and compare.
    [ValidateSet('0', '1', '2')]
    [string[]]$Levels = @('0', '1', '2'),
    # Which CPython to freeze against, as a uv version spec. Empty is the checkout's .venv.
    [string]$Interpreter = '',
    # Rounds. Every variant is timed once per round, so this is runs-per-variant too.
    [int]$Runs = 9,
    # Measure what is already under dist\ instead of building.
    [switch]$NoBuild,
    # Write the table into README.md between the benchmark markers.
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

# --- build, or find, one tree per level ----------------------------------------------
$builds = [ordered]@{}
foreach ($level in $Levels) {
    $target = Join-Path $root "dist\dti-$version-O$level"
    if (-not $NoBuild) {
        Write-Host "  building -O$level ..." -ForegroundColor DarkGray
        $buildArgs = @('-Optimize', $level, '-Clean')
        if ($Interpreter) { $buildArgs += @('-Python', $Interpreter) }
        & (Join-Path $PSScriptRoot 'build-app.ps1') @buildArgs *> $null
        if ($LASTEXITCODE -ne 0) { throw "build-app failed at -O$level" }
        # build-app always writes dist\dti-<version>; moved aside so the variants sit side
        # by side and can be re-measured without rebuilding.
        $built = Join-Path $root "dist\dti-$version"
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Move-Item $built $target
    }
    # A release builds ONE variant and writes it to dist\dti-<version>, with no level in
    # the name. Falling back to it is what lets the workflow record the build it is about
    # to publish rather than needing three of them.
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

# Warm every tree before the clock starts. The first run of a fresh tree pays for the
# filesystem cache, and doing it here rather than inside the loop makes round one like
# every other round.
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

# --- the table ------------------------------------------------------------------------
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
# Milliseconds mean nothing without saying whose machine produced them, and a hosted
# runner is not the low-end laptop this whole exercise is about.
$where = if ($env:GITHUB_ACTIONS) { 'a GitHub runner' } else { 'a developer machine' }
$runtime = "$runtime, $where"

Write-Host ''
Write-Host "  benchmark - dti $version on $runtime" -ForegroundColor Cyan
Write-Host "  fastest of $Runs interleaved rounds, milliseconds" -ForegroundColor DarkGray
Write-Host ''
$rows | Format-Table -AutoSize

# The comparison is the point - and so is refusing to report one that is not there.
$verdict = ''
if ($rows.Count -gt 1) {
    $baseline = $rows[0]
    $largest = 0.0
    foreach ($row in $rows[1..($rows.Count - 1)]) {
        $deltas = foreach ($command in $commands) {
            $change = $row.$command - $baseline.$command
            $largest = [math]::Max($largest, [math]::Abs($change))
            # The sign is written in rather than formatted: .NET alignment takes a signed
            # integer for padding, so "{0,+5}" is a parse error and not a plus sign.
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

# --- the generated README section -----------------------------------------------------
#
# Written BETWEEN MARKERS, never appended: the section is generated, so it has to be
# replaceable or a release adds a table per version. The markers are HTML comments, which
# render as nothing and survive anybody editing the prose around them.
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
