# Pitfalls

Things that have actually gone wrong here, and the rule that followed. Every one was
**silent**: a menu that came back, a test that passed over nothing, a rule nothing
enforced. None was found by reading the code afterwards.

`CLAUDE.md` holds the rules, `docs/decisions/` holds why the architecture is what it is,
and this file holds the failures — a rule with the wreck behind it is easier to keep.

---

## 1. A workflow can die where nobody is looking

### 1.1 A step name missing from `TRAIL_STEPS`

`_enter_step` does `TRAIL_STEPS.index(step)`. A name not in the tuple raises, the run
supervisor catches it as a failed workflow, logs it to a session nobody is reading, and
puts the previous menu back. Scripts opened, died and vanished, leaving a menu that looked
exactly like nothing had been asked for.

**Rule.** A new menu step goes in `TRAIL_STEPS`, in walk order, in the same change.
`tests/test_navigation_steps.py` reads the names back out of the source with `ast` rather
than restating them.

### 1.2 The order in `TRAIL_STEPS` is behaviour

The tuple decides what going back clears. A step listed after the steps below it in the
walk leaves those standing, so a stale action survives a change of section.

---

## 2. Output that never reaches the terminal

### 2.1 Parentheses capture a subprocess's stdout

```powershell
exit (Start-Tui ...)     # WRONG - captures the whole output pipeline
Start-Tui ...; exit $LASTEXITCODE
```

The app started, took the terminal, drew its entire interface into a value nobody read,
and waited for a key over a blank screen. `Write-Host` bypasses the pipeline, so
"Starting..." still appeared — which made it read as a hang.

**Rule.** Anything that hands the terminal to this app is called as a statement.

### 2.2 The app must run in the project, not its own checkout

`Path.cwd()` names the workspace and resolves anything relative. Launching from the
checkout so `python -m company_tui` could find the package made it report *that* as the
project. The venv's interpreter imports from anywhere, so the working directory bought
nothing and cost the project's identity.

---

## 3. A test can pass over nothing at all

### 3.1 `unittest discover` exits 0 when it finds no tests

`tests/` was gitignored, so "discover passes" and "focused tests under `tests/`" were both
satisfied by a directory that could not be committed. Two tests were cited in the docs as
enforcing rules while not existing.

**Rule.** `python -m company_tui check` reports an empty discovery as FAIL. A gate over
nothing is not a gate, and a rule the docs say is enforced has a test with that name.

### 3.2 A detector that finds nothing passes forever

The first emoji check missed `U+23F1 STOPWATCH` — the exact glyph the docs name as one
that got in. Both "no emoji found" assertions passed because the detector found nothing
anywhere.

**Rule.** Every "nothing in the source does X" check carries a test that X is still
detected, and one that the walk finds material at all.

### 3.3 A width test does not find emoji

`U+23F1` is Narrow and is an emoji; `U+2715` is Narrow and is not; `U+274C` is Wide and
is. Width and emoji-ness are different questions, so `tests/test_glyphs.py` bans the
blocks and allows four text glyphs by name.

### 3.4 `uv sync` deletes a linter that is not in the lock

`uv pip install ruff` puts it in the venv, not the lock; `uv sync` then prunes it. The gate
went from `PASS ruff` to `SKIP ruff - not installed` and still finished **"Passed"**.
Nothing lied — the lint had simply stopped running, in a line nobody reads next to a
verdict everybody does.

**Rule.** A tool the gate runs is declared where the lock can see it. The SKIP branch stays
for a genuinely incomplete machine; it must not be where a routine sync puts you.

---

## 4. Your verification harness is code, and it has bugs too

### 4.1 A full-screen app cannot be judged through a pipe

Redirected to a file it emitted 93 bytes of escapes and exited; piped to `head` it drew a
splash; through the dispatcher it hung. Three answers, none about the bug.

**Rule.** Reproduce in a real PTY, and inspect with Textual's `App.run_test()` pilot. A
truncated `winpty` capture is not a finding.

### 4.2 A source assertion matches the comment explaining the rule

A guard for "the dispatcher must not contain `exit (Start-Tui`" failed the moment the
comment saying why that form is forbidden was written beside the fix.

**Rule.** Negative source assertions read a comment-stripped copy, stripped with the
language's own tokenizer — a `#` inside a string is not a comment.

---

## 5. Reading the source

### 5.1 `ast` over regex, always

`"\U0001F600"` is an emoji in the running program and eight innocent characters in the
file. `ast` resolves escapes, tells a docstring from a value, and survives reformatting.

