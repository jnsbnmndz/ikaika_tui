# Reports any GitHub Action this repository uses that is behind its latest release.
#
#     .\script.ps1 check-actions
#
# Here rather than a third-party action: the one that did this was a Docker container
# action whose base image aged out, and it could not be patched from outside.
# docs/pitfalls.md 8.1. A lookup that fails is `unknown` and does not fail the job -
# a version check that guesses is worse than one that abstains.

[CmdletBinding()]
param(
    [switch]$Quiet,
    [switch]$NoFail,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\app-version.ps1')

if ($Help) {
    Write-Host ''
    Write-Host '  check-actions - which actions in .github/workflows are behind.'
    Write-Host ''
    Write-Host '  Usage'
    Write-Host '    .\script.ps1 check-actions [-Quiet] [-NoFail]'
    Write-Host ''
    Write-Host '  Reads every `uses:` in .github/workflows, asks GitHub for each'
    Write-Host '  action''s latest release, and fails if one has moved on. A tag pin'
    Write-Host '  is current while the newest release shares its major; a SHA pin is'
    Write-Host '  read through the `# vX.Y.Z` comment beside it.'
    Write-Host ''
    Write-Host '  Needs no token when the actions are public. gh is used when it is'
    Write-Host '  present, so a run inside Actions is authenticated and not rate'
    Write-Host '  limited; otherwise the public API is called unauthenticated.'
    Write-Host ''
    exit 0
}

$root = Get-RepoRoot
$workflowDir = Join-Path $root '.github\workflows'

if (-not (Test-Path -LiteralPath $workflowDir)) {
    Write-Host ''
    Write-Host "  There is no $workflowDir." -ForegroundColor Yellow
    Write-Host ''
    exit 0
}

function Get-ActionReference {
    $found = @{}
    foreach ($file in Get-ChildItem -LiteralPath $workflowDir -Filter '*.yml') {
        $number = 0
        foreach ($line in (Get-Content -LiteralPath $file.FullName)) {
            $number++
            $text = "$line"
            if ($text -match '^\s*#') { continue }
            if ($text -notmatch '^\s*-?\s*uses:\s*([^\s#]+)\s*(#\s*(.+))?$') { continue }

            $reference = $Matches[1].Trim()
            $comment = if ($Matches[3]) { $Matches[3].Trim() } else { '' }
            if ($reference.StartsWith('./') -or $reference.StartsWith('docker://')) { continue }
            if ($reference -notmatch '^([^/]+/[^/@]+)(/[^@]+)?@(.+)$') { continue }

            $name = $Matches[1]
            $ref = $Matches[3]
            $key = "$name@$ref"
            if ($found.ContainsKey($key)) {
                $found[$key].Places += ", $($file.Name):$number"
                continue
            }
            $found[$key] = [ordered]@{
                Name    = $name
                Ref     = $ref
                Comment = $comment
                Places  = "$($file.Name):$number"
            }
        }
    }
    return $found.Values
}

function Get-LatestTag([string]$Name) {
    $gh = Get-Command 'gh' -ErrorAction SilentlyContinue
    if ($gh) {
        $tag = & gh api "repos/$Name/releases/latest" --jq '.tag_name' 2>$null
        if ($LASTEXITCODE -eq 0 -and $tag) { return "$tag".Trim() }
        return ''
    }
    try {
        $answer = Invoke-RestMethod -Uri "https://api.github.com/repos/$Name/releases/latest" `
            -Headers @{ 'User-Agent' = 'dti-check-actions' } -TimeoutSec 20
        return "$($answer.tag_name)".Trim()
    } catch {
        return ''
    }
}

function Get-Standing([hashtable]$Action, [string]$Latest) {
    if (-not $Latest) { return 'unknown' }

    $pinned = $Action.Ref
    if ($pinned -match '^[0-9a-f]{40}$') {
        if (-not $Action.Comment) { return 'unknown' }
        $pinned = ($Action.Comment -split '\s+')[0]
    }

    if ($pinned -eq $Latest) { return 'current' }
    if ($Latest.StartsWith("$pinned.")) { return 'current' }
    return 'behind'
}

Write-Host ''
Write-Host "  check-actions - $workflowDir"
Write-Host ''

$rows = @()
foreach ($action in (Get-ActionReference | Sort-Object { $_.Name })) {
    $latest = Get-LatestTag $action.Name
    $standing = Get-Standing $action $latest
    $rows += [ordered]@{
        Name     = $action.Name
        Pinned   = $action.Ref
        Comment  = $action.Comment
        Latest   = $latest
        Standing = $standing
        Places   = $action.Places
    }
}

if (-not $rows.Count) {
    Write-Host '  No action references found.' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}

$behind = @($rows | Where-Object { $_.Standing -eq 'behind' })
$unknown = @($rows | Where-Object { $_.Standing -eq 'unknown' })

foreach ($row in $rows) {
    if ($Quiet -and $row.Standing -ne 'behind') { continue }
    $shown = if ($row.Comment) { "$($row.Pinned.Substring(0, [Math]::Min(7, $row.Pinned.Length))) ($($row.Comment))" } else { $row.Pinned }
    $colour = switch ($row.Standing) { 'behind' { 'Yellow' } 'unknown' { 'DarkGray' } default { 'Green' } }
    Write-Host "  $($row.Standing.PadRight(8))" -NoNewline -ForegroundColor $colour
    Write-Host "$($row.Name.PadRight(46)) $shown" -NoNewline
    if ($row.Standing -eq 'behind') { Write-Host "  ->  $($row.Latest)" -ForegroundColor Yellow }
    else { Write-Host '' }
}

if ($env:GITHUB_STEP_SUMMARY) {
    $lines = @()
    $lines += if ($behind.Count) { "## $($behind.Count) action(s) behind" } else { '## Every action is current' }
    $lines += ''
    $lines += '| | Action | Pinned | Latest | Used in |'
    $lines += '|---|---|---|---|---|'
    foreach ($row in $rows) {
        $mark = switch ($row.Standing) { 'behind' { 'behind' } 'unknown' { 'unknown' } default { 'current' } }
        $pinned = if ($row.Comment) { "``$($row.Pinned)`` ($($row.Comment))" } else { "``$($row.Pinned)``" }
        $latest = if ($row.Latest) { "``$($row.Latest)``" } else { '-' }
        $lines += "| $mark | ``$($row.Name)`` | $pinned | $latest | $($row.Places) |"
    }
    if ($behind.Count) {
        $lines += ''
        $lines += 'Dependabot opens the pull requests for these. This job exists to say so when one was never merged.'
    }
    if ($unknown.Count) {
        $lines += ''
        $lines += '`unknown` is a lookup that failed or a SHA pin with no `# vX.Y.Z` comment beside it. Neither fails this job.'
    }
    $lines -join "`n" | Out-File $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}

Write-Host ''
if ($unknown.Count) {
    Write-Host "  Could not check: $(($unknown | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor DarkGray
}
if ($behind.Count) {
    Write-Host "  BEHIND: $(($behind | ForEach-Object { "$($_.Name) -> $($_.Latest)" }) -join ', ')" -ForegroundColor Yellow
    Write-Host ''
    if ($NoFail) { exit 0 }
    exit 1
}
Write-Host '  Every action is current.' -ForegroundColor Green
Write-Host ''
exit 0
