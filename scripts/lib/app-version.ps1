# Reads, parses and raises the version, and answers what the tags have already claimed.
#
# The build number rises globally across version names and comes from the TAGS, not from
# VERSION. A tag whose name carries no `+n` falls back to the VERSION file committed at
# it, because reading names alone quietly turns "from the tags" into "VERSION plus one".

Set-StrictMode -Version Latest

$script:VersionPattern = '^(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?$'
$script:ReleasedSuffix = '-released'

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Get-VersionFile { return Join-Path (Get-RepoRoot) 'VERSION' }
function Get-PyProjectFile { return Join-Path (Get-RepoRoot) 'pyproject.toml' }
function Get-LockFile { return Join-Path (Get-RepoRoot) 'uv.lock' }

function Get-ProjectName {
    $pyproject = Get-PyProjectFile
    if (-not (Test-Path -LiteralPath $pyproject)) { return '' }
    $inProject = $false
    foreach ($line in (Get-Content -LiteralPath $pyproject)) {
        if ($line -match '^\s*\[([^\]]+)\]') {
            $inProject = ($Matches[1] -eq 'project')
            continue
        }
        if ($inProject -and $line -match '^\s*name\s*=\s*"([^"]+)"') { return $Matches[1] }
    }
    return ''
}

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

function Get-TagName($Version, [switch]$Released) {
    if ($Version -is [string]) {
        throw "Get-TagName takes a parsed version, not '$Version' - pass (Get-AppVersion) or Split-AppVersion's result."
    }
    $text = Format-AppVersion $Version
    if ($Released) { return "v$text$($script:ReleasedSuffix)" }
    return "v$text"
}

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
            else { throw "'$Bump' is not major, minor, patch, keep, or an x.y.z version." }
        }
    }
    return Split-AppVersion "$name+$build"
}

function Set-LockVersion([string]$Text) {
    $lock = Get-LockFile
    if (-not (Test-Path -LiteralPath $lock)) { return '' }
    $name = Get-ProjectName
    if (-not $name) { return '' }

    $lines = @(Get-Content -LiteralPath $lock)
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*name\s*=\s*""$([regex]::Escape($name))""\s*$") {
            $found = $true
            continue
        }
        if (-not $found) { continue }
        if ($lines[$i] -match '^\s*version\s*=') {
            $lines[$i] = "version = `"$Text`""
            [IO.File]::WriteAllLines($lock, $lines, (New-Object Text.UTF8Encoding $false))
            return $lock
        }
        if ($lines[$i] -match '^\s*\[') { break }
    }
    return ''
}

function Get-LockVersionText {
    $lock = Get-LockFile
    if (-not (Test-Path -LiteralPath $lock)) { return '' }
    $name = Get-ProjectName
    if (-not $name) { return '' }

    $found = $false
    foreach ($line in (Get-Content -LiteralPath $lock)) {
        if ($line -match "^\s*name\s*=\s*""$([regex]::Escape($name))""\s*$") {
            $found = $true
            continue
        }
        if (-not $found) { continue }
        if ($line -match '^\s*version\s*=\s*"([^"]+)"') { return $Matches[1] }
        if ($line -match '^\s*\[') { break }
    }
    return ''
}

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

    $written = @($versionFile, $pyproject)
    $lock = Set-LockVersion $text
    if ($lock) { $written += $lock }
    return $written
}
