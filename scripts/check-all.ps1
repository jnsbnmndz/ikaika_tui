# Runs every check a push should pass - the gate, the same locally and in CI.
#
#     .\script.ps1 check-all [-Build] [-InstallHook]
#
# A skip is REPORTED, never omitted, and a check that stops checking is a failure: an
# empty test discovery is FAIL. docs/pitfalls.md 3.1 and 3.4 are why. -Build also starts
# the frozen exe, because a freeze that succeeds is not a build that runs.

[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$SkipLint,
    [switch]$InstallHook,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')
. (Join-Path $PSScriptRoot 'lib\signing.ps1')

if ($Help) {
    Write-Host ''
    Write-Host '  check-all - every check a push should pass.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 check-all [-Build] [-SkipLint] [-InstallHook]'
    Write-Host ''
    Write-Host '  Runs the tests, the linters, and the version consistency check. A'
    Write-Host '  linter that is not installed reports SKIP - a missing dev tool is'
    Write-Host '  not a broken repository. A failing test reports FAIL.'
    Write-Host ''
    Write-Host '  -Build also freezes the app, which takes minutes.'
    Write-Host '  -InstallHook wires this into git as a pre-push hook.'
    Write-Host ''
    Write-Host '  GitHub Actions calls this same file, so CI and a laptop cannot'
    Write-Host '  disagree about what passing means.'
    Write-Host ''
    exit 0
}

$root = Get-RepoRoot

if ($InstallHook) {
    $hooksDir = Join-Path $root '.git\hooks'
    if (-not (Test-Path -LiteralPath $hooksDir)) {
        Write-Host "  No .git\hooks at $hooksDir - is this a git checkout?" -ForegroundColor Red
        exit 1
    }
    $hook = Join-Path $hooksDir 'pre-push'
    $lines = @(
        '#!/bin/sh',
        '# Installed by scripts/check-all.ps1 -InstallHook.',
        '# Skip once with: git push --no-verify',
        'exec pwsh -NoProfile -File "$(git rev-parse --show-toplevel)/script.ps1" check-all'
    )
    [IO.File]::WriteAllText($hook, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
    Write-Host ''
    Write-Host "  Installed $hook" -ForegroundColor Green
    Write-Host '  Every push now runs check-all first. git push --no-verify skips it.' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

$results = [ordered]@{}
function Add-Result([string]$Name, [string]$State, [string]$Note = '') {
    $results[$Name] = @{ State = $State; Note = $Note }
    $colour = switch ($State) { 'PASS' { 'Green' } 'FAIL' { 'Red' } default { 'DarkGray' } }
    Write-Host "  $($State.PadRight(4))  $Name" -NoNewline -ForegroundColor $colour
    if ($Note) { Write-Host "  $Note" -ForegroundColor DarkGray } else { Write-Host '' }
}

Write-Host ''
Write-Host "  check-all - $root"
Write-Host ''

$pythonVersion = & $python -c "import sys; sys.stdout.write('.'.join(map(str, sys.version_info[:3])))" 2>&1
if ($LASTEXITCODE -ne 0) {
    Add-Result 'python' 'FAIL' 'no interpreter'
} else {
    Add-Result 'python' 'PASS' "$pythonVersion at $(Split-Path -Leaf (Split-Path -Parent $python))"
}

& $python -c "import textual, sys; sys.stdout.write(textual.__version__)" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Add-Result 'textual' 'FAIL' "not importable - run: uv sync, or $python -m pip install -e ."
} else {
    $textualVersion = & $python -c "import textual, sys; sys.stdout.write(textual.__version__)" 2>&1
    Add-Result 'textual' 'PASS' "$textualVersion"
}

$testOutput = & $python -m unittest discover -s tests -b 2>&1
$testExit = $LASTEXITCODE
$ran = ''
if ("$testOutput" -match 'Ran (\d+) test') { $ran = "$($Matches[1]) tests" }
if ($testExit -ne 0) {
    Add-Result 'tests' 'FAIL' $ran
    Write-Host ''
    $testOutput | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    Write-Host ''
} else {
    Add-Result 'tests' 'PASS' $ran
}

try {
    $version = Get-AppVersion
    $text = Format-AppVersion $version
    $pyprojectVersion = ''
    foreach ($line in (Get-Content -LiteralPath (Get-PyProjectFile))) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"') { $pyprojectVersion = $Matches[1]; break }
    }
    $lockVersion = Get-LockVersionText

    $disagree = @()
    if ($pyprojectVersion -ne $text) { $disagree += "pyproject says $pyprojectVersion" }
    if ($lockVersion -and $lockVersion -ne $text) { $disagree += "uv.lock says $lockVersion" }

    if ($disagree.Count) {
        Add-Result 'version' 'FAIL' "VERSION says $text, $($disagree -join ', ')"
    } elseif (-not $lockVersion) {
        Add-Result 'version' 'PASS' "$text (no uv.lock entry to check)"
    } else {
        Add-Result 'version' 'PASS' $text
    }
} catch {
    Add-Result 'version' 'FAIL' $_.Exception.Message
}

try {
    $committed = Read-EnvFile (Get-ShareEnvPath)
    $leaked = @(@('share.cert', 'share.debugCert') | Where-Object { $committed[$_] })
    if ($leaked.Count) {
        Add-Result 'secrets' 'FAIL' "$($leaked -join ', ') set in a committed share.env - run setup-signing to move them, then rotate"
    } else {
        Add-Result 'secrets' 'PASS' 'no share link in a committed file'
    }
} catch {
    Add-Result 'secrets' 'FAIL' $_.Exception.Message
}

$workflowDir = Join-Path $root '.github\workflows'
if (-not (Test-Path -LiteralPath $workflowDir)) {
    Add-Result 'workflow calls' 'SKIP' 'no .github\workflows here'
} else {
    $offenders = @()
    foreach ($file in Get-ChildItem -LiteralPath $workflowDir -Filter '*.yml') {
        $number = 0
        foreach ($line in (Get-Content -LiteralPath $file.FullName)) {
            $number++
            $text = "$line"
            if ($text -match '^\s*#') { continue }
            if ($text -notmatch 'script\.ps1\s+[\w-]+') { continue }
            if ($text -match '@\w+' -or $text -match '\s-\w+:') {
                $offenders += "$($file.Name):$number"
            }
        }
    }
    if ($offenders.Count) {
        Add-Result 'workflow calls' 'FAIL' "splatted or colon-bound arguments at $($offenders -join ', ') - script.ps1 takes literal tokens only"
    } else {
        Add-Result 'workflow calls' 'PASS' 'literal tokens only'
    }
}

if ($SkipLint) {
    Add-Result 'ruff' 'SKIP' 'asked for with -SkipLint'
    Add-Result 'PSScriptAnalyzer' 'SKIP' 'asked for with -SkipLint'
} else {
    $ruff = Get-Command 'ruff' -ErrorAction SilentlyContinue
    $ruffExe = Join-Path $root '.venv\Scripts\ruff.exe'
    if (Test-Path -LiteralPath $ruffExe) { $ruffPath = $ruffExe }
    elseif ($ruff) { $ruffPath = $ruff.Source }
    else { $ruffPath = '' }

    if (-not $ruffPath) {
        Add-Result 'ruff' 'SKIP' 'not installed - uv add --dev ruff'
    } else {
        $ruffOut = & $ruffPath check company_tui tests 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-Result 'ruff' 'FAIL' ''
            $ruffOut | Select-Object -First 30 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
        } else {
            Add-Result 'ruff' 'PASS' ''
        }
    }

    $analyzer = Get-Module -ListAvailable -Name 'PSScriptAnalyzer' -ErrorAction SilentlyContinue
    if (-not $analyzer) {
        Add-Result 'PSScriptAnalyzer' 'SKIP' 'not installed - Install-Module PSScriptAnalyzer'
    } else {
        Import-Module PSScriptAnalyzer -ErrorAction Stop
        $settings = Join-Path $PSScriptRoot 'PSScriptAnalyzerSettings.psd1'
        $found = @(Invoke-ScriptAnalyzer -Path (Join-Path $root 'scripts') -Recurse -Settings $settings -ErrorAction SilentlyContinue)
        $found += @(Invoke-ScriptAnalyzer -Path (Join-Path $root 'script.ps1') -Settings $settings -ErrorAction SilentlyContinue)
        if ($found.Count) {
            Add-Result 'PSScriptAnalyzer' 'FAIL' "$($found.Count) findings"
            $found | Select-Object -First 20 | ForEach-Object {
                Write-Host "        $($_.ScriptName):$($_.Line) $($_.RuleName) - $($_.Message)" -ForegroundColor DarkGray
            }
        } else {
            Add-Result 'PSScriptAnalyzer' 'PASS' ''
        }
    }
}

