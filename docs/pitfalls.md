# Pitfalls

Things that have actually gone wrong in this repository, what they looked like, and the
rule that follows. Every one of them was **silent**: a menu that came back, a test that
passed over nothing, a documented rule nothing enforced. None was caught by reading the
code afterwards.

`CLAUDE.md` and `AGENT.md` hold the rules. `docs/decisions/` holds why the architecture is
what it is. This file holds the failures, because a rule with the wreck behind it is
easier to keep than a rule on its own.

---

## 1. A workflow can die where nobody is looking

### 1.1 A step name missing from `TRAIL_STEPS`

`_enter_step` indexes into that tuple to forget a step and everything after it:

```python
for later in TRAIL_STEPS[TRAIL_STEPS.index(step):]:
```

A name that is not in the tuple raises `ValueError`. That exception is caught by the run
supervisor as a failed workflow, written to the session's log, and answered by putting the
previous menu back. So a new `script_section` step made Scripts **open, die and vanish**,
leaving a card menu that looked exactly like nothing had been asked for. No error reached
the screen, because the screen the error would have gone to was never pushed.

**Rule.** A new menu step goes in `TRAIL_STEPS`, in walk order, in the same change that
introduces it. `tests/test_navigation_steps.py` reads the step names back out of the source
with `ast` rather than restating them, so the next one cannot repeat this.

### 1.2 The order in `TRAIL_STEPS` is behaviour, not tidiness

The tuple decides what going back clears. A step listed **after** the steps that come below
it in the walk leaves those standing when the user changes it, so a stale action survives a
change of section.

---

## 2. Output that never reaches the terminal

### 2.1 Parentheses capture a subprocess's stdout

This is a PowerShell trap on the calling side, and it broke the front end of this app:

```powershell
exit (Start-Tui ...)     # WRONG - captures the whole output pipeline
Start-Tui ...            # correct - a statement
exit $LASTEXITCODE
```

A native command's stdout goes into the pipeline. Wrapped in parentheses, the app started,
took the terminal, drew its **entire interface into a value nobody read**, and sat waiting
for a key over a blank screen. `Write-Host` bypasses the pipeline, so the "Starting..."
line still appeared - which made it read as a hang rather than as output being swallowed.

**Rule.** Anything that hands the terminal to this app is called as a statement.

### 2.2 The app must run in the project, not in its own checkout

`Path.cwd()` is what names the workspace in the header and resolves anything relative.
Launching the app from `tui.root` so `python -m company_tui` could find the package made it
report **that checkout** as the project. The venv's own interpreter imports the package from
anywhere, so the working directory bought nothing and cost the project's identity.

---

## 3. A test can pass over nothing at all

### 3.1 `unittest discover` exits 0 when it finds no tests

`tests/` was in `.gitignore`, beside `test/` and `tools/`. So the definition of done asked
for `python -m unittest discover` to pass and for focused tests under `tests/` - and both
were satisfied by a directory that could not be committed to. `discover` printed
`NO TESTS RAN` and exited 0 for as long as that was true.

Two consequences that outlived it: `tests/test_glyphs.py` and `tests/test_window_shape.py`
were **cited in CLAUDE.md and AGENT.md as enforcing rules** while not existing.

**Rule.** `python -m company_tui check` reports an empty discovery as `FAIL`, not `PASS`. A
gate over nothing is not a gate. And a rule the documentation says is enforced has a test
with that name, or the documentation is corrected.

### 3.2 A detector that finds nothing passes forever

The first version of the emoji check missed `U+23F1 STOPWATCH` - the exact glyph the docs
name as one that got in. Both "no emoji found" assertions passed, because the detector
found nothing anywhere.

**Rule.** Every check of the form "nothing in the source does X" carries a test that X is
still detected, and one that the walk still finds material at all.

### 3.3 A width test does not find emoji

`U+23F1 STOPWATCH` is East Asian Narrow and is an emoji. `U+2715 MULTIPLICATION X` is
Narrow and is not. `U+274C CROSS MARK` is Wide and is. Width and emoji-ness are different
questions; `tests/test_glyphs.py` bans the blocks and allows four text glyphs by name.

### 3.4 `uv sync` deletes a linter that is not in the lock

