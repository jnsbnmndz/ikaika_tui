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

## 10. Serving a page to a browser

### 10.1 Refusing a body without reading it aborts the connection under the client

The layout builder's server refuses a POST whose `Content-Length` is absurd, and it refused
it the obvious way: answer 413 and do not read the body. Under load that became
`ConnectionAbortedError [WinError 10053]` on the *client*, intermittently — it passed alone
and failed in the full suite, which is the shape of a race and not of a bug in the test.

The client is still writing 300KB when the server answers and closes. Windows aborts the
connection rather than delivering the response, so the client never reads the refusal it was
sent; on a slower machine, or a smaller body, it arrives fine. A refusal that only sometimes
reaches the caller is worse than no refusal.

**Rule.** Read a refused body away before answering, up to a bound (`DRAIN_LIMIT`), and drop
the connection only when there is more than that. The bound is the point: reading an
arbitrary body to be polite about refusing it is the thing the refusal exists to avoid. The
same applies to any early response — `413`, `401`, `400` before parsing — anywhere a body was
announced and not consumed.

### 10.2 A preview that only previews half of what the page arranges

The builder arranges three things — the palette, the menu grid and the window — and the
preview drew two of them. Nothing errored: the window's four numbers were saved correctly
and the preview simply never looked at them, so typing a new start size changed a field and
nothing else on the screen. The Design and Menu tabs answered back instantly, which made the
Window tab read as broken rather than as unpreviewed.

Two smaller versions of the same thing were in the same pane. `Not taken` was filled in only
on the way back from a save, so it stood over an empty list for the whole of a first visit —
a heading with nothing under it, which looks like a list that failed to load rather than like
one with nothing in it. And the preview took its colours as
`doc.layout.themes[doc.layout.theme] || {}`, so a `theme` naming a theme that is not there
assigned `undefined` to every style property; in the DOM that is a no-op, and the frame
quietly kept the builder page's own colours and presented them as the theme.

**Rule.** A preview answers for everything the page next to it can change, or it is a
control with no feedback. Fill an empty report with the words for empty rather than leaving
it blank. And fall back in the preview the same way the domain does — `Layout.palette` falls
back because a theme can be deleted out from under the name pointing at it, and a preview
that renders the wrong colours without saying so is worse than one that renders none.

## 11. Changing a widget's state without rebuilding it

### 11.1 A status in the rebuild signature rebuilds the strip for every question

The tab strip above the terminal rebuilds itself from the registry, guarded by a signature so
it only does that when something has changed. `SessionStatus` was in the signature, and a run
that asks a question changes its session's status to `ASKING` and back. So a command asking
five things tore the whole strip down and built it again ten times, and nobody had asked for
a single one of them.

It is worse than wasted work. `remove_children()` is answered on a later pass but `mount_all`
is not, so between them the strip holds **both** sets of tabs — a four-tab strip measured ten
children — then settles back. That frame is a visible jump in tab widths, and `scroll_visible`
afterwards puts the strip's own scroll back wherever the active tab is. Typing an answer with
the strip flickering above it is the symptom; the status in the signature is the cause, and
nothing in the strip's own code looks wrong.

**Rule.** Split the signature into *shape* and *state*. Rebuild for shape — a tab added,
closed, renamed, or a different one made active — and for state, hand the existing widget the
new value and let it restyle itself (`SessionTab.restate`). A status is a CSS class and a
glyph; neither needs a new widget. The test counts constructor calls across a question rather
than looking at the strip, because a rebuilt strip renders correctly and only misbehaves in
the frame between.

### 11.2 Disabling a focused widget focuses nothing

The stdin row disables its `Input` the moment a question is answered, which is right — there
is nothing to type into. Textual blurs a widget that is disabled under the focus and does not
move the focus on, so the panel was left with `focused is None`: the question was answered and
then no key did anything until the user clicked something or pressed Tab. The same thing by
another route put the focus on COPY, because Textual *does* move focus to the next sibling
when a focused **button** is disabled, and the sibling after SEND is a button about something
else entirely.

**Rule.** A control that takes the focus has to give it back. Remember what was focused when
the question took it and restore that when the question ends, falling back to the panel's
primary control when what held it is gone or disabled by now. Read `self.focused` **once, at
the top**, before anything is disabled — read afterwards it already reports whatever the
framework chose in the meantime, which is the thing being corrected.

## 12. Giving the terminal back

### 12.1 Shutdown sequences queued on a daemon thread are not sequences written

A frozen build was quit and left the terminal printing `^[[<35;61;40M` at every twitch of
the mouse, forever, with `^[[I` and `^[[O` mixed in — mouse motion reports and focus
reports, going to a process that no longer existed, echoed by a console nobody had put
back. The traceback said `KeyboardInterrupt` inside `stop_application_mode` →
`disable_input` → `Thread.join`, and `PYI-14636:ERROR Failed to execute script`.

Three things have to line up, and each is reasonable on its own:

- Textual's `WindowsDriver.write` **enqueues** onto a `WriterThread`, and that thread's
  `flush()` is a documented no-op — "flush is done in the thread". So
  `_disable_mouse_support()` writing `?1000l ?1003l ?1015l ?1006l` and then calling
  `self.flush()` has written nothing to the terminal. It has filled a queue.