if ($Build) {
    $buildOutput = & (Join-Path $PSScriptRoot 'build-app.ps1') 2>&1
    if ($LASTEXITCODE -ne 0) {
        Add-Result 'build-app' 'FAIL' ''
        $buildOutput | Select-Object -Last 20 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    } else {
        $frozen = Get-ChildItem -Path (Join-Path $root 'dist') -Filter '*.exe' -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -like 'dti-*' } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if (-not $frozen) {
            Add-Result 'build-app' 'FAIL' 'froze, but no exe under dist'
        } else {
            $started = & $frozen.FullName --version 2>&1
            if ($LASTEXITCODE -ne 0) {
                Add-Result 'build-app' 'FAIL' "froze, but $($frozen.Name) does not start"
                $started | Select-Object -Last 20 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
            } else {
                Add-Result 'build-app' 'PASS' "froze and starts - $($started | Select-Object -First 1)"
            }
        }
    }
} else {
    Add-Result 'build-app' 'SKIP' 'not asked for - pass -Build'
}

$failed = @($results.Keys | Where-Object { $results[$_].State -eq 'FAIL' })
$skipped = @($results.Keys | Where-Object { $results[$_].State -eq 'SKIP' })

if ($env:GITHUB_STEP_SUMMARY) {
    $summary = @()
    $summary += if ($failed.Count) { "## Gate failed: $($failed -join ', ')" } else { '## Gate passed' }
    $summary += ''
    $summary += '| | Check | Note |'
    $summary += '|---|---|---|'
    foreach ($name in $results.Keys) {
        $note = "$($results[$name].Note)".Replace('|', '\|')
        $summary += "| $($results[$name].State) | $name | $note |"
    }
    if ($skipped.Count) {
        $summary += ''
        $summary += "Skipped: $($skipped -join ', ')."
    }
    $summary -join "`n" | Out-File $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}

Write-Host ''
if ($failed.Count) {
    Write-Host "  FAILED: $($failed -join ', ')" -ForegroundColor Red
    Write-Host ''
    exit 1
}
if ($skipped.Count) {
    Write-Host "  Passed. Skipped: $($skipped -join ', ')" -ForegroundColor Green
} else {
    Write-Host '  Passed - everything ran.' -ForegroundColor Green
}
Write-Host ''
exit 0