`setup-dev-env -Lint` installed ruff with `uv pip install`, which puts it in the venv and
not in `uv.lock`. `uv sync` prunes anything not in the lock, so it removed ruff — and
`check-all`, which reports a missing linter as SKIP because an incomplete machine is not a
broken repository, went from `PASS ruff` to `SKIP ruff - not installed` and still finished
with **"Passed"**. Nothing lied. The lint had simply stopped running, and the report said
so in a line nobody reads next to a verdict everybody does.

That is 3.1 again by another route: a check that stops checking, arrived at by a command
whose whole job is to make the environment match the lock.

**Rule.** A tool the gate runs is declared where the lock can see it — ruff is in
`[dependency-groups] dev`, so `uv sync` installs it instead of removing it. The SKIP
branch stays, for the machine that genuinely has no linter; what it must not be is the
branch a routine sync puts you on.

---

## 4. Your verification harness is code, and it has bugs too

### 4.1 A full-screen app cannot be judged through a pipe

Redirected to a file the app emitted 93 bytes of terminal-init escapes and exited; through
a pipe to `head` it rendered a splash; through the dispatcher it hung. Three different
answers to the same question, none of them about the bug.

**Rule.** Reproduce in a real PTY (`winpty` will do), and inspect with Textual's own
`App.run_test()` pilot, which drives the real app deterministically and can be asked what
is on screen. `winpty` itself asserts and dies mid-capture when the pty closes - a
truncated capture is not a finding.

### 4.2 A source assertion matches the comment explaining the rule

A guard written as "the dispatcher must not contain `exit (Start-Tui`" failed the moment
the comment saying **why that form is forbidden** was written beside the fix.

**Rule.** Negative source assertions read a comment-stripped copy, stripped with the
language's own tokenizer - a `#` inside a string is not a comment, and only the parser
knows which is which.

---

## 5. Reading the source

### 5.1 `ast` over regex, always

String literals carry escapes: `"\U0001F600"` is an emoji in the running program and eight
innocent characters in the file. `ast` resolves them, tells a docstring from a value, and
survives reformatting.

### 5.2 Textual widget internals move

`Static.renderable` does not exist on this version; `App.run_test()` and the screen's
compositor do. Ask the object, do not assume the attribute.

---

## 6. Replacing a program that is running

### 6.1 An installer cannot delete the executable it was started from

`scripts/installer.nsi` upgrades by running the old uninstaller and then `RMDir /r` over
the install directory. That directory holds `dti.exe`. Windows will not delete or
overwrite a running executable, so an installer started while the toolbox is still alive
reaches its first `File` instruction and stops with **"Error opening file for writing"** —
over an install it has already half removed.

The trap is that the obvious fix looks like it works:

```python
subprocess.Popen([installer])   # WRONG
app.exit()
```

Most of the time the installer's own startup is slower than the app's shutdown and the
race is won. `capabilities/updates.py` carried a paragraph saying so, and refused to run
anything at all, which was the right answer until there was a real one.

**Rule.** The handover is a **third** process that waits for this one by pid and only then
starts the installer (`infrastructure/handover.py`). Arming comes first and quitting
follows immediately — reversed, there is nothing left to arm it.
`tests/test_auto_update.py` asserts that `Wait-Process` precedes `Start-Process` in the
command, because that ordering is the entire difference between an upgrade and a corrupted
install. See `docs/decisions/0004`.

### 6.2 A remembered installer outlives the version it was for

The launch check writes the downloaded installer's path to `updates.json` so a second
launch costs no request. Then the user installs it, the app comes back up **as** that
version — and the state file still names an installer, so the badge offers it again. And
again, at every launch, forever.

**Rule.** A remembered path is trusted only after three checks: something was fetched, the
file is still there, and what it holds is still newer than what is running.
`UpdateWatch._remembered` does all three and clears the state when the third fails.

### 6.3 A test's placeholder path became a delete target

`UpdateWatch` takes its download cache as a constructor argument, and the tests passed
`Path(".")` — the working directory, which is the repository root. Harmless when written:
the cache was only ever *read* from.

Then `_discard` was added, to clear the stale installer after an update. It iterates the
cache and unlinks what it finds. Every test that reached it emptied the repository root:
`README.md`, `CLAUDE.md`, `VERSION`, `pyproject.toml`, `script.ps1`, `uv.lock` and
`.gitignore`, leaving the directories behind. It happened **twice** — once on the run that
introduced it, and again on the next `check-all`, before anyone worked out that running
the tests was what did it.

