# 4. The toolbox can install its own update, through a process that outlives it

> **Status: ACCEPTED (2026-09-08).** Supersedes the "IT DOES NOT INSTALL ANYTHING" paragraph that `company_tui/capabilities/updates.py` carried. The launch check is `application/updates.py`; the handover is `infrastructure/handover.py`; the badge and the `Ctrl+U` action are in `presentation/chrome.py` and `presentation/tui_console.py`.

## 1. Context

There was already a manual check: `capabilities/updates.py` reads the release feed,
compares four numbers, and downloads the installer when asked. It stopped there, with a
line in its own header explaining why:

> **IT DOES NOT INSTALL ANYTHING.** Running it is left to the person, and that is
> deliberate: the installer replaces the very files this process is executing from, so
> launching it from here would have the uninstaller deleting a running program. The
> one-line-of-code version of this feature is the one that corrupts an install.

That warning is correct, and it is worth being precise about *why*, because the precision
is what makes the feature possible. `scripts/installer.nsi` upgrades by running the old
uninstaller and then `RMDir /r` over the install directory. That directory holds
`dti.exe`. Windows will not delete or overwrite a running executable, so an installer that
starts while the toolbox is alive reaches its first `File` instruction and stops with
"Error opening file for writing" — over an install it has already half removed. Not
silent, but it looks like the toolbox is broken rather than like a race, and the
half-removed state is real.

Two things then made the feature worth having anyway. The build number now travels in the
tag (`v1.2.0+8`), so `newer_than` can finally tell two builds of one version apart — which
is what makes an automatic check able to say anything useful. And the people running this
are the people releasing it, so "there is a newer build" is a thing that happens weekly
rather than twice a year.

## 2. Decision

### 2.1 The check runs at launch, as a worker, and is silent about everything else

`UpdateWatch.look()` is called from `on_mount` and not awaited. Every rule it follows
comes from nobody having asked for it:

- **It may not delay the first paint.** A launch that opened on a blank frame while GitHub
  was slow would be this feature costing more than it is worth.
- **It may not report its own plumbing.** Offline, rate-limited, a repository that does not
  exist, a tag that does not parse — all silence. The same rule the script-store version
  check follows: a courtesy that explains why it could not be a courtesy is noise, and here
  it is noise at the moment the app opens. The manual card reports all of it properly,
  because that is somebody actually asking.
- **It may not ask on every launch.** `CHECK_INTERVAL_HOURS` and a remembered timestamp.
  Unauthenticated GitHub allows sixty requests an hour per address, and an app that asks on
  every start spends that budget on somebody restarting it to look at a theme — and that is
  the same person who then finds the manual check rate-limited.
- **It never raises.** It is called from a worker started at mount, where an exception is a
  traceback in a log nobody is reading, on the one screen where the app has not finished
  appearing.

### 2.2 It downloads, and remembers where

The installer is fetched into `~/.dti/updates/` and the path is written to `updates.json`.
A second launch with an installer already recorded touches the network **not at all** — the
badge comes straight back out of the file.

Three things have to hold before that remembered path is trusted: something was fetched,
the file is still there, and what it holds is still newer than what is running. The third
is what stops a badge surviving the install it was offering: the app comes back up as the
version that installer held, and without the check the state file would keep proposing it
at every launch forever.

### 2.3 The handover is a third process, and that is the whole feature

```
powershell -Command "Wait-Process -Id <pid>; Start-Process '<installer>'"
```

Detached, so it survives this process and its console. It waits for *this* pid and only
then starts the installer, which is the ordering that makes the difference between an
upgrade and a corrupted install. `tests/test_auto_update.py` asserts that ordering
directly, because it is the one line where being nearly right is worse than not having the
feature.

**Windows PowerShell, not `pwsh`.** Every script in this repository requires PowerShell 7;
this is the one place that must not, because 7 is something a developer installed and this
runs on the machine of whoever installed the app. `powershell.exe` 5.1 ships with Windows.

**Not `ProcessRunner`.** Every method there is about a subprocess whose output and exit
code are the point and whose lifetime is bounded by the run that started it. This is the
opposite on both counts: nothing it prints is ever read, and it must outlive its parent
deliberately. A port that means "spawn and forget" alongside one whose cancellation kills
its child would be two contracts under one name.

### 2.4 Arming and quitting are one act, in that order

`hand_over` returning `""` means something is now waiting for this process to end. The
caller quits immediately, and must: what has been armed is waiting for exactly that.
Reversed, there is nothing left to arm it.

### 2.5 The install is offered by the chrome, not by the capability

A badge in the header and `Ctrl+U`. Not by the manual card, and not because that would be
harder to write — because it cannot work. The capability runs inside a run panel, and
shutting the app down cancels every run, including the one asking. It would be a worker
cancelling itself and awaiting its own completion.

So the capability *records* what it downloaded, through the same `UpdateStatePort` the
launch check reads, and `Ctrl+U` picks it up. `look()` answers out of that file without a
request when an installer is already fetched, which is why pressing the key after a manual
download is not a second network call.

The key is in no footer. It does nothing until there is an installer waiting, and a hint
for a key that is dead most of the time is a control that lies — so the badge carries the
key, and the badge only exists when the key does something.

## 3. Consequences

- `[updates] check_on_launch` turns it off. On by default and harmless when nothing else is
  set, because `configured` is false until a repository is named — the shipped default
  checks nothing.
- Only the interactive console gets a watch. `list` and `doctor` print and exit, and a
  scriptable command that quietly downloads thirty megabytes is a surprise in somebody's CI
  log.
- The asset name is reduced to a bare filename before it is joined to the cache directory.
  It comes off a server, and it ends up as a path handed to Windows to execute.
- `updates.json` is **not** keyed by workspace, unlike `sessions.json`. The tabs of one
  project are not the tabs of another, but there is one copy of this toolbox on the machine
  and one update for it.
- The download moved behind `AssetDownloadPort`, so the launch check and the manual card
  share one answer to "what is a finished download" — and one implementation of writing to
  `.part` and moving it into place, which is what makes a remembered path safe to trust.

## 4. Alternatives rejected

**Spawn the installer as a child and quit.** The race in section 1. It works most of the
time, which is the worst property a thing like this can have.

**Detect the running instance in NSIS and wait there.** Needs a plugin (`nsProcess` or
`FindProcDLL`) to detect a process at all, which is a new dependency in the installer build
for something four lines of PowerShell already does — and it moves the fix into the artefact
being installed, so an old installer could never be fixed.

**Silent auto-install at launch.** Replacing the program somebody just started, without
asking, while they may have runs going. Every part of this codebase asks before something
that cannot be undone; this is the largest such thing it could do.

**Check on a timer while the app runs.** More requests, for an answer that cannot change
usefully within one session — and a badge appearing under somebody's cursor mid-workflow.
Launch is the moment a restart is cheapest, which is exactly the moment to mention one.

**Skip the state file and re-check every launch.** Simpler, and it re-downloads thirty
megabytes every time the app opens until the user installs. The file exists to make the
second launch free.