### 5.2 Textual widget internals move

`Static.renderable` does not exist on this version; `App.run_test()` and the compositor do.
Ask the object, do not assume the attribute.

---

## 6. Replacing a program that is running

### 6.1 An installer cannot delete the executable it started from

The installer runs the old uninstaller then `RMDir /r` over the install directory, which
holds the running `dti.exe`. Spawning it as a child and quitting wins the race most of the
time — the worst property a thing like this can have.

**Rule.** The handover is a **third** process that waits for this pid and only then starts
the installer. Arming comes first and quitting follows immediately; reversed, there is
nothing left to arm it.

### 6.2 A remembered installer outlives the version it was for

The launch check records the downloaded installer so a second launch costs no request. The
app then comes back up *as* that version, and the badge offers it again at every launch
forever.

**Rule.** A remembered path is trusted only after four checks: something was fetched, it is
on this build's line, the file is still there, and it is still newer than what is running.

### 6.3 A test's placeholder path became a delete target

`UpdateWatch` took its cache as an argument and tests passed `Path(".")` — harmless while
the cache was only read from. Then `_discard` was added; it emptied the repository root
**twice**, taking `.gitignore` (unmasking the signing key) and `pyproject.toml` (so ruff
began failing on rules this project does not enable).

**Rule.** A destructive loop does not trust a path it was handed. `_discard` refuses any
directory not named `updates` and deletes only `.exe` and `.part`; either guard alone would
have prevented it. No test points a real path at the working directory.

### 6.4 A detached PowerShell is a waiter that does nothing at all

**`powershell.exe` started with `DETACHED_PROCESS` exits 0 without running a line.**
Detached means no console, and PowerShell is a console application. `Popen` succeeded, so
`hand_over` returned `""`, so the app announced an armed handover and shut itself down with
nothing waiting for it. That is the whole of "the in-app update does not work": not a
failing installer, but one that was never started.

It applies to `-Command` and `-File` alike, so it survived the rewrite that replaced one
with the other and had to be found separately.

**Rule.** `CREATE_NO_WINDOW`, never `DETACHED_PROCESS` — a console of its **own**, which is
what "outlives this console" actually required. The flags are asserted by name, because a
test cannot start a real waiter but can refuse the flag that produces a dead one.

### 6.5 A handover that leaves no trace cannot be diagnosed

The waiter was one `-Command` string with the pid and both paths pasted in: the paths were
*code*, there were two escaping layers between Python and PowerShell, and it kept no
record. The visible-retry branch fired on `$done.ExitCode -ne 0`, which is true both when
the installer refused and when it never started — two failures, one behaviour, nothing
written down. By the time any of it matters the app is gone.

**Rule.** The waiter is a `.ps1` generated at runtime into `%TEMP%` with a `param()` block,
so values travel as arguments and quoting stops being a correctness question. It logs
beside itself, deleted on success and kept on failure. **`-ExecutionPolicy Bypass` is not
optional** — `-File` obeys the policy where `-Command` ignored it.

### 6.6 An update that installs a different app succeeds forever

`channel = any` offered whichever release was newest, which on a release install was almost
always a **debug** build — a separate install by design. So the installer ran, exited 0,
put `dti-debug` on the machine, and `dti` was the version it had always been. The offer
came back at every launch.

Every part looked right: feed answered, comparison said newer, download finished, handover
armed, installer succeeded, app relaunched. The only wrong thing was *which install it
updated*, and the running version never changed, so nothing could notice.

**Rule.** The line comes first and the channel cannot overrule it. `wanted()` refuses any
release that could not replace the running build, and the build reads its line off the
command it runs under. An installed build has exactly one line that can replace it; the
channel still decides in a source checkout. `updates.json` is keyed by line too — one file
between two installs is two builds fighting over it.

### 6.7 A key printed on a button that was never bound

`ConfirmScreen(key=...)` draws the chord under the affirmative so somebody who pressed
`Ctrl+U` to get there can see that pressing it again is the same answer. It said so and it
was not true: `BINDINGS` carried `escape` and nothing else, and a `ModalScreen` stops the
app's own copy reaching past it. The one key the dialog named was the one key that did
nothing — and Enter sits on CANCEL, because neither answer may look pre-selected.

**Rule.** A key the interface draws is a key the interface presses. `KeyHint` reads its
label back into the key it sends and so cannot drift; this label could, and did.

### 6.8 An uninstaller that returns before it has finished