Three things made it worse than a lost afternoon. `.gitignore` going unmasked `certs/` and
`.dti_configs/signing.env`, so the next `git add -A` would have committed the signing key
and its password. `pyproject.toml` going took ruff's rule selection with it, so the lint
began failing on rules this project does not enable — which is the exact failure that
file's own comment describes. And the run reported `FAIL version — No VERSION file`, which
reads as a bug in the version check rather than as the tests having deleted it.

**Rule.** A destructive loop does not trust a path it was handed. `_discard` refuses any
directory not named `updates` and deletes only `.exe` and `.part` — either guard alone
would have prevented this. And no test points a real path at the working directory:
`_scratch_cache` builds a temporary directory that is genuinely named like the cache, so
the guard is not what makes the tests pass.

`tests/test_auto_update.py::TheSweepDoesNotTrustItsPath` asserts both guards against a
directory shaped like the one that got emptied — `VERSION` and `.gitignore` included —
because "no test does that any more" is a promise about the tests, and this needs to be a
property of the code.

---

## 7. An argument list is not a list of arguments

### 7.1 A splatted array reaches a command positionally

The release workflow built its switches up as an array and splatted it:

```powershell
$bumpArgs = @('-Bump', 'minor', '-Yes')
.\script.ps1 bump-version @bumpArgs
```

Array splatting is **positional**. `-Bump` was passed as the *value* of `-Bump`, `minor`
had nowhere left to go, and the whole release died on
`A positional parameter cannot be found that accepts argument 'minor'`. The two obvious
repairs do not work either: a hashtable splat binds by name at the first hop and is
flattened to values before `script.ps1` forwards the automatic `$args`, and
`-Released:$false` comes back out of that hop as a positional `False`. Only tokens written
at the call site survive it. `script.ps1`'s header had documented the callee half of this
for exactly the same reason and the caller half was still written wrong.

**What made it a pitfall rather than a bug** is that nothing could see it. `check-all`,
`ruff`, `PSScriptAnalyzer` and 149 tests all passed, because the only thing that runs those
lines is a dispatched release, and the array is empty - so the splat is a no-op and the
call works - unless somebody ticks a box. Both build steps carried the same defect and had
never once run.

**Rule.** Anything reaching a command through `script.ps1` is a literal token. An optional
switch is chosen in YAML (`${{ inputs.sign && '-Sign' || '' }}`), where the substitution
leaves a token behind, never in PowerShell, where it leaves a string in an array. The
`workflow calls` check in `check-all` reads the workflows for both wrong spellings, because
a rule the gate cannot see is a rule that only CI can break.

---

## 8. A dependency you cannot patch

### 8.1 A Docker container action builds its image on every run

`saadmk11/github-actions-version-updater` was pinned to a commit SHA, in check-only mode,
holding no write permission — every precaution taken. It still broke, and not in a way any
of those precautions covered.

It is a Docker *container* action (`runs: using: docker`, `image: 'Dockerfile'`), so the
runner **builds the image on every run** from the Dockerfile at that SHA. That Dockerfile
begins `FROM python:3.12-slim-bullseye` and then runs `apt-get update`. Debian bullseye's
repositories have been archived, so the update fails, so the build fails, so the job fails
before executing a line of the action's own code:

```
Docker build failed with exit code 1
Docker build failed with exit code 1, back off 3.449 seconds before retry.
Docker build failed with exit code 1, back off 9.923 seconds before retry.
```

Pinning to a SHA is what you are told to do, and it made this *worse*: the pin froze a
Dockerfile whose base layer kept aging while the pin stayed still. Upstream's `main` had
the same line and v0.9.0 was still the newest tag, so there was nothing to bump to — and a
container action pinned by SHA cannot be patched from outside the repository that owns it.
The only moves available were "wait for a stranger" and "stop using it".

**Rule.** For a third-party action, ask what it would cost to reimplement before adopting
it. This one was four API calls and a string comparison, and it is now
`scripts/check-actions.ps1` — which also removed the Personal Access Token the action
needed, because a script reading the workflow files off the checkout needs no permission
that the default `GITHUB_TOKEN` lacks. A container action carries a build of somebody
else's operating system into every run; a JavaScript action does not, and neither does a
line of PowerShell.
