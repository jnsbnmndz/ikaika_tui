"""Starting an installer that replaces the program starting it.

This is the one file in the update feature where being nearly right is worse than not
having the feature. `scripts/installer.nsi` upgrades by running the old uninstaller and
then `RMDir /r` over the install directory, and that directory holds the executable this
code is running from. So:

    spawn the installer as a normal child and quit      -> a race
    spawn it, quit, and hope we exit first              -> the same race, with optimism
    spawn it and wait for it                            -> deadlock; it is waiting for us

A locked executable is not a silent failure - NSIS stops with "Error opening file for
writing" over a half-removed install - but it is an ugly one, it looks like the toolbox
broke rather than like a race, and the half-removed state is real.

So the handover is a THIRD process that outlives this one, waits for this process by pid,
and only then starts the installer.

Windows PowerShell, not `pwsh`. Every script in this repository requires PowerShell 7,
and this is the one place that must not: 7 is something a developer installed, and this
runs on the machine of whoever installed the app. `powershell.exe` 5.1 ships with Windows
and has `Wait-Process`.

CREATE_NO_WINDOW, AND NEVER DETACHED_PROCESS

This was `DETACHED_PROCESS`, for the obvious-sounding reason: without a flag the waiter
belongs to this console, and the console goes away with the process it is waiting for.
The flag is the wrong one, and it is wrong in the worst available way.

**`powershell.exe` started with `DETACHED_PROCESS` exits 0 without running anything.**
Detached means no console at all, and PowerShell is a console application - so it comes
up, finds nothing to attach to, and leaves. Immediately, quietly, and with a success
code. Nothing is written, nothing is logged, and the parent's `Popen` succeeded, so the
app reported an armed handover and quit. That is the whole of "the in-app update does not
work": there was never a waiter, so there was never an installer.

It applies to `-Command` exactly as it applies to `-File`, which is why replacing the one
with the other did not fix it and why this paragraph matters more than that one.

`CREATE_NO_WINDOW` is the flag that was wanted all along. The child is a console process
with a console of **its own** that is never shown, so it does not die with this one's and
there is nothing on screen either. `CREATE_NEW_PROCESS_GROUP` on top, so a Ctrl+C aimed
at the app on its way out does not reach the thing meant to outlive it.

`tests/test_auto_update.py` asserts the flag by name. A test cannot start a real waiter -
it would install something - so what it can do is refuse the one flag that is known to
produce a process that does nothing at all.


IT IS A SCRIPT, WRITTEN AT RUNTIME, AND NOTHING IS INTERPOLATED INTO IT

This was one `-Command` string with the pid, the installer and the exe pasted into it,
which made three separate problems out of one job. The paths were *code*: a quote in a
path ended the string and the rest of it ran as PowerShell, so the module carried a
`quote()` and a test about apostrophes for a value that was never meant to be program
text in the first place. There were two escaping layers, because Python joins an argv
back into one command line for Windows and `powershell.exe` then re-parses it by its own
rules, neither of which is the other's. And what ran was nowhere - a string in a process
that had already exited, so an update that failed left the user with an app that closed
and never came back, and left nobody anything to read.

`SCRIPT` is therefore a constant with **no placeholders at all**, written to %TEMP% as it
is, and every value reaches it as an *argument*:

    powershell -ExecutionPolicy Bypass -File <script> -WaitPid 1234 -Installer <path>

`param()` binds them. A path is a string the whole way down, quoting stops being a
correctness question, and that is why there is no `quote()` here any more.

**`-ExecutionPolicy Bypass` is not optional.** `-Command` ignores the execution policy
and `-File` obeys it, so the same script that works on a developer's machine is blocked
on a default install without it. It is the one line here that has to survive an edit.

Generated rather than shipped, deliberately. `scripts/lib/path-entry.ps1` is the other
PowerShell the installer needs, and it is a real file that `build-installer.ps1` hands to
`makensis` and the NSI writes into `$PLUGINSDIR`. Doing that here would put the updater
into the build and the release - a file to package, a path to find once frozen, and a fix
that could only reach a machine through the very installer that is failing. Written at
runtime it is none of those things.


IT IS SILENT, AND IT PUTS THE APP BACK

The sequence is: wait for this process, run the installer with /S, start the new build.
So what the user sees is the app close and reopen a few seconds later on the new version,
which is the update being performed rather than being handed to them.

The failure path is the reason this is not simply "add /S". Silent means invisible, and an
install that fails silently is an app that closed and never came back. So a failure runs
the installer again WITHOUT /S, and its own error dialog says what went wrong.

And the script keeps a log. The old command decided to re-run visibly on
`$done.ExitCode -ne 0`, which is true both when the installer refused and when it never
started at all - `$ErrorActionPreference` was `SilentlyContinue`, so a `Start-Process`
that threw left `$done` null and `$null -ne 0` took the same branch. Two different
failures, one behaviour, and no record of which one happened. The script tells them apart
and writes what it did to a file beside itself. On success both go; on failure the log
stays, because by then the app is gone and this is the only account there is.


IT IS ARMED, AND THEN THE CALLER QUITS

`hand_over` returning "" means something is now waiting for this process to end. The
caller must exit, and promptly: what is waiting has a timeout, and a user who says yes to
an install and then watches the app sit there has been told a lie.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.updates import HandoverPort

WAIT_TIMEOUT_SECONDS = 120
"""How long the waiter gives this process to exit before running the installer anyway.

