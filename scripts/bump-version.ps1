# Releases this app: rewrites the version, commits it, and tags it.
#
#     .\script.ps1 bump-version -Bump patch                 a debug build's tag
#     .\script.ps1 bump-version -Bump minor -Released       an official release
#     .\script.ps1 bump-version -Bump keep                  rebuild, new build number
#     .\script.ps1 bump-version -Bump patch -WhatIf         say what it would do
#
# ONE COMMAND, RUN THE SAME WAY EVERYWHERE. GitHub Actions calls this file rather than
# reimplementing it in YAML, so what CI does and what a laptop does cannot drift: a
# workflow that bumps a version its own way is a second answer to what the version is.
#
# The tag is the distribution. `-Released` puts `-released` on it, which is how a release
# feed tells an official build from the debug tags the same source collected on its way
# there. Both spellings share one build number, because the number belongs to the source.
#
# NOTHING IS PUSHED. The commit and the tag are local, and the command prints the push
# line rather than running it: publishing is a decision, and a build tool that pushes on
# your behalf is one nobody can rehearse.
#
# Requires PowerShell 7+ and a clean tree - anything uncommitted would ride along in the
# release commit, which is how a half-finished change gets tagged as a version.

[CmdletBinding()]
param(
    # major, minor, patch, keep (or its older spelling, same), or an explicit x.y.z.
    [string]$Bump = 'patch',
    # Tag it as an official release rather than a debug build.
    [switch]$Released,
    # Do everything except write, commit and tag.
    [switch]$WhatIf,
    # Skip the confirmation. The checks still run.
    [switch]$Yes,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

if ($Help) {
    Write-Host ''
    Write-Host '  bump-version - rewrite the version, commit it, and tag it.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 bump-version [-Bump major|minor|patch|keep|x.y.z]'
    Write-Host '                              [-Released] [-WhatIf] [-Yes]'
    Write-Host ''
    Write-Host '  VERSION holds x.y.z+n and is the single source; pyproject.toml is'
    Write-Host '  rewritten to match. The build number rises globally and comes from'
    Write-Host '  the tags, so it is never handed out twice.'
    Write-Host ''
    Write-Host '  -Released tags v<x.y.z>-released instead of v<x.y.z>. Both share one'
    Write-Host '  build number - it belongs to the source, not to the kind of build.'
    Write-Host ''
    Write-Host '  Nothing is pushed. The push line is printed when it is done.'
    Write-Host ''
    exit 0
}

$root = Get-RepoRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '  git is not on PATH.' -ForegroundColor Red
    exit 1
}

$current = Get-AppVersion
$next = Resolve-NextVersion $Bump
$tag = Get-TagName $next -Released:$Released
$kind = if ($Released) { 'official release' } else { 'debug build' }

Write-Host ''
Write-Host "[1/5] Current: $(Format-AppVersion $current)"
Write-Host "[2/5] Next:    $(Format-AppVersion $next)  ->  $tag  ($kind)"

if (-not (Test-TagIsFree $tag)) {
    Write-Host "  $tag already exists. Nothing was changed." -ForegroundColor Red
    Write-Host '  Pick another version, or delete that tag deliberately.' -ForegroundColor Yellow
    exit 1
}
Write-Host "[3/5] $tag is free."

# Asked before anything is written. A release commit that carries somebody's unfinished
# work is a version tagged over a tree nobody reviewed.
$dirty = @(& git -C $root status --porcelain=v1 | Where-Object { $_ })
if ($dirty.Count -and -not $WhatIf) {
    Write-Host ''
    Write-Host "  $($dirty.Count) uncommitted change(s) - commit or stash them first:" -ForegroundColor Yellow
    foreach ($line in ($dirty | Select-Object -First 10)) { Write-Host "    $line" }
    exit 1
}

if ($WhatIf) {
    Write-Host ''
    Write-Host '  -WhatIf: nothing was written, committed or tagged.' -ForegroundColor DarkGray
    Write-Host "  It would have written $(Format-AppVersion $next) and tagged $tag."
    Write-Host ''
    exit 0
}

if (-not $Yes) {
    Write-Host ''
    $answer = Read-Host "  Tag $tag as a $kind? [y/N]"
    if ("$answer".Trim().ToLower() -notin @('y', 'yes')) {
        Write-Host '  Left alone.' -ForegroundColor DarkGray
        exit 0
    }
}

$touched = Set-AppVersion $next
Write-Host "[4/5] Written: $(($touched | ForEach-Object { Split-Path $_ -Leaf }) -join ', ')"

& git -C $root add -- $touched | Out-Null
& git -C $root commit -q -m "chore: release $tag" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  The release commit failed. VERSION is written but nothing is tagged.' -ForegroundColor Red
    exit 1
}
& git -C $root tag -a $tag -m "$kind $(Format-AppVersion $next)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  Tagging failed. The release commit is in place; tag it by hand.' -ForegroundColor Red
    exit 1
}

Write-Host "[5/5] Committed and tagged $tag."
Write-Host ''
Write-Host '  Local only. Push when ready:' -ForegroundColor DarkGray
Write-Host "    git push origin HEAD $tag" -ForegroundColor DarkGray
Write-Host ''
exit 0
