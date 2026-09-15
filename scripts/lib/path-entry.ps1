# Adds or removes a directory from the user's PATH, for the installer to shell out to.
#
# NOT done in NSIS: NSIS_MAX_STRLEN is 1024 and ReadRegStr truncates silently at it, and
# writing that back is how an installer eats somebody's PATH. .NET has no such limit and
# broadcasts WM_SETTINGCHANGE itself. User scope only - writing the merged $env:Path into
# user scope is the other classic bug, and it doubles the length every time.

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Directory,

    [ValidateSet('add', 'remove')]
    [string]$Action = 'add'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Comparable([string]$Path) {
    return $Path.Trim().TrimEnd('\', '/').ToLowerInvariant()
}

try {
    $target = $Directory.Trim().TrimEnd('\', '/')
    if (-not $target) {
        Write-Output 'no directory given'
        exit 1
    }

    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @()
    if ($current) {
        $entries = @($current -split ';' | Where-Object { $_.Trim() })
    }

    $wanted = Get-Comparable $target
    $without = @($entries | Where-Object { (Get-Comparable $_) -ne $wanted })
    $present = $without.Count -ne $entries.Count

    if ($Action -eq 'add') {
        if ($present) {
            Write-Output "already on PATH: $target"
            exit 0
        }
        $updated = @($entries + $target)
    } else {
        if (-not $present) {
            Write-Output "not on PATH, nothing to remove: $target"
            exit 0
        }
        $updated = $without
    }

    if ($updated.Count) {
        [Environment]::SetEnvironmentVariable('Path', ($updated -join ';'), 'User')
    } else {
        [Environment]::SetEnvironmentVariable('Path', $null, 'User')
    }

    $after = [Environment]::GetEnvironmentVariable('Path', 'User')
    $now = @()
    if ($after) { $now = @($after -split ';' | Where-Object { $_.Trim() }) }
    $found = @($now | Where-Object { (Get-Comparable $_) -eq $wanted }).Count

    if ($Action -eq 'add' -and $found -ne 1) {
        Write-Output "FAILED to add $target - PATH holds $found copies of it"
        exit 1
    }
    if ($Action -eq 'remove' -and $found -ne 0) {
        Write-Output "FAILED to remove $target - PATH still holds $found copies"
        exit 1
    }

    Write-Output "$Action ok: $target ($($now.Count) entries, $($after.Length) chars)"
    exit 0
} catch {
    Write-Output "PATH edit failed: $($_.Exception.Message)"
    exit 1
}
