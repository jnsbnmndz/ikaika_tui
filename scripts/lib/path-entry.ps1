# Adds or removes one directory from the CURRENT USER's PATH. Run by the installer.
#
#     path-entry.ps1 -Directory "C:\...\dti" -Action add
#     path-entry.ps1 -Directory "C:\...\dti" -Action remove
#
# Exists as a script the installer shells out to, rather than as NSIS instructions,
# because NSIS cannot do this safely on this machine.
#
#
# WHY NOT IN NSIS
#
# NSIS is built with a fixed string limit - `makensis /HDRINFO` on the machine this
# was written for reports NSIS_MAX_STRLEN=1024 - and `ReadRegStr` TRUNCATES silently
# at it. Writing that truncated value back is the classic way an installer destroys
# somebody's PATH, and it is not hypothetical here: that user's PATH was already 723
# characters, and the merged machine+user value was 1117. Two more tools installed
# and the native approach starts eating entries with no error.
#
# .NET has no such limit, and `SetEnvironmentVariable` broadcasts WM_SETTINGCHANGE
# itself, so a shell opened afterwards sees the change without a sign-out.
#
#
# THE 'User' SCOPE, NOT $env:Path
#
# `$env:Path` is the machine PATH and the user PATH already merged. Writing that
# into the user scope copies every machine entry into the user's own PATH - it
# doubles the length, and those copies then survive anything that edits the machine
# PATH afterwards. Read and write the same scope, always.
#
# Idempotent in both directions: adding a directory already there changes nothing,
# which matters because an upgrade runs this again. Nothing else in PATH is touched.

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Directory,

    [ValidateSet('add', 'remove')]
    [string]$Action = 'add'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Trailing separators and case both differ between how a path is typed and how it is
# stored, and neither difference means a different directory. Compared on this rather
# than on the raw string, or an upgrade appends a second copy of the same folder.
function Get-Comparable([string]$Path) {
    return $Path.Trim().TrimEnd('\', '/').ToLowerInvariant()
}

try {
    $target = $Directory.Trim().TrimEnd('\', '/')
    if (-not $target) {
        Write-Output 'no directory given'
        exit 1
    }

    # $null when the user has never had a PATH of their own, which is not an error.
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
        # Appended, not prepended: putting an installer's directory first lets it
        # shadow a command somebody else's tool owns, which is not this one's call.
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
        # Removing the last entry. $null deletes the variable rather than leaving an
        # empty one behind, which is what was there before anything was installed.
        [Environment]::SetEnvironmentVariable('Path', $null, 'User')
    }

    # Read back rather than trusting the write: this is somebody's PATH, and a silent
    # failure here is the one nobody notices until a command stops being found.
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
