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
and only then starts the installer:

    powershell -Command "Wait-Process -Id <pid>; Start-Process '<installer>'"

Windows PowerShell, not `pwsh`. Every script in this repository requires PowerShell 7,
and this is the one place that must not: 7 is something a developer installed, and this
runs on the machine of whoever installed the app. `powershell.exe` 5.1 ships with Windows
and has `Wait-Process`.

DETACHED_PROCESS, not a plain Popen. Without it the waiter belongs to this console, and
the console goes away with the process it is waiting for.


IT IS ARMED, AND THEN THE CALLER QUITS

`hand_over` returning "" means something is now waiting for this process to end. The
caller must exit, and promptly: what is waiting has a timeout, and a user who says yes to
an install and then watches the app sit there has been told a lie.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

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

# -Id, then the installer. `Wait-Process` errors when the pid has already gone, which is
# the good case and not an error here - hence SilentlyContinue rather than a check.
WAITER = (
    "$ErrorActionPreference='SilentlyContinue';"
    "Wait-Process -Id {pid} -Timeout {timeout};"
    "Start-Process -FilePath '{installer}'"
)

NOT_WINDOWS = "handing over to an installer is Windows-only"
NO_INSTALLER = "the installer is not where it was downloaded to"


def quote(value: str) -> str:
    """A path as a PowerShell single-quoted string.

    Single quotes, so nothing inside is expanded - a path holding `$` or a backtick is a
    real path, and this repository lives under a folder literally named
    "GitHub(jnsbnmndz)". Doubling is how a literal quote is escaped inside one.
    """
    return value.replace("'", "''")


class WindowsHandover(HandoverPort):
    """`HandoverPort` over a detached PowerShell waiter."""

    def __init__(self, timeout: int = WAIT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    def hand_over(self, installer: Path) -> str:
        if os.name != "nt":
            return NOT_WINDOWS
        # Checked here rather than trusted from the state file. The path was written down
        # at a previous launch, and %TEMP% cleaners and the user both exist - and a waiter
        # armed against a file that is gone would take the app down for nothing.
        if not installer.is_file():
            return NO_INSTALLER

        command = WAITER.format(
            pid=os.getpid(),
            timeout=self._timeout,
            installer=quote(str(installer.resolve())),
        )
        try:
            subprocess.Popen(  # noqa: S603 - a fixed argv, no shell, no user input
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-Command",
                    command,
                ],
                # DETACHED_PROCESS so it survives this process and its console; a new
                # process group so a Ctrl+C aimed at the app on its way out does not
                # reach the thing that is meant to outlive it.
                creationflags=(
                    subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
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
            return f"the installer could not be started: {error}"
        return ""
