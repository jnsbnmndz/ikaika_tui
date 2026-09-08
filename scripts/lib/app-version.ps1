# The version, and the two files that have to agree about it.
#
# VERSION at the repository root holds one line, `x.y.z+n`, and is the single source.
# `pyproject.toml` needs its own copy because a wheel's metadata cannot read a text file,
# so this writes both together - the drift it exists to prevent had already happened once,
# with VERSION saying 0.1.0+2 while pyproject said 0.0.0+1 and the header showed the first.
#
#
# THE BUILD NUMBER RISES GLOBALLY, AND COMES FROM THE TAGS
#
# `1.1.9+7` is followed by `1.2.0+8`, never `1.2.0+1`. An installer compares that number
# to decide whether what it is holding is newer than what is installed, so a reset makes
# an upgrade look older than the thing it replaces and the installer refuses it.
#
# It is derived from the TAGS rather than from VERSION, because VERSION is one checkout's
# opinion and the tags are what the repository as a whole has published. A number already
# taken by a tag is never handed out twice, and that is checked before anything is built
# rather than after.
#
# Which means a release has to be TAGGED. Without it the number is spent locally, nothing
# records it, and the next machine hands out the same one.
#
#
# THE TAG NAME CARRIES THE BUILD NUMBER, AND SAYS WHICH KIND OF BUILD IT WAS
#
#     v1.2.0+8              a debug build - what a branch or a local run produces
#     v1.2.0+8-released     an official release, signed and published
#
# One version can therefore have both, which is the point: the same source is tagged
# debug while it is being tested and released once it ships, and the suffix is what tells
# a release feed which of the two to offer. The build number is shared - it belongs to the
# source, not to the kind of build - so `Get-NextBuildNumber` counts both spellings.
#
# The `+n` is in the NAME because that is the number an installer compares, and a tag
# without it can only be told apart from another build of the same version by fetching the
# VERSION file committed at it - which is a clone away from anything reading a release
# feed. `domain/updates.py` has parsed `v1.2.3+4-released` since it was written and had
# nothing to read it out of; this is what finally puts it there. It also makes every tag
# unique by construction, since the number never repeats.
#
# THE SUFFIX STAYS LAST. `Release.official` asks whether a tag ENDS WITH `-released`, so
# `v1.2.0-released+8` reads as a debug build and would never be offered as an update.
# That is not semver's ordering, and semver is not what parses this - nor is `-released` a
# prerelease, it is the opposite.

Set-StrictMode -Version Latest

$script:VersionPattern = '^(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?$'
$script:ReleasedSuffix = '-released'


