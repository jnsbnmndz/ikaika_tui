# The one entry point. Commands are discovered from scripts\, so the listing and the
# folder cannot disagree; `<command> -Help` prints that command's own switches.
#
# Arguments are forwarded as literal tokens - never splatted. See docs/pitfalls.md 7.1.

param(
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

function Get-CommandList {
    return @(Get-ChildItem -LiteralPath $scriptsDir -Filter '*.ps1' -File |
            Sort-Object Name |
            ForEach-Object { $_.BaseName })
}

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
    $near = @($commands | Where-Object { $_ -like "*$Name*" -or $Name -like "*$_*" })
    if ($near.Count) {
        Write-Host "  Did you mean: $($near -join ', ')" -ForegroundColor Yellow
    } else {
        Write-Host "  Commands: $($commands -join ', ')" -ForegroundColor DarkGray
    }
    Write-Host ''
    exit 1
}

if ($args.Count) {
    & $target @args
} else {
    & $target
}
exit $LASTEXITCODE
