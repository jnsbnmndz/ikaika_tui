# Runs every check a push should pass - the gate, run the same way locally and in CI.
#
# The line above is what `.\script.ps1` prints beside this command's name: it reads the
# first comment line of each file, so that line has to be a whole sentence. It was two,
# and the listing showed half of one.
#
#     .\script.ps1 check-all                  everything
#     .\script.ps1 check-all -Build           and freeze the app, which is slow
#     .\script.ps1 check-all -InstallHook     run it automatically before every push
#
# GitHub Actions calls this file. That is the whole point: a workflow that lists its own
# steps in YAML is a second, silently diverging answer to "does this pass", and the one
# that matters is the one nobody can run locally.
#
#
# A MISSING DEV TOOL IS "SKIP", NOT "FAIL"
#
# ruff and PSScriptAnalyzer are reported as SKIP when they are not installed. A machine
# without a linter is not a broken repository, and a check that fails for being absent
# teaches people to pass -SkipLint, which is how a real failure gets ignored too.
#
# A FAILING TEST IS FAIL. The distinction is whether the repository is broken or the
# machine is incomplete.
#
# Every check runs even after one fails, and the summary at the end lists all of them.
# Stopping at the first failure means finding out about the second one on the next push.
#
# Requires PowerShell 7+.

[CmdletBinding()]
param(
    # Also freeze the app. Off by default: it takes minutes, and it is a packaging check
    # rather than a correctness one.
    [switch]$Build,
    # Skip the linters even when they are installed.
    [switch]$SkipLint,
    # Install this as .git/hooks/pre-push and exit.
    [switch]$InstallHook,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')
# For Get-ShareEnvPath and Read-EnvFile, used by the committed-credential check below.
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
    # sh, because that is what git runs on Windows too - it invokes hooks through its
    # bundled shell, not through cmd or PowerShell. A .ps1 here is never executed.
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

# name -> PASS | FAIL | SKIP, plus a note. Collected rather than printed as they happen,
# so the summary is one block instead of scattered through the output.
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

# --- the interpreter and the dependency it cannot run without ------------------------
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

# --- the tests -----------------------------------------------------------------------
# -b buffers stdout, because the terminal app's own output otherwise interleaves with
# the runner's. The count is parsed out of stderr, which is where unittest writes it.
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

# --- the version, which lives in three files that have to agree ----------------------
# uv.lock is the third and was the one nobody was watching: it records this project among
# the locked packages, version and all, and a release rewrote only the first two - so it
# sat a release behind saying 0.1.0+2 while VERSION said 0.0.1+1. Set-AppVersion writes
# all three now; this is what would notice if that stopped being true.
#
# A missing or nameless lock is not a failure. Not every checkout uses uv, and a project
# that has never been locked has nothing to disagree with.
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

# --- no credential in a committed file -----------------------------------------------
# The share links moved out of share.env, which is committed, and into signing.env, which
# is not (docs/decisions/0003-a-share-link-is-a-secret.md). A link put back into the
# committed half is a credential in every clone's history, and nothing else here would
# notice: the fetch works, the installer is signed, the run is green.
#
# FAIL rather than a warning. This is the repository being wrong, not the machine being
# incomplete, which is the line the whole SKIP/FAIL distinction above is drawn on.
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

# --- how the workflows call this file ------------------------------------------------
# A release run is the one path no local gate exercises, and the last one failed on
# argument passing rather than on anything a script does: an array splatted into
# script.ps1 arrives POSITIONALLY, so @('-Bump','minor') binds '-Bump' as the value of
# -Bump and leaves 'minor' homeless. A hashtable splat and a colon-bound switch are
# flattened the same way by the $args hop. Only tokens written at the call site survive.
#
# So this reads the workflows for the two spellings that do not work. Comment lines are
# skipped deliberately - release.yml's header shows the wrong shape on purpose, and a
# warning that trips the check it is warning about is a check nobody keeps.
#
# docs/pitfalls.md 6.1. Cheap regex rather than a YAML parser: this is one line shape in
# two files, and a parser would be a dependency for it.
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

# --- the linters, which are allowed to be absent -------------------------------------
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

    # Imported rather than probed with Get-Command: the module exposes cmdlets, not an
    # executable, so a Get-Command lookup for a binary name would always miss.
    $analyzer = Get-Module -ListAvailable -Name 'PSScriptAnalyzer' -ErrorAction SilentlyContinue
    if (-not $analyzer) {
        Add-Result 'PSScriptAnalyzer' 'SKIP' 'not installed - Install-Module PSScriptAnalyzer'
    } else {
        Import-Module PSScriptAnalyzer -ErrorAction Stop
        # -Settings, not -Severity: the settings file carries the excluded rules and the
        # reason for each. Passing severities here instead would silently re-enable them.
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

# --- packaging, only when asked ------------------------------------------------------
if ($Build) {
    $buildOutput = & (Join-Path $PSScriptRoot 'build-app.ps1') 2>&1
    if ($LASTEXITCODE -ne 0) {
        Add-Result 'build-app' 'FAIL' ''
        $buildOutput | Select-Object -Last 20 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    } else {
        Add-Result 'build-app' 'PASS' 'froze without error'
    }
} else {
    Add-Result 'build-app' 'SKIP' 'not asked for - pass -Build'
}

# --- the verdict ---------------------------------------------------------------------
$failed = @($results.Keys | Where-Object { $results[$_].State -eq 'FAIL' })
$skipped = @($results.Keys | Where-Object { $results[$_].State -eq 'SKIP' })

Write-Host ''
if ($failed.Count) {
    Write-Host "  FAILED: $($failed -join ', ')" -ForegroundColor Red
    Write-Host ''
    exit 1
}
# Skipped is reported, never omitted: "everything passed" when three checks never ran is
# the report that gets believed and should not be.
if ($skipped.Count) {
    Write-Host "  Passed. Skipped: $($skipped -join ', ')" -ForegroundColor Green
} else {
    Write-Host '  Passed - everything ran.' -ForegroundColor Green
}
Write-Host ''
exit 0