function Get-RepoRoot {
    # Two levels up from scripts\lib, and never $PWD: every path below is relative to the
    # repository and a command run from a subdirectory would otherwise write elsewhere.
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Get-VersionFile { return Join-Path (Get-RepoRoot) 'VERSION' }
function Get-PyProjectFile { return Join-Path (Get-RepoRoot) 'pyproject.toml' }


# Parses `x.y.z+n` into its parts, or throws saying what it read.
#
# Thrown rather than defaulted: a quiet fallback to 0.0.0+0 would name an installer, a
# payload folder and a git tag after a release that does not exist.
function Split-AppVersion([string]$Raw) {
    $text = "$Raw".Trim()
    if ($text -notmatch $script:VersionPattern) {
        throw "'$text' is not a version - expected x.y.z or x.y.z+n."
    }
    return [ordered]@{
        Major = [int]$Matches[1]
        Minor = [int]$Matches[2]
        Patch = [int]$Matches[3]
        Build = if ($Matches[4]) { [int]$Matches[4] } else { 0 }
        Name  = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
    }
}

function Get-AppVersion {
    $file = Get-VersionFile
    if (-not (Test-Path -LiteralPath $file)) { throw "No VERSION file at $file." }
    return Split-AppVersion (Get-Content -LiteralPath $file -TotalCount 1)
}

function Format-AppVersion($Version) { return "$($Version.Name)+$($Version.Build)" }


# Every version a tag has already claimed, either spelling, as parsed parts.
#
# A tag written by this code carries its build number, so the NAME is the answer. Tags
# written before it did not - `v1.1.9` parses with a build of 0, so reading names alone
# made every one of them contribute nothing and "the number comes from the tags" was
# really "VERSION plus one", which is exactly the reset the rule exists to prevent, just
# later. So a name with no `+n` still falls back to the VERSION file committed AT the tag.
#
# `git show <tag>:VERSION` reads the committed file rather than the working tree, so a tag
# made before VERSION existed simply answers nothing and is skipped.
#
# Returned PLAIN, never `, @(...)`. That idiom protects a single-element array from being
# unrolled, and here it made the EMPTY case a one-element array holding an empty array -
# so a repository with no tags reported one. Callers wrap in @() instead. Seventh time
# this idiom has cost something.
function Get-TaggedVersion {
    $root = Get-RepoRoot
    $tags = @(& git -C $root tag 2>$null | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    $found = @()
    foreach ($tag in $tags) {
        $name = $tag -replace '^v', ''
        if ($name.EndsWith($script:ReleasedSuffix)) {
            $name = $name.Substring(0, $name.Length - $script:ReleasedSuffix.Length)
        }
        if ($name -notmatch $script:VersionPattern) { continue }

        $text = $name
        if ($name -notmatch '\+\d+$') {
            $recorded = "$(& git -C $root show "${tag}:VERSION" 2>$null | Select-Object -First 1)".Trim()
            if ($recorded -match $script:VersionPattern) { $text = $recorded }
        }
        $found += (Split-AppVersion $text)
    }
    return $found
}

# The next build number nobody has used. Never lower than what VERSION already says, so a
# tag pushed from another checkout - or a bump reverted by hand - cannot walk it backwards.
function Get-NextBuildNumber {
    $highest = (Get-AppVersion).Build
    foreach ($version in (Get-TaggedVersion)) {
        if ($version.Build -gt $highest) { $highest = $version.Build }
    }
    return $highest + 1
}

function Test-TagIsFree([string]$Tag) {
    $existing = @(& git -C (Get-RepoRoot) tag --list $Tag 2>$null | Where-Object { $_ })
    return -not $existing.Count
}

# The tag for a version, build number included. See the header for why it is in there and
# why the suffix has to come after it.
#
# Takes the PARSED version rather than its name, so a caller cannot hand over `$v.Name`
# and get a tag with the number quietly missing - which is what both callers did before
# the number was part of it, and a silently build-less tag is a tag that contributes
# nothing to the next build number.
function Get-TagName($Version, [switch]$Released) {
    if ($Version -is [string]) {
        throw "Get-TagName takes a parsed version, not '$Version' - pass (Get-AppVersion) or Split-AppVersion's result."
    }
    $text = Format-AppVersion $Version
    if ($Released) { return "v$text$($script:ReleasedSuffix)" }
    return "v$text"
}


# What `-Bump` means, as the version it produces.
#
# 'same' keeps the name and still takes a new build number: a rebuild of the same source
# is a different artifact, and an installer that cannot tell them apart will not replace
# one with the other.
function Resolve-NextVersion([string]$Bump) {
    $current = Get-AppVersion
    $build = Get-NextBuildNumber

    switch ("$Bump".Trim().ToLower()) {
        'major' { $name = "$($current.Major + 1).0.0" }
        'minor' { $name = "$($current.Major).$($current.Minor + 1).0" }
        'patch' { $name = "$($current.Major).$($current.Minor).$($current.Patch + 1)" }
        { $_ -in @('same', 'keep', '') } { $name = $current.Name }
        default {
            if ("$Bump" -match '^\d+\.\d+\.\d+$') { $name = "$Bump" }
            else { throw "'$Bump' is not major, minor, patch, same, or an x.y.z version." }
        }
    }
    return Split-AppVersion "$name+$build"
}


# Writes VERSION and pyproject.toml together, and reports what it touched.
#
# pyproject's line is rewritten in place rather than the file being regenerated: it holds
# dependencies and an entry point this has no business rewriting. Anchored to the line
# inside [project] - `version` also appears under [build-system] requirements in many
# projects, and a looser match would edit whichever came first.
function Set-AppVersion($Version) {
    $text = Format-AppVersion $Version
    $versionFile = Get-VersionFile
    [IO.File]::WriteAllText($versionFile, "$text`n", (New-Object Text.UTF8Encoding $false))

    $pyproject = Get-PyProjectFile
    if (Test-Path -LiteralPath $pyproject) {
        $lines = @(Get-Content -LiteralPath $pyproject)
        $inProject = $false
        $written = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^\s*\[([^\]]+)\]') {
                $inProject = ($Matches[1] -eq 'project')
                continue
            }
            if ($inProject -and $lines[$i] -match '^\s*version\s*=') {
                $lines[$i] = "version = `"$text`""
                $written = $true
                break
            }
        }
        if (-not $written) {
            throw "No version line under [project] in $pyproject - refusing to guess where it goes."
        }
        [IO.File]::WriteAllLines($pyproject, $lines, (New-Object Text.UTF8Encoding $false))
    }
    return @($versionFile, $pyproject)
}
