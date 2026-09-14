"""Starting an installer that replaces the program starting it."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.updates import HandoverPort

WAIT_TIMEOUT_SECONDS = 120
"""How long the waiter gives this process to exit before running the installer anyway."""

POWERSHELL = "powershell.exe"
"""Windows PowerShell 5.1, which is present on every Windows machine."""

SILENT = "/S"
"""NSIS's silent switch: no wizard, no pages, no clicks."""

SCRIPT = r"""
param(
    [Parameter(Mandatory = $true)][int]    $WaitPid,
    [Parameter(Mandatory = $true)][int]    $Timeout,
    [Parameter(Mandatory = $true)][string] $Installer,
    [string] $Relaunch = '',
    [string] $Log = ''
)

# Defaulted rather than required, so a binding failure cannot be the thing that costs us
# the log. -NonInteractive turns an unbound mandatory parameter into an exit instead of a
# prompt, and an exit before the first line is written is exactly the invisible failure
# this script exists to end.
if (-not $Log) { $Log = [IO.Path]::ChangeExtension($PSCommandPath, '.log') }

function Note($text) {
    $stamp = [DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss')
    "$stamp  $text" | Out-File -LiteralPath $Log -Append -Encoding utf8
}

$installed = $false
try {
    Note "waiting up to $Timeout s for process $WaitPid to exit"
    # Already gone is the good case and not an error here: the app may well have exited
    # between arming this and the script getting round to looking.
    try {
        Wait-Process -Id $WaitPid -Timeout $Timeout -ErrorAction Stop
        Note "process $WaitPid has exited"
    } catch {
        Note "not waited for: $($_.Exception.Message)"
    }

    # The two failures the old one-liner could not tell apart. A throw here means the
    # installer never ran at all; a non-zero code means it ran and refused. Both end up
    # visible, but only one of them is NSIS's to explain.
    Note "running: $Installer /S"
    $code = $null
    try {
        $run = Start-Process -FilePath $Installer -ArgumentList '/S' -Wait -PassThru -ErrorAction Stop
        $code = $run.ExitCode
        Note "the installer exited with $code"
    } catch {
        Note "the installer could not be started: $($_.Exception.Message)"
    }

    if ($code -eq 0) {
        $installed = $true
    } else {
        # A SILENT FAILURE IS THE ONE THING WORSE THAN A WIZARD. Silent means the user
        # sees the app close and nothing come back, with no idea why - so run it AGAIN,
        # visibly, and let its own error dialog do the explaining.
        Note 'running it again without /S so it can report the failure itself'
        Start-Process -FilePath $Installer -ErrorAction SilentlyContinue
    }

    # Only after a successful install, and only for a frozen build. The path is the old
    # process's own executable, which is the right one by construction: the installer
    # replaces the directory it lives in, so the same path is the new version.
    if ($installed -and $Relaunch) {
        Note "starting $Relaunch"
        Start-Process -FilePath $Relaunch -ErrorAction SilentlyContinue
    }
} catch {
    Note "the handover itself failed: $($_.Exception.Message)"
} finally {
    # The log goes only when there is nothing in it worth reading. On any failure it
    # stays, because by now the app it belonged to is gone and this is the only account
    # of what happened. PowerShell has already parsed the whole script, so removing the
    # file it is running from is allowed.
    if ($installed) { Remove-Item -LiteralPath $Log -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
"""
"""The waiter, as a script rather than as a command line."""

SCRIPT_NAME = "{slug}-update-{pid}.ps1"
"""Named after the app and this pid, in %TEMP%."""

NOT_WINDOWS = "handing over to an installer is Windows-only"
NO_INSTALLER = "the installer is not where it was downloaded to"
NO_SCRIPT = "the update script could not be written: {error}"
NOT_STARTED = "the installer could not be started: {error}"


class WindowsHandover(HandoverPort):
    """`HandoverPort` over a detached PowerShell waiter written at runtime."""

    def __init__(self, timeout: int = WAIT_TIMEOUT_SECONDS, folder: Path | None = None) -> None:
        self._timeout = timeout
        self._folder = folder

    def hand_over(self, installer: Path) -> str:
        if os.name != "nt":
            return NOT_WINDOWS
        if not installer.is_file():
            return NO_INSTALLER

        try:
            script = self._write_script()
        except OSError as error:
            return NO_SCRIPT.format(error=error)

        try:
            subprocess.Popen(
                self._argv(script, installer),
                creationflags=(
                    subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            script.unlink(missing_ok=True)
            return NOT_STARTED.format(error=error)
        return ""

    def _write_script(self) -> Path:
        folder = self._folder or Path(tempfile.gettempdir())
        folder.mkdir(parents=True, exist_ok=True)
        script = folder / SCRIPT_NAME.format(slug=naming.APP_SLUG, pid=os.getpid())
        script.write_text(SCRIPT, encoding="utf-8-sig")
        return script

    def _argv(self, script: Path, installer: Path) -> list[str]:
        argv = [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
            "-WaitPid",
            str(os.getpid()),
            "-Timeout",
            str(self._timeout),
            "-Installer",
            str(installer.resolve()),
        ]
        if getattr(sys, "frozen", False):
            argv += ["-Relaunch", str(Path(sys.executable).resolve())]
        return argv