Bounded rather than infinite, and generous rather than tight. Shutdown here writes the
tabs down and cancels every run, which for a run mid-`npm install` is a subprocess tree
to kill - seconds, not minutes, but not instant either. If something genuinely wedges,
the installer still runs and NSIS reports the locked file, which is a visible failure
with a Retry button rather than an installer that never appeared at all.
"""

POWERSHELL = "powershell.exe"
"""Windows PowerShell 5.1, which is present on every Windows machine.

Deliberately not `pwsh`: see the header. This is the only PowerShell call in the codebase
that has to work on a machine where nobody installed anything.
"""

SILENT = "/S"
"""NSIS's silent switch: no wizard, no pages, no clicks.

The whole point of an in-app update. Without it the app closes and a Setup window
appears with a Next button, which is not an update the app performed - it is the app
handing you an installer. Safe here because the install is per-user under
%LOCALAPPDATA%, so nothing elevates and there is nothing to consent to; and because an
update never asks where to install, that page being skipped costs nothing.

Written into `SCRIPT` rather than formatted into it. The constant is here so the tests
and the reader have a name for it, not so that anything substitutes it.
"""

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
"""The waiter, as a script rather than as a command line.

No `{}` in it and nothing formatted into it - see the header. Everything it needs arrives
through `param()`, so the only thing this constant has to get right is what it does, not
how a path is spelled inside it.
"""

SCRIPT_NAME = "{slug}-update-{pid}.ps1"
"""Named after the app and this pid, in %TEMP%.

The pid rather than a random suffix: two of these can only exist if two copies of the
toolbox are updating at once, and then the name says which is which. The script removes
itself when it is done, and leaves its log behind only when the install failed.
"""

NOT_WINDOWS = "handing over to an installer is Windows-only"
NO_INSTALLER = "the installer is not where it was downloaded to"
NO_SCRIPT = "the update script could not be written: {error}"
NOT_STARTED = "the installer could not be started: {error}"


class WindowsHandover(HandoverPort):
    """`HandoverPort` over a detached PowerShell waiter written at runtime."""

    def __init__(self, timeout: int = WAIT_TIMEOUT_SECONDS, folder: Path | None = None) -> None:
        self._timeout = timeout
        # %TEMP% unless a test says otherwise. A test writing to the real one would leave
        # a .ps1 behind on every run, and this feature has form for a path argument that
        # turned out to be load-bearing - see docs/pitfalls.md 6.3.
        self._folder = folder

    def hand_over(self, installer: Path) -> str:
        if os.name != "nt":
            return NOT_WINDOWS
        # Checked here rather than trusted from the state file. The path was written down
        # at a previous launch, and %TEMP% cleaners and the user both exist - and a waiter
        # armed against a file that is gone would take the app down for nothing.
        if not installer.is_file():
            return NO_INSTALLER

        try:
            script = self._write_script()
        except OSError as error:
            return NO_SCRIPT.format(error=error)

        try:
            subprocess.Popen(  # noqa: S603 - a fixed argv, no shell, paths as arguments
                self._argv(script, installer),
                # CREATE_NO_WINDOW, *not* DETACHED_PROCESS - see the header. Its own
                # hidden console, so it survives this one's going away; a new process
                # group so a Ctrl+C aimed at the app on its way out does not reach the
                # thing that is meant to outlive it.
                creationflags=(
                    subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
                close_fds=True,
                # Nothing reads any of these, and inheriting this app's are how a
                # detached child ends up writing over a terminal the app has released.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            # Nothing is waiting for this process, so the app carries on - and the script
            # would sit in %TEMP% for good, since the only thing that deletes it is the
            # run that never happened.
            script.unlink(missing_ok=True)
            return NOT_STARTED.format(error=error)
        return ""

    def _write_script(self) -> Path:
        folder = self._folder or Path(tempfile.gettempdir())
        folder.mkdir(parents=True, exist_ok=True)
        script = folder / SCRIPT_NAME.format(slug=naming.APP_SLUG, pid=os.getpid())
        # utf-8-sig: Windows PowerShell 5.1 reads a BOM-less file as the machine's ANSI
        # codepage, so a non-ASCII character added here one day would arrive as mojibake
        # rather than as a syntax error. The BOM is what makes that edit safe in advance.
        script.write_text(SCRIPT, encoding="utf-8-sig")
        return script

    def _argv(self, script: Path, installer: Path) -> list[str]:
        argv = [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            # See the header. `-File` obeys the execution policy where `-Command` did
            # not, so this is what stops a default machine refusing to run the script.
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
        # Frozen only. Under `python -m company_tui` there is nothing to restart -
        # sys.executable is the interpreter, and relaunching that would open a bare
        # Python prompt over somebody's terminal.
        if getattr(sys, "frozen", False):
            argv += ["-Relaunch", str(Path(sys.executable).resolve())]
        return argv