- `disable_input()` then blocks on `self._event_thread.join()`, waiting for an input thread
  that is itself blocked reading the console. A `KeyboardInterrupt` landing there is a
  `BaseException`, and that method catches `Exception`, so it escapes.
- The queue is only drained by `close()` → `WriterThread.stop()`, which the escape skips —
  and the thread is a **daemon**, so the interpreter exits without draining it.

So everything after the join is lost: the alt screen is never left, the cursor is never
shown, the kitty keyboard stack is never popped, `?1004l` is never written, and the
`?1003l` that *was* written went into a queue that was thrown away. The console's input
and output modes, saved by `enable_application_mode` and restored only in `close()`, are
left as Textual set them.

This repository is not a bystander: `restore_terminal_interaction` turns `?1000 ?1003
?1015 ?1006 ?1004` **on** whenever the terminal regains focus, and had no counterpart at
all. Anything that arms a terminal owns disarming it, and may not assume the framework's
shutdown will run.

**Rule.** Write the release yourself, in a `finally` around the app, **straight to
`sys.__stdout__`** — never through the driver, which is the thing that may be gone — and
build the off sequence from the same list of modes as the on sequence so the two cannot
drift. Read the console's own modes **before** the app is built, because the framework
overwrites them as it starts and reading afterwards records its modes rather than the
shell's. Every sequence in a release is an *off*, so it is safe on a clean exit too; the
one exception is showing the cursor, which is the restore. And catch `KeyboardInterrupt`
at the top rather than letting it out: a frozen build turns it into a wall of traceback
with `Failed to execute script` under it, over a terminal that is already unusable.

## 13. A panel smaller than what it has to hold

### 13.1 A fixed height is a share that does not shrink, and the overflow is off-screen

A run was started from an editor's side terminal — about 52 columns by 26 rows — and the
command asked a question. The panel showed the form, the Will-run line and a STOP button,
with no terminal under it at all, and nothing could be typed. The run sat there until it
was stopped.

Under `NARROW_WIDTH` the two panes stack, and the form is pinned to `CONFIG_RUNNING` rows
with the output pane taking `1fr` of the rest. That reads as a floor for the form and a
share for the terminal, and it is the wrong way round: `11` is a *size*, so on a short
terminal the form took its eleven rows and the output pane was left with four, while what
it holds — a border, the tab strip, a line of output, and the six rows of the stdin row and
its key — needs eleven. Textual lays the overflow out past the parent's bottom rather than
clipping it to a scroll, so `#stdin-row` was measured at **row 29 of a 24-row screen**. It
was not hidden, or disabled, or unfocusable. It was simply below the screen.

Nothing reports this. The box takes the focus and keeps it, the tab goes orange, the footer
says the run is going, and every one of those is true. A question is being asked somewhere
the user cannot see or reach, which from the other side of the screen is a program that has
hung.

**Rule.** When two panes share a column, decide which one *cannot* be squeezed and give it a
floor, then let the other have what is left — measured from the room there actually is, not
from a constant. Here the form is a record of what was asked for and the stdin row is the
only way to answer; so the form shrinks, and where there is not even room to shrink it, it
goes until the run ends. Fold a margin into that arithmetic by **reading it off the widget**
rather than restating it as a second constant next to the rule that sets it. And test the
geometry across the sizes a terminal is actually given: this fails identically whether the
widget is composed, focused and enabled, so only its measured region says anything.

### 12.2 Omitting `stdin` means inherit, not none

A run was streaming into the panel and a band of raw `^[[<35;69;22M^[[<35;71;22M...`
appeared **across the middle of the live interface**, over both panes, growing with every
twitch of the mouse. The app was not dying and nothing had crashed; it was drawing
normally and something else was writing on top of it.

Those are SGR mouse **motion** reports — terminal *input*. For them to be on the screen,
something had to be reading them off stdin and echoing them. That something was the child.

`asyncio.create_subprocess_exec` and `subprocess.run` with `stdin` left unsaid mean
`stdin=None`, and `None` means **inherit the parent's handle**. `ProcessRunner.stream`
built its `extra` dict as `{}` when there was no `ListView`, and `run` (so also `capture`,
which is `run` on a thread) passed `capture_output=True` and nothing about stdin. Both
therefore handed every child **the console the interface is drawn on** — the one the app
itself had put into virtual-terminal input mode with `?1000h ?1003h ?1015h ?1006h ?1004h`.
A PowerShell child reading that console got the mouse reports and echoed them, onto the
same screen Textual was painting. The docstring on the port said "Without a view there is
no stdin pipe"; it was describing an intention, not the code.

Proved by feeding the parent's own stdin a sentinel and asking what the child could read:
with stdin unsaid the child printed `read:'bytes-meant-for-the-interface'`. A handle
number or a file kind differs per harness; who can read the bytes does not.

The visible garbage is the mild version. Two readers on one handle race for every byte, so
keystrokes and clicks meant for the interface are swallowed at random — and a child that
blocks on a read of that handle never returns at all, which is how this same revert made
the test suite hang rather than fail.

**Rule.** A child that is not being talked to gets `DEVNULL`, explicitly, on every launch
path. Never leave `stdin` unsaid in a program that owns a terminal: the default is the
opposite of what it reads like. A command that legitimately wants input gets a pipe and a
protocol, which here is what a `ListView` already is. And test it by **what the child can
read**, not by what the launch code looks like.
