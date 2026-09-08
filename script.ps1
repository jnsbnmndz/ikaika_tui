# The one entry point. Every command lives in scripts\ and is run through here.
#
#     .\script.ps1                      what commands there are
#     .\script.ps1 build-app            run one
#     .\script.ps1 build-app -Help      what it does, and every switch
#     .\script.ps1 bump-version -Bump patch -Released
#
# Commands are DISCOVERED, not listed: a .ps1 in scripts\ is a command, named after its
# file. Nothing here has to be edited to add one, so the list and the folder cannot
# disagree - which is the failure a hand-maintained table has, silently, the first time
# somebody adds a file.
#
# scripts\lib\ is NOT searched, and it holds two kinds of thing alike in the one
# way that matters here: neither is a command.
#
#   dot-sourced libraries      running one defines some functions and does nothing,
#                              which looks like a command that silently failed
#   helpers other programs run lib\path-entry.ps1 is invoked by the installer with
#                              arguments it requires. It sat in scripts\ for one build
#                              and appeared in this listing, where the only thing it
#                              could do was fail on a missing -Directory.
#
#
# A BARE RUN PRINTS AND EXITS. IT DOES NOT PROMPT.
#
# The sibling project opens a terminal app here. This one does not, and the difference is
# deliberate: this repository's commands are run by CI and by hooks as often as by a
# person, and a front end that waits for input is a hang with no output in both. The
# listing is what a bare run is for.
#
# Requires PowerShell 7+.

# NO [CmdletBinding()], AND THE REST OF THE LINE COMES FROM $args.
#
# The obvious spelling - an advanced script with a ValueFromRemainingArguments parameter -
# is wrong here, and wrong in a way that only shows up on switches. That parameter
# collects `-Yes` as the plain string "-Yes", so splatting it hands the command a
# POSITIONAL value: `setup-signing -Yes` came back as "the argument -Yes does not belong
# to the set both,release,debug", having been bound to -Which. [object[]] does the same.
#
# The automatic $args keeps them as unbound argument tokens, so @args re-parses them as
# parameter names, which is the whole job. Verified both ways rather than reasoned about.
#
# THE SAME RULE BINDS THE CALLER, AND THAT HALF IS EASIER TO GET WRONG.
#
#     .\script.ps1 bump-version -Bump minor -Yes        works
#     .\script.ps1 bump-version @('-Bump','minor')      does NOT
#     .\script.ps1 bump-version @{ Bump = 'minor' }     does NOT
#     .\script.ps1 bump-version -Bump minor -Yes:$true  does NOT
#
# Array splatting is positional, so '-Bump' arrives as the VALUE of -Bump. A hashtable
# splat binds by name at this hop and is flattened to values before $args is forwarded, as
# is a colon-bound switch. Everything reaching a command through here has to be a token
# written at the call site - which is what release.yml learned the hard way, and what the
# `workflow calls` check in check-all now enforces on the workflows.
param(
    # Which command. Empty lists them.
    [string]$Name = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Host "This needs PowerShell 7+ (found $($PSVersionTable.PSVersion))." -ForegroundColor Red
    Write-Host '  winget install Microsoft.PowerShell' -ForegroundColor Yellow
    exit 1
}

$scriptsDir = Join-Path $PSScriptRoot 'scripts'
if (-not (Test-Path -LiteralPath $scriptsDir)) {
    Write-Host "There is no scripts folder at $scriptsDir." -ForegroundColor Red
    exit 1
}

# Top level only - -Recurse would pull in scripts\lib\.
#
# NOT Get-Command, which is the singular name the style rule asks for and also a
# built-in cmdlet: a function by that name shadows it for the rest of the file, so
# the next person to add a Get-Command lookup here gets this instead, silently.
function Get-CommandList {
    return @(Get-ChildItem -LiteralPath $scriptsDir -Filter '*.ps1' -File |
            Sort-Object Name |
            ForEach-Object { $_.BaseName })
}

# The first comment line of a command file, which by convention says what it does. Read
# rather than duplicated here, so the listing cannot drift from the file it describes.
function Get-Summary([string]$Command) {
    $path = Join-Path $scriptsDir "$Command.ps1"
    foreach ($line in (Get-Content -LiteralPath $path -TotalCount 5)) {
        $text = "$line".Trim()
        if ($text.StartsWith('#')) {
            $text = $text.TrimStart('#').Trim()
            if ($text) { return $text }
        }
    }
    return ''
}

$commands = Get-CommandList

if (-not $Name -or $Name -in @('help', '-h', '--help', '-help')) {
    Write-Host ''
    Write-Host '  Developer Toolbox Inventory' -ForegroundColor Cyan
    $versionFile = Join-Path $PSScriptRoot 'VERSION'
    if (Test-Path -LiteralPath $versionFile) {
        Write-Host "  v$("$(Get-Content -LiteralPath $versionFile -TotalCount 1)".Trim())" -ForegroundColor DarkGray
    }
    Write-Host ''
    if (-not $commands.Count) {
        Write-Host '  There are no commands in scripts\.' -ForegroundColor Yellow
        Write-Host ''
        exit 1
    }
    $width = ($commands | Measure-Object -Property Length -Maximum).Maximum
    foreach ($command in $commands) {
        $summary = Get-Summary $command
        Write-Host "    $($command.PadRight($width))  " -NoNewline
        Write-Host $summary -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Host '  .\script.ps1 <command> -Help' -NoNewline
    Write-Host '   for one command''s own switches' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}

$target = Join-Path $scriptsDir "$Name.ps1"
if (-not (Test-Path -LiteralPath $target)) {
    Write-Host ''
    Write-Host "  There is no command called '$Name'." -ForegroundColor Red
    # Anything sharing a run of characters with what was typed. Cheap, and it catches the
    # cases that actually happen: a typo, and half-remembering the name.
    $near = @($commands | Where-Object { $_ -like "*$Name*" -or $Name -like "*$_*" })
    if ($near.Count) {
        Write-Host "  Did you mean: $($near -join ', ')" -ForegroundColor Yellow
    } else {
        Write-Host "  Commands: $($commands -join ', ')" -ForegroundColor DarkGray
    }
    Write-Host ''
    exit 1
}

# Called as a STATEMENT, and the exit code read afterwards from $LASTEXITCODE.
#
# Never `exit (& $target @Arguments)`. Parenthesising a call captures its whole output
# pipeline, so everything the command printed becomes the value being exited with - which
# in the sibling project meant an interface drawn into a discarded variable and an app
# that looked hung. The same shape has cost three separate bugs there.
if ($args.Count) {
    & $target @args
} else {
    & $target
}
exit $LASTEXITCODE
