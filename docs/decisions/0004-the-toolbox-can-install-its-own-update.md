# 4. The toolbox can install its own update, through a process that outlives it

> **Status: ACCEPTED (2026-09-08), amended 2026-09-12.** Launch check `application/updates.py`, handover `infrastructure/handover.py`, badge and `Ctrl+U` in `presentation/`.

## Context

`capabilities/updates.py` checked and downloaded but refused to install, for a correct
reason: the installer runs the old uninstaller then `RMDir /r` over the directory holding
the running `dti.exe`, so launching it from there has the uninstaller deleting a running
program. The one-line version of this feature is the one that corrupts an install.

Two things made it worth having anyway. The build number now travels in the tag, so
`newer_than` can tell two builds of one version apart; and the people running this are the
people releasing it, so "there is a newer build" happens weekly.

## Decision

### The check runs at launch, as a worker, and is silent about everything else

Every rule follows from nobody having asked: it may not delay the first paint, may not
report its own plumbing (offline, rate-limited, unparseable tag — all silence, because the
manual card is where somebody *did* ask), may not ask more than once every
`CHECK_INTERVAL_HOURS`, and never raises.

### It downloads, and remembers where

Into `~/.dti/updates/`, with the path written down so a second launch touches the network
not at all. Four things must hold before a remembered path is trusted: something was
fetched, it is on this build's line, the file is still there, and it is still newer than
what is running. The last is what stops a badge surviving the install it was offering.

### The handover is a third process, and that is the whole feature

```
powershell -ExecutionPolicy Bypass -File <script> -WaitPid <pid> -Installer <path>
```

It waits for *this* pid and only then starts the installer — the ordering that is the whole
difference between an upgrade and a corrupted install, and asserted directly in tests.

**Windows PowerShell, not `pwsh`:** every other script here needs 7, and this is the one
place that must not, because it runs on the machine of whoever installed the app.

**`CREATE_NO_WINDOW`, never `DETACHED_PROCESS`** (amended). The first version said
"detached, so it survives this console", which is the right requirement and the wrong flag:
`powershell.exe` with no console exits 0 having run nothing while `Popen` reports success,
so the app announced an armed handover and quit with nothing waiting for it. That is why
this feature shipped not working. `docs/pitfalls.md` 6.4.

**A generated script, not a command string** (amended). The waiter was one `-Command` line
with the pid and both paths pasted in, which made paths into program text, put two escaping
layers between Python and PowerShell, and left nothing on disk to read when it failed. It
is now a `.ps1` written to `%TEMP%` at runtime with a `param()` block, logging beside itself
— removed on success, kept on failure. Generated rather than shipped, because a file the
build packages is one whose fix can only reach a machine through the installer that is
failing. `docs/pitfalls.md` 6.5.

### Arming and quitting are one act, in that order

`hand_over` returning `""` means something is waiting for this process to end. The caller
quits immediately, and must.

### The install is offered by the chrome, not the capability

A badge and `Ctrl+U`. Not because the capability would be harder, but because it cannot
work: the capability runs inside a run panel, and shutting down cancels every run including
the one asking. So the capability *records* what it downloaded and the chrome picks it up.

### An update has a line, and the line is what is running (amended)

A debug build cannot update a release install — it installs beside it — so offering one is
a silent no-op with a badge that never clears. `wanted()` refuses any release that could not
replace the running build, and `build_kind` reads that off the command name. For an
installed build the channel has nothing left to choose; it still decides in a source
checkout. `updates.json` is keyed by line for the same reason. `docs/pitfalls.md` 6.6.

## Consequences

- `[updates] check_on_launch` turns it off; clearing `repository` turns both halves off.
- Only the interactive console gets a watch — a scriptable command that quietly downloads
  thirty megabytes is a surprise in somebody's CI log.
- The asset name is reduced to a bare filename before being joined to the cache directory.
  It comes off a server and ends up as a path handed to Windows to execute.
- The download sits behind `AssetDownloadPort`, so there is one answer to "what is a
  finished download".

## Alternatives rejected

- **Spawn the installer as a child and quit.** Works most of the time, which is the worst
  property a thing like this can have.
- **Detect the running instance in NSIS.** Needs a plugin, and moves the fix into the
  artefact being installed — so an old installer could never be fixed.
- **Silent auto-install at launch.** Replacing the program somebody just started, without
  asking, while they may have runs going.
- **Check on a timer.** More requests for an answer that cannot change usefully within one
  session, and a badge appearing under somebody's cursor mid-workflow.