The installer upgrades by running the old uninstaller and then writing the new tree. NSIS
uninstallers **copy themselves to `%TEMP%` and return immediately**, so `ExecWait` waits on
a process that has already handed off — and the new files land while the old ones are still
being deleted. What survives is whichever finished last.

**Rule.** `ExecWait '"$R0" /S _?=$R1'`. The `_?=` switch keeps the uninstaller in place,
which is what makes it something `ExecWait` can actually wait for. It also means the
uninstaller cannot delete itself, so the installer removes `Uninstall.exe` and the
directory afterwards.

---

## 7. An argument list is not a list of arguments

### 7.1 A splatted array reaches a command positionally

```powershell
$bumpArgs = @('-Bump', 'minor', '-Yes')
.\script.ps1 bump-version @bumpArgs      # -Bump becomes the VALUE of -Bump
```

Neither obvious repair works: a hashtable splat binds by name at the first hop and is
flattened before `script.ps1` forwards `$args`, and `-Released:$false` comes back as a
positional `False`. Nothing could see it — the array is empty unless somebody ticks a box,
so the splat is a no-op and every gate passed. Both build steps had the defect and had
never once run.

**Rule.** Anything reaching a command through `script.ps1` is a literal token. An optional
switch is chosen in YAML, where substitution leaves a token behind. The `workflow calls`
check reads the workflows for both wrong spellings.

### 7.2 A relative jump over an NSIS macro lands inside it

`IfErrors +2 0` over `!insertmacro UnselectSection` — which expands to **nine**
instructions. `+2` landed on the second `Push` and the flag arithmetic ran against a
corrupted stack. The result was a Components page with the **required** component unchecked
and *"Space required: 0.0 KB"*, from a script that compiled without a warning.

**Rule.** Labels, always, in NSIS. `+N` counts instructions and nothing starting with
`!insertmacro` or `${...}` is one — `${GetOptions}` alone expands to about eighty.
`makensis /PPO` prints the expansion.

### 7.3 A section constant used before its `Section` is index 0

`${SecPath}`, `${SecStartMenu}` and `${SecDesktop}` are defines the compiler creates when
it *reaches* each `Section`. `.onInit` and `RestoreChoice` sat above them, so the constants
did not exist yet and NSIS read the literal text as a section index — **0, which is
SecCore, the required component.**

`RestoreOne "Desktop"` reads the recorded choice back on an update. A desktop shortcut is
off by default, so `"0"` is what every install records — and that `"0"` became
`UnselectSection 0`. The required component was deselected, so the installer ran, wrote
nothing, and **exited 0**.

What that looks like from the app: press the update badge, the toolbox closes, the
installer succeeds, the toolbox reopens on the version it was already running. No error
anywhere — the waiter only re-runs an installer visibly when the exit code is non-zero,
and this one was zero. The first install of a version always worked, because `RestoreChoice`
only runs when a previous version is recorded, which is why it looked like the updater and
not the installer.

The compiler said so on every single build and it read as noise:

```
warning 6000: unknown variable/constant "{SecDesktop}" detected, ignoring
```

**Rule.** `.onInit`, `RestoreOne` and `RestoreChoice` live **below** the sections they
name. Functions can be defined after the code that calls them; constants cannot be used
before they exist. `tests/test_installer_sections.py` reads the file and fails on any
`${SecX}` appearing before the line that declares it — it finds seven in the version that
shipped. And `warning 6000` from `makensis` is not noise: it is a name that silently
became a number.

### 7.4 A silent installer does not report a file it could not replace

Windows will not overwrite a running executable, and in **silent** mode NSIS neither stops
nor says so. Installing over a running copy rewrote `Uninstall.exe` and the whole of
`_internal`, left `dti.exe` at its old bytes, and exited 0 — a half-updated install whose
`_internal/VERSION` reports the *new* version while the program running is the old one.

**Rule.** This is what the handover exists to prevent (6.1): the installer starts only
after the app's pid is gone. Nothing may run it while the app is alive — including a test.

---

## 8. A dependency you cannot patch

### 8.1 A Docker container action builds its image on every run

`github-actions-version-updater` was pinned to a SHA, check-only, no write permission —
every precaution taken. It is a *container* action, so the runner builds the image every
run from a Dockerfile whose `FROM python:3.12-slim-bullseye` then runs `apt-get update`.
Bullseye is archived, so the build fails before a line of the action's code runs. Pinning
made it **worse**: the pin froze a Dockerfile whose base layer kept aging.

