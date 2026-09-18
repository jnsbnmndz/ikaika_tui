# Releases this app: rewrites the version, commits it, and tags it.
#
#     .\script.ps1 bump-version -Bump patch|minor|major|keep [-Released] [-WhatIf] [-Yes]
#
# The tag is the distribution, and the build number comes from the tags rather than from
# VERSION - an installer compares it, so a reset makes an upgrade look older. Commits and
# tags; never pushes. See docs/decisions/0002.

[CmdletBinding()]
param(
    [string]$Bump = 'patch',
    [switch]$Released,
    [switch]$WhatIf,
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
