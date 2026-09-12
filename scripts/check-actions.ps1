# Reports any GitHub Action this repository uses that is behind its latest release.
#
#     .\script.ps1 check-actions              report, and fail if anything is behind
#     .\script.ps1 check-actions -Quiet       report only what is behind
#
# The half of keeping actions current that notices when nobody merged a pull request.
# Dependabot (.github/dependabot.yml) opens them; this says so out loud when one was never
# merged, or when Dependabot has been switched off in the repository settings. A pull
# request nobody opened is indistinguishable from nothing being out of date.
#
#
# WHY THIS IS A SCRIPT AND NOT A MARKETPLACE ACTION
#
# It was one - saadmk11/github-actions-version-updater, pinned to a SHA, in check-only
# mode. It is a DOCKER CONTAINER action, so every run builds its image from the
# Dockerfile at that SHA, and that Dockerfile says `FROM python:3.12-slim-bullseye`.
# Debian bullseye's repositories have since been archived, so `apt-get update` inside the
# build fails, so the image cannot be built, so the job fails: "Docker build failed with
# exit code 1", three times, with two backoffs. Upstream's main branch has the same line
# and v0.9.0 is still the newest tag, so there was nothing to bump to and nothing this
# repository could patch - a container action pinned by SHA is not a thing you can fix
# from the outside.
#
# What it did is four API calls and a string comparison. Doing it here costs less than
# depending on somebody else's base image aging out, and it removes the whole reason that
# workflow needed a Personal Access Token: the workflow files are read off the checkout
# rather than out of the API, and every release lookup is a public read that the default
# GITHUB_TOKEN can make. See docs/pitfalls.md 8.1.
#
#
# WHAT "BEHIND" MEANS, AND WHAT IT DELIBERATELY DOES NOT
#
# A tag pin (`actions/checkout@v5`) is current when the newest release shares its major.
# `v5` against `v5.0.1` is current - that is the whole point of a moving major tag - and
# `v5` against `v6.0.0` is behind.
#
# A SHA pin is compared through the version written beside it (`@d8781ca... # v0.9.0`),
# not by resolving the SHA. Resolving means chasing annotated tag objects to their commits
# for an answer the comment already gives, and a SHA pin with no comment beside it is
# unauditable by anything, including a person - so that is reported as a finding rather
# than resolved around.
#
# Requires PowerShell 7+.

[CmdletBinding()]
param(
    # Print only the actions that are behind.
    [switch]$Quiet,
    # Report and exit 0 regardless. For running it without gating on the answer.
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


# Every `uses:` in the workflows, as owner/repo plus the ref it is pinned to.
#
# Comment lines are skipped: this file's own header quotes a pinned reference, and a
# checker that reported the example in its explanation would be a checker nobody keeps.
# Local (`./`) and container (`docker://`) references are skipped because neither has a
# release to be behind.
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


# The newest published release tag for an action, or '' when there is none.
#
# gh when it is there, so a run inside Actions is authenticated and does not spend the
# sixty-an-hour unauthenticated budget; plain HTTPS otherwise, so this works on a laptop
# with no gh installed. Either way a failure is '' and the action is reported as unknown
# rather than as behind - a version check that guesses is worse than one that abstains.
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


# Whether a pinned ref is still current against the newest release tag.
#
# Returns 'current', 'behind' or 'unknown'. Three answers rather than two, because "we
# could not find out" and "it is up to date" are different facts and only one of them
# should fail a build.
function Get-Standing([hashtable]$Action, [string]$Latest) {
    if (-not $Latest) { return 'unknown' }

    $pinned = $Action.Ref
    # A SHA pin is read through the version beside it. Without one there is nothing to
    # compare, and that is a finding in itself rather than a pass.
    if ($pinned -match '^[0-9a-f]{40}$') {
        if (-not $Action.Comment) { return 'unknown' }
        $pinned = ($Action.Comment -split '\s+')[0]
    }

    if ($pinned -eq $Latest) { return 'current' }
    # A moving major tag is current while the newest release is inside it: v5 covers
    # v5.0.1 and v5.2.0, and stops covering anything at v6.
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

# The run summary, when there is one to write to. Same table, because the person reading a
# failed run in a browser is the person who needs it and they should not have to open the
# log to find out which action it was.
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