**Rule.** For a third-party action, ask what it would cost to reimplement first. This one
was four API calls and a string comparison, and is now `scripts/check-actions.ps1` — which
also removed the PAT it needed. A container action carries somebody else's operating system
into every run.

---

## 9. Talking to a process that is talking back

### 9.1 A scroll container answers the arrow keys first

`RunsScreen` declared `("up", "focus_previous")` and `("down", "focus_next")` and
neither ever fired. A `VerticalScroll` binds the arrow keys to scrolling, and a key goes
to the focused widget and then **up** through its ancestors — so the scroller answers
before the screen is reached, and the list could only be clicked. It had shipped that way.

**Rule.** Bindings that move between rows go on the **row**, which is what has focus, not
on the screen. `PickRow` and `RunRow` both carry `up`/`down` and call
`self.screen.focus_previous()`/`focus_next()`. A binding that never fires is the same
defect as a key hint for a dead key: a control that lies.

### 9.2 `StreamWriter.write` only queues it

The pick written back on the child's stdin never left the transport. The child waited to
read it, this waited on the child's stdout, and neither moved — a deadlock with no error,
no traceback and nothing on screen. It looked exactly like a command that had hung.

**Rule.** `await process.stdin.drain()` after every write. Writing to a pipe is not
sending to a pipe.

### 9.3 A child that reads stdin with no listing outstanding blocks

Nothing can answer a read that no `@dti:rows` asked for. The toolbox is waiting on the
child's stdout while the child waits on our stdin.

**Rule.** This one is left as it is, deliberately: it is the command misbehaving, and the
recourse is the panel's Stop, which cancels the run and kills the child like any other
hung command. What must never happen is the *toolbox* causing it — which is why the pick
is drained (9.2) and why stdin is closed when the run ends.

### 9.4 A screen's own arrival counts as an interaction

The countdown was meant to stop the moment somebody touched the list, and focus moving is
one of the ways somebody touches it. So `PickScreen` cancelled on `DescendantFocus` for any
widget other than the row it had focused on mount — and every countdown was dead before it
drew. `VerticalScroll` is focusable, and the screen focuses it on the way up before the row
gets the focus, so the first `DescendantFocus` of a screen's life names the scroller. The
symptom is a timer that simply never runs: no error, and a hint line showing the seconds it
opened with and then never moving.

**Rule.** Interaction is a key or a press, and focus only follows one of those. Where a
focus change is used as the signal, it has to be narrowed to what a person could have
focused — `isinstance(event.widget, PickRow)` here — because a screen assembling itself
moves focus too, and it does so before anything is on screen to be interacted with.

### 9.5 `@dti:rows` blocks, so anything meant to be beside it has to come first

The browser's status line was a step behind, always showing what the command had said about
the *previous* listing. Nothing was wrong with either end: `@dti:rows` does not return until
the user does something about it, so the toolbox does not read the next line until then, and
a `@dti:status` written after the rows is read only once the listing it described has been
answered. It looks exactly like a status that is not being updated.

**Rule.** A command says what it wants shown beside a listing *before* the listing —
`@dti:view` and `@dti:status` first, then `@dti:rows` — or puts it on the listing itself as
`hint`. And a status has to outlive the listing it arrived with, or the ordering that is
correct would clear itself: `@dti:rows` replaces the status line only when it carries a
`hint` of its own.

### 9.6 A listing that answers a selection can re-ask the question it answered

`"detail": "on-demand"` is the one place where DTI writes to the child because of where the
*focus* is rather than because of something the user committed to. The answer is a fresh
`@dti:rows`, which redraws the pane — and a redraw that put the focus back on the first row
would move the selection, which asks about the new row, which redraws, forever. No error,
no traceback: two processes talking to each other as fast as they can while the screen
flickers.

**Rule.** Two things, and both are load-bearing. A redraw restores the focused row **by id**
(`_draw`), so the answer to a request leaves the user where the request came from. And a row
already asked about is not asked again while it is still the one selected (`_wanted`), so a
command that answers "there is no body for that" ends the exchange instead of continuing it.
`tests/test_browser.py` stands over both.

The request also waits for the selection to settle (`DETAIL_DELAY`) rather than firing per
focus change, because a held arrow key is otherwise a round trip per row.

One cost is accepted rather than fixed: `browse()` is not awaiting anything between
returning a request and the listing that answers it, so a key pressed in that window is
dropped. Navigation still works — the arrows are bindings on the row — and the fix, if this
ever bites, is a stash tied to the listing it was pressed against, not a queue.
