# CLAUDE.md

Guidance for working in this repository.

This is Developer Toolbox Inventory (DTI) — a Python developer toolbox for repeatable scaffolding and automation. Every name it answers to is in `domain/naming.py`, derived from `APP_SLUG`; four of them are a wire format something else on the machine already speaks, so the new name is written and either is accepted. Its version lives in `VERSION` at the repository root, one line, `x.y.z+n`; `presentation/branding.py` reads it, so a release rewrites one file and nothing restates it (`docs/decisions/0002-the-version-is-one-file.md`). It must remain usable for Flutter, React, and future stacks without coupling the core application to a specific framework.

The interactive UI is themed: `presentation/branding.py` defines `APP_THEME` plus the tagline and version, registered and activated by `TuiConsole` on mount. The theme's own name is `naming.APP_SLUG`, so what is registered and what `TuiConsole` activates cannot drift — a mismatch there is an unstyled app. The wordmark is built from `APP_NAME` rather than written out, and `SPLASH_MARK` is a deliberately abstract placeholder rather than any company's logo. New CSS should reference theme tokens (`$primary`, `$accent`, `$surface`, `$panel`, `$text-muted`, ...) rather than hardcoded colors, so it stays on-brand and adapts if the theme changes.

Every screen sits inside the same chrome from `presentation/chrome.py`: an `AppFrame` border, an `AppHeader` (logo mark, name, tagline, version, workspace status, and a count of runs still going) and an `AppFooter` (key hints on the left, signature on the right). Compose new screens inside `AppFrame` so the app reads as one surface. Menus are responsive — `CardMenuScreen` lays its cards out in a grid at most `CARDS_PER_ROW` wide and swaps full tiles for single-row entries when there isn't room for them, and the accent color is reserved for whatever currently has focus.

Every key hint is also a button. A `KeyHint` reads its own label back into the key it names (`key_for`) and clicking it presses that key, so the mouse reaches everywhere the keyboard does without a second set of controls to keep in step with the first — and so a hint cannot drift from what it does. A hint naming a range rather than a key stays inert instead of lighting up for a press it could never send, and so does one whose key is dead at the time. Add a hint by putting it in a footer's tuples; do not wire a handler to it.

Nothing the interface draws may be an emoji, and `tests/test_glyphs.py` checks rather than trusts — reading every string literal in the package with `ast`, so an escape like `"😀"` is caught however innocent it looks in the file. The check bans the emoji Unicode blocks outright and allows four text glyphs (`✓ ✕ ✗ ❯`) by name, because width does not separate them: `U+23F1 STOPWATCH` is narrow and is an emoji, `U+2715 MULTIPLICATION X` is narrow and is not. A codepoint a terminal treats as emoji is rendered from an emoji font instead of a text one: double width, so every column after it is wrong, in a colour that ignores the theme and at a weight nothing like the box-drawing art beside it. This is easy to get wrong because these codepoints read fine in an editor — a stop mark on the Run button and a stopwatch on each run's timestamp both got in that way. Draw from the geometric shapes, dingbat and box-drawing blocks (`◆ ✓ ▲ ✗ ● ○ ✕ ❯ ▸ ■`); if nothing legible is available, use no glyph and let colour do the work.

A button is an outline, and focus **doubles** its border — never fills it. Colour says which answer is which (`$warning` for the way back, `$error` for the step there is no way back from) and is the same colour focused or not, border and label alike; the doubled line says which one Enter would take. A filled answer reads as an answer already chosen, and every question `ConfirmScreen` asks — quit with runs going, overwrite a tree, close a live tab — is about something that cannot be undone, so neither answer may look pre-selected. Focus doubles the line rather than recolouring it because a recoloured border would be the answer's own colour arguing with the focus colour. A confirmation is a title, an optional `detail` saying what saying yes costs, and two answers; a dialog reached by a chord puts that chord under the affirmative's label (`key`), so someone who pressed `Ctrl+Q` to get there can see that pressing it again is the same answer. A checkbox follows the same rule and is *only the box* (`FieldToggle`): Textual's ships as a mark and its label in one widget, so the words of a question are part of the control that answers it — a stray click on the text answers it, and focus paints a reversed block behind it. The label is a `Static` beside the box instead, so a click has to land on the box, hover lights what the pointer is actually over, and the label never changes. The box says everything: doubled while it is on, orange when on (`TOGGLE_ON` in `branding.py`, interpolated rather than a theme variable — a widget's `DEFAULT_CSS` is parsed before any theme is active, so `$toggle-on` would be an undefined reference), blue under the pointer, gold under the keyboard, with focus beating hover because that is the one a key press is about to act on.

The border is the *only* thing focus changes — not the label's colour, not its weight, and nothing behind it. That takes `!important` on border, background and `text-style`, plus `background-tint: 0%` and a neutral `tint`, because Textual paints a background on `:focus` and `:hover`, `flat=True` adds a class that outranks a plain `Screen Button` type selector, and `$button-focus-text-style` is `bold reverse` — the reverse swaps the label's colours and arrives at a filled button by another route however transparent the background is.

Anything clickable made of more than one widget mixes in `HoverLight` (`presentation/chrome.py`) rather than writing a `:hover` rule. Textual puts `:hover` on the *innermost* widget under the pointer, so `Parent:hover .child` asks about a state its ancestor never has and silently never matches — which is why a hint could only light the half being pointed at and why a tab lit nothing at all. The mixin gives the parent a `-hovered` class off `Enter`/`Leave`; hang the rule on that.

## Commands

```sh
python -m company_tui                  # interactive Textual UI
python -m company_tui --start scripts  # open straight on a capability
python -m company_tui list             # plain stdout, scriptable
python -m company_tui doctor           # plain stdout, scriptable
python -m company_tui check            # everything the definition of done asks for
python -m unittest discover
```

Building, releasing and signing go through one PowerShell entry point, and the
GitHub Actions workflows call that same file rather than restating the steps in
YAML — a workflow with its own list of steps is a second, silently diverging
answer to what a release is, and it is the one nobody can run locally.

```powershell
.\script.ps1                              # commands are discovered from scripts\
.\script.ps1 setup-dev-env -Build -Lint   # make a machine able to build
.\script.ps1 check-all                    # the gate; -InstallHook for pre-push
.\script.ps1 setup-signing                # release and debug certificates
.\script.ps1 bump-version -Bump patch     # rewrite VERSION, commit, tag
.\script.ps1 build-app -Sign              # freeze with PyInstaller
.\script.ps1 build-installer -Sign        # wrap it in NSIS
```

The installer is per-user, adds its directory to the user PATH so the app starts by
typing `dti` (`/NOPATH` opts out), and installs `dti.exe` rather than a version-named
exe — the folder under `dist/` carries the version, the command does not. **The
PATH edit goes through `scripts/lib/path-entry.ps1` and .NET, never NSIS**:
`NSIS_MAX_STRLEN` is 1024, `ReadRegStr` truncates silently at it, and writing that
back is how an installer eats somebody's PATH. That file carries the numbers that
make it a real risk on this machine rather than a theoretical one.

The build number rises **globally** and comes from the **tags**, not from
`VERSION`: an installer compares it, so a reset makes an upgrade look older than
what is installed. `-Released` tags `v<x.y.z>-released` and is what makes a build
official; debug builds are published as prereleases so `Check for Updates`, which
asks for the latest official release, cannot offer one. `bump-version` commits and
tags but never pushes.

## Dependency direction

```text
presentation → application → domain
infrastructure → domain
capabilities → domain ports
templates → domain ports
bootstrap → all concrete implementations
```

The domain has no terminal, filesystem, subprocess, framework, or network dependencies. Application code coordinates capabilities. Infrastructure implements external interactions. Presentation renders and collects input — via `PlainConsole` (plain stdout, used by `list`/`doctor`) or `TuiConsole` (the interactive Textual app), both satisfying the same `presentation.ui.Ui` protocol. Each stack under `templates/<stack>/` implements the `TemplatePack` contract the same way infrastructure implements domain ports. `bootstrap.py` constructs the object graph.

Workflows that need input declare it as `Option`s (`domain/options.py`) rather than asking question by question. `Ui.open_run_panel` renders them as one form — in the TUI that is `RunScreen`, a scrollable config pane on the left and a live terminal on the right — and keeps the panel open while the work runs, so `write`/`ask`/`confirm` land in that terminal instead of in modal dialogs. Use `ProcessRunner.stream` for anything slow enough that the user should watch it.

A finished run offers the form back, not just the exit: `close_run_panel` returns `True` when the user wants another go, so write a capability as a loop around `open_run_panel`/`close_run_panel` rather than a single pass. Making a second project should not mean walking back out to the menu and choosing the same things again.

Anything the user starts, the user can stop. Hand the work to `Ui.run_in_panel` instead of awaiting it directly: the panel's Stop cancels that task and `run_in_panel` returns `None`, a cancelled `stream` kills its child, and a pack that left something half-written cleans up as it unwinds. Always finish with `close_run_panel(message, ok)` — that is what tells the panel the run is over and lets the user leave.

`Application.run()`, `Capability.execute()`, and `TemplatePack.scaffold()`/`.build()` are all `async def`, because `TuiConsole` can only wait for a screen's result (`push_screen_wait()`) from a worker. Keep new capability/pack code on this `await` chain rather than adding a synchronous path.

## Sessions

Several runs happen at once, and the panel shows one of them. A `RunSession` (`presentation/session.py`) owns everything one run has — its form, its values, its log, its task, whatever it is waiting on — and `RunScreen` renders whichever session is selected, replaying that session's log when it attaches. The strip above the terminal gets the whole width: it scrolls to the wheel as well as to the keyboard, keeps the active tab in view, and gives each tab a close mark. The keys that act on it live at the foot of the pane, under the stdin row — anything sharing the strip's row is width the tabs do not get, and the tabs are the only thing there with no fixed size. Esc leaves a run going and hands back the menu it was started from, one step back rather than out to the top; Stop is on the button.

A tab outlives the app; a run does not. What is written down between one launch and the next is everything the user put in — the name they gave the tab, the stack it belongs to, the form they filled in and what the last run printed — and none of what was doing the work (`domain/session_memory.py`, stored as JSON under the user's home by `infrastructure/session_file.py`, keyed by the directory the toolbox was started in). A killed subprocess cannot be resumed, so a restored tab is **idle**: no task, no "running", and its output comes back wrapped in a line saying it belongs to a session that is over — output with nothing above it reads as this run's, which for a scaffold that died half way through a clone is a claim about a directory that is not true.

Restoring happens *in place*. No menu is skipped and nothing is resumed: a restored tab simply has no workflow behind it, so the first workflow to walk into that context adopts it through the same `_relocate` that already picks up a tab left from earlier in the session. That is also why `_teach` hands the walking workflow to every idle tab in the context — a callable is not something JSON can hold, and the strip's "+" is "another one of these". Tabs are written down when a run ends, when one is renamed or closed, and when the app is quit; never per line of output, which for a build printing tens of thousands of them is the same mistake as a window resized per frame.

Esc on a running panel backgrounds the run and puts back the menu that started it (`_resume_behind`), by opening a sibling session whose `preset` repeats every step except the last — so the run keeps going in its own tab and the user is one step back, not out at the front door. That sibling has to be spawned *before* the old run is backgrounded: freeing the foreground with nothing else holding it releases the menu loop, and the top menu it puts up would land underneath. A panel with no menu behind it (`len(steps) < 2`) has no step to go back to, and there Esc is only ever leaving.

Taking the panel off the screen and backgrounding a run are separate acts, and only the second one frees the menu loop. A run whose panel closed because the user backed out of its form is still mid-workflow and about to show a menu of its own; freeing the loop there pushes a second menu over the top of it.

That same session then serves the rest of the workflow, so what a form was answered with belongs to the attempt rather than to the session and `load` re-arms it. A session that carried "backed out" forward would answer the next form before it was on screen, and the menu the user came back to would send them straight back to itself. Its log follows the same line: a `$` prompt marks a run, so walking in and out of a form reuses the prompt already there rather than stacking up a transcript of runs that never happened.

Which log a line lands in is decided by `CURRENT_SESSION`, a `ContextVar` set when a session's task starts. Async tasks inherit the context they were created in, so every `write`/`ask`/`confirm` inside a workflow — and every subprocess callback under it — resolves to that workflow's own session without a single capability knowing sessions exist. **Never route output by "the panel that is open"**; that is the model this replaced, and it is wrong the moment there is more than one run.

`Application.run()` hands each capability to `Ui.start_run` as a callable rather than awaiting it. The console runs it as its own Textual worker (a worker, not a bare task, so a run started from a keypress can still push a screen), and `start_run` returns when that run lets go of the screen — which is not when it finishes. Keeping the workflow as a callable is also what makes the strip's "+" one more call: a second tab in the same context repeats the first one's menu answers from `session.preset` instead of asking again.

Every context gets its own strip. A session's `scope` is the breadcrumb it was made under (`{capability, scaffold_target, template_pack}`), **settled once, at creation** — deliberately a snapshot and not a reading of `steps`, which keeps changing as the workflow walks. A tab that re-homed itself on every choice would follow the user out of the context it is holding a directory and a log for, which is how one terminal came to carry two stacks' runs. A workflow that walks somewhere else gets a session *there* instead: `_relocate` moves it at `open_run_panel`, which is the first moment the context is fully known, and drops the tab behind it because nothing ever ran in it. `session.place` is where the workflow has got to; `session.scope` is where the tab belongs, and they differ exactly when a move is due.

A tab outlives the workflow that made it. `_retire` frees a session (`task = None`) rather than removing it once anything has been run there (`session.ran`), so walking back into a stack picks that tab up — its output, the time it ran and the form it was sent all still in it, and `load` keeps the answers rather than blanking them. Only a tab nothing was ever run in is dropped. Walking into a stack whose tabs are all mid-run attaches the run instead of opening a form beside it: there is nothing to fill in, and the workflow that walked in waits for the screen, which it gets back as the menu it came from. That is also why `_resume_behind` checks whether anything else is already holding the foreground — two workflows putting up the same menu is two menus.

Not every session is a tab. Every workflow owns one from the moment it starts, long before it knows which context it is for — it is what carries the breadcrumb and the answers while the user is still walking menus — so `session.opened`, set by `load`, is what makes one a tab. `visible` and `summary` count tabs; counting sessions is how a strip grew an entry nothing had ever been in and the chrome reported a run waiting that was really a menu. For the same reason `_relocate` only ever attaches a tab with a form actually on it: one whose own workflow has walked off to a menu has nothing to show, and attaching it put up a run panel with an empty configuration pane.

They still live in one `SessionRegistry` — a session that existed only inside its own context would be reachable only by walking the menus back to it from memory. `visible(scope)` is a real filter, so a run from elsewhere is not in this strip at all; what stops it being forgotten is `running_under(place)`, which counts by *prefix* so each menu card says how many runs are going behind it, plus the running total in the chrome and `Ctrl+B` — which opens `RunsScreen`, the one view that can list every run there is, each saying where it lives. Tabs are numbered per context too, so every stack opens on its own first tab. Work you cannot see is work you forget about — but a tail of runs from everywhere else puts back exactly what a strip per context removes.

Output goes into a panel and it has to be able to come back out. The terminal is a `SelectableLog` (`presentation/run_screen.py`): Textual selects by reading a per-cell offset off whatever a widget drew and handing that widget back a range in its own coordinates, and a stock `RichLog` writes neither — it keeps finished `Strip`s and paints them — so a drag across it reported no offsets, the screen fell back to selecting the whole widget, and the whole widget answered with nothing. `render_line` stamps the offsets and paints the selected span; `get_selection` reads the text back off the same strips. The highlight goes on as a `post_style` and as a **background only**: applied underneath it would lose to the colour the log has already given every cell, and applied as a whole style it would repaint the markers — which are the reason somebody is copying a failed run out in the first place. Beside Send are COPY and CLEAR, disabled while the terminal holds nothing but its prompt. COPY sends the whole transcript rather than the selection, deliberately: a press is a click, a click is what ends a drag, and the selection is already gone by the time the button hears about it — selected text has Ctrl+C, which the screen answers before the app's own binding for that key. It is read off `RunSession.transcript` rather than off the widget, so lines come out at their own length instead of broken at whatever column the window was that afternoon. CLEAR empties the session, not the view — clearing only what is drawn leaves every line still held, still written down at the next save, and back on screen the moment the user switches tabs and switches back — and it leaves the prompt, which is the only line saying which stack and which workflow this tab is.

Two things follow from runs happening side by side. Log buffers are capped (`LOG_LIMIT`) — `npm install` alone emits tens of thousands of lines, and N sessions holding all of them is a leak with a progress bar on it. And a destination can only be written by one run at a time (`domain/destinations.py`), claimed by `ScaffoldCapability` before the work is handed over: two runs aimed at the same directory is not a race either can win, since one removes the tree the other is halfway through cloning into.

## Scaffolding

Every project the toolbox produces carries `dti.script.json` — `version`, `name`, `description`, `title` — whether it was cloned or written file by file. A project carrying the older `ikaika.script.json` is still recognised, and a file that already exists keeps its name (`naming.manifest_path`) rather than being left behind holding a stale copy of the same four keys. It is what makes a directory one of these projects: `ProjectFinalizer.require_project` refuses to finish a scaffold without one, and the generators refuse to run outside one. Only those four keys belong to the toolbox; a template's other keys are read and written back untouched, in order and at the template's own indent (`domain/json_document.py`).

A pack decides only how the tree appears. What happens next is `ProjectFinalizer` (`domain/scaffolding.py`), the same for every stack: stamp the identity, seed `.env` from `.env.example`, drop the template's `.git` and start a repository with a first commit. Files besides the manifest that also carry the project's name are stack-specific and declared as `IdentityRewrite`s — for React Native that is Expo's `app.json` (`templates/react_native/expo.py`), which spells the name four ways and inherits the template's EAS project id unless it is dropped.

A name is parsed once, in `context_from`, into a `ProjectName` (`domain/project_name.py`) that hands each stack its own spelling — `slug`, `snake`, `compact`, `pascal`, `camel`, `title`. Parsing is also the guard: `.`, `..`, and absolute paths are refused before a pack turns the name into a directory it will delete and recreate. Use `ProjectName.existing` to read a name back out of a manifest, where validation does not apply.

Where a stack clones from, which ref of it is current, the organisation's bundle prefix and the workspace root come from `ConfigPort` (`dti.toml`, or an existing `ikaika.toml`), not from constants — pinning a template should be a settings edit. The Settings capability is that edit: the same run panel, writing either the project file or the user one, and `FileConfig` forgets what it read on save so the change applies without a restart. Packs declare the executables they need as `ToolRequirement`s so a run fails fast with a sentence and Doctor can report the same facts. A script repository declares nothing of the sort and does not have to: what it needs is *derived* from the commands it writes — token zero of each, skipping a name written as a reference (nothing can resolve it before a form exists) and one with a path in it (`node` is a tool, `scripts/build.mjs` is an argument to it). Derived rather than declared because it cannot then drift: it is the command that is actually going to run, and a repository that starts calling `pnpm` says so by calling it. Checked before the setup commands run and before an action stages its template — a tool that is not on this machine will not be on it a moment later, and the alternative is writing a file only to take it back out. Doctor reads the same list off the store, without fetching, so its one line per tool says which stacks and which stacks' scripts want it.

## Build scripts

A stack's build workflows are not in this repository. They are a repository of their own — templates, the program that finishes them, and a `dti.script.json` saying how the two go together — cloned once into `scripts_root` (`~/.dti/scripts` by default, or an existing `~/.ikaika`, which is used where it is rather than left behind holding every cloned repository) under `<owner>/<repo>`, and shared by every project on the machine. React Native's is `JDM-Github/react_native_scripts`. Adding a generator is an edit to *that* repository rather than a release of the toolbox: `domain/script_config.py` reads whatever `config` declares and Build is a menu of it, which is why the actions are asked for between the stack menu and the panel — the first moment there is a stack to ask, and the last before the user is looking at a form.

A repository already in the store is left exactly as it is: never pulled, never checked out over. That directory is the copy the user edits, which is the whole point of keeping one, and a toolbox that quietly reset it would be taking that back. Which revision arrives is settled at the clone, from `[scripts.<pack>] ref` in `dti.toml`, and the clone is a whole one rather than a shallow one because this history is worked in rather than thrown away a moment later — and because a clone with a remote can be asked what it has published since.

A clone is not an install. A repository that carries a program of its own declares `after-clone-command`, and it runs once, in the store, as part of arriving — before anything is read out of that directory and before any menu is built from it. A store whose setup failed is **thrown away**, the same as a clone that failed: half an install is the same hazard as half a clone, only quieter, because everything is present, nothing says so, and what fails is a build three menus later with an error from inside somebody else's tool. Nothing can answer a `${...}` at clone time — there is no project yet — so a setup command carrying one is refused rather than run with the reference passed through as an argument. Its output is streamed but written *down* rather than *out*: there is no panel here, so a line would land in the activity log in the header's margin, and `npm install` writes tens of thousands of them, most a progress bar redrawing itself. They go into a bounded tail that is read out only if the command fails — `working` is already holding a mark up for the wait. Streamed rather than captured because `capture` is a thread, and cancelling a thread cancels the waiting and not the work; `stream` kills its child. A stopped fetch throws the store away too, which matters more with setup to run than it did for the clone alone: a complete clone whose install was stopped half way is a directory that passes every test the next run makes of it.

That is the one question the toolbox does ask: opening Build fetches the configured ref and reads the manifest **out of the fetched objects** (`git show FETCH_HEAD:...`), never out of the working tree, so finding out what the remote has cannot disturb the copy being run. *Different* rather than *older*: these are the manifest's own words and nothing here knows how a repository counts, so ordering two strings nobody defined an order for is not attempted. Every failure — offline, no such ref, unparseable — is silence, because a version check is a courtesy and a courtesy that reports its own plumbing is noise.

Being behind is a menu, not a dialog, because there are three answers and `ConfirmScreen` offers exactly two: re-clone, keep this copy, or stop asking. It comes up *before* the workflow menu, since that menu is built out of the copy in question and replacing it underneath would mean the user chose from a list they did not get — and before the walk decides there is no such menu, since *that* is read out of the same copy. A store one version back declaring no workflow is a store that may have grown one, and asking after the fall-back had already been chosen is how Build came to report that a stack has no build workflow on the strength of a manifest it had just been told was stale. What the question was answered with then has nowhere to be a notice — the fall-back is not a menu — so it is written where the fall-back's own message goes, ahead of it. Keeping it is settled for that walk through Build and asked again next time; re-cloning is the only step that throws away work, and the card says so rather than the aftermath. "Stop asking" writes `check = false` — into whichever file is actually being read, not always the user's, because settings are one file winning outright rather than two merged and a preference written where nothing reads it is a question that keeps being asked. Settings holds the same controls permanently: a row per stack saying what is in the store and at which version, a toggle that installs it or replaces it, and the watch toggle. Drawing that form fetches nothing — a form has to be on screen before anyone can ask for anything, and opening Settings must never be what clones a repository.

`config` holds a section per kind of work. A section carrying `args`, `path`, `template` or `command-after-success` **is** an action (`config.build`); anything else is a group of them (`config.scaffold`, and its twelve). Told apart by what they carry rather than by name, because a repository gets to call its sections whatever it likes.

Everything is written in `${...}` against one map: `${root}` is the project the action was aimed at, **always absolute**; `${<action>.args.<flag>}` is what the form came back with; `${<action>.path}` and `${<action>.filename}` are the expanded target, so a `message-exists` can name the file it refused to write. A reference nothing answers is *left in place* rather than blanked — `${root}/src` with the root blanked is `/src`, a real path to somewhere nobody chose — and `unresolved` is what refuses to act on one.

**A path with no `${root}` in front of it belongs to the script repository, not the project.** `templates/screen.template.tsx` is the repository's copy; `${root}/templates/...` would be the project's own. Commands run with that repository as their working directory for the same reason — it is what makes a bare `node scripts/finalize-scaffold-template.mjs` mean the copy beside the config that named it — and it is why `${root}` has to be absolute by the time a command sees it. A relative one would be read from the repository instead of from the project. Put the other way: a command runs where its config lives, so a project carrying a `config` of its own runs in the project.

Commands are split into an argument array *before* the references are filled in, never after. A Windows path substituted first arrives full of backslashes, every one of which is an escape to the splitter, and `C:\src` comes back out as `C:src` — a path to somewhere that does not exist and, occasionally, to somewhere that does.

The directories on a path are made on the way; a config naming a folder this project has not needed yet is describing where the file goes, not asserting somebody already made room for it. What is not made on the way is a file over one already there — that is `message-exists`, and it is a refusal rather than a prompt because the config wrote the wording for it. The one thing that waives it is the config's own question: a declared boolean argument spelled `overwrite`, answered yes on the form. A convention and the narrowest one that works — an action that never asks cannot be answered, so every other `message-exists` stands exactly where it stood, and the alternative was reading flags back out of `command-after-success`, which is guessing at a shell line to find out what the form already said. A declared boolean therefore always reaches that line as one of two words: `--overwrite ""` is not a no to any program that reads it. Until the command after it has run, a staged template is still the raw template, comment wrapper and placeholders intact, so a failed command and a stopped run both take it back out: that file sitting where the finished one belongs is worse than no file at all. Take *back out*, not delete — a staging that replaced something remembers what it replaced and puts it back, because removing what a failed run wrote over is right for a file this run invented and wrong for one somebody had been editing since March.

`rules` is the vocabulary a repository claims, not decoration. A constraint is applied only where `rules` says that type carries it, so a repository that drops `allowed_regex` from `rules.string` has said its strings are unconstrained, and enforcing a pattern it stopped declaring would be this toolbox overruling the file it is meant to be reading. What a refusal reports is the config's own `message-invalid-*`; the specific reason goes above it in the terminal, where somebody fixing the typo will read it.

One store, two menus. An action carrying a template and a filename puts a file into a project that already exists, and that is **Scaffold → Components**; everything else is **Build**. Split by what an action carries rather than by which section it sits in, for the same reason a section is told from a group of them — a repository gets to call its sections whatever it likes, and one that renamed `config.scaffold` would otherwise find its generators had left the menu. Neither menu lists the other's half: one action reachable two ways is one action with two breadcrumbs, two tabs and two places to look for the run you started. The walk itself — read the store, ask about a version that has moved, choose, fill in, run, offer another — is written once in `capabilities/script_actions.py` and handed a filter.

A stack whose store offers nothing of the kind asked for falls back rather than reporting anything — once the version question above has been settled — because nothing to choose between is not a problem: Build runs the build the pack ships with (`TemplatePack.build`), and Components offers the generators the pack ships with (`TemplatePack.generators`), which is the only thing Components could mean for a stack that has never had scripts.

## A project's own commands

Build runs the workflows a *stack's* script repository declares. **Scripts** runs the ones the project in front of you declares, out of the `dti.script.json` in its own root (either spelling — see `domain/naming.py`) — the case above already allows for when it says a command runs where its config lives, so a project carrying a `config` of its own runs in the project. `docs/decisions/0001-a-project-declares-its-own-commands.md` is why.

Nothing in `capabilities/scripts.py` knows what wrote that file. A sibling PowerShell toolkit emits one describing every command it can dispatch, and that is what this was built for and deliberately not what it depends on: a project whose commands are npm scripts, a Makefile, or a shell script per task declares them the same way and arrives at the same menus. The document is the contract; the program that produced it is not.

The walk is section, then action, then the run panel. Sections come from `config`'s own grouping rather than one invented here — a repository that declares fifty actions has already said how it thinks about them, and fifty cards in one grid is a list to scroll rather than a choice to make. The run itself is `templates/scripts.py: run_action`, the same function Build and Components go through: an action with no template and no path skips the staging half and runs what the config named, which keeps the parts that are easy to leave out — answers checked against the document's own rules, tools looked for on the machine before anything runs, and a stopped run unwinding to the subprocess.

Which project it is comes from `DTI_PROJECT_ROOT` — or the older `IKAIKA_PROJECT_ROOT`, which is still read, the new name winning where both are set — then the working directory. The toolbox may be started from its own checkout while driving another tree, so the directory it happens to be in is not always the answer.

A launcher can open straight on a capability — `python -m company_tui --start scripts`, which is what a bare `script.ps1` does. It is answered through the same `_enter_step`/`_record` a real menu choice makes, so the breadcrumb, the session's scope and the tab it lands in are identical either way; only the first call honours it, so backing out reaches the menu and nothing becomes unreachable. **A new menu step must go in `TRAIL_STEPS`** — one that is missing raises inside the run supervisor, which reports a failed workflow into a log nobody is reading and puts the previous menu back. See `docs/pitfalls.md` 1.1.

## Transitions

Every step of a workflow pops one screen before pushing the next, so the app's own screen shows in between. It carries the same chrome, and its activity log stays hidden (`-quiet`) until something is written to it, so the gap reads as the same surface rather than as somewhere else. A workflow that sends the user back therefore passes a `notice` to the menu they land on instead of writing to the console, which would put the message behind whatever comes next. What a workflow without a panel does write there is read at the pause that follows it, and the log is emptied and hidden again when the menu loop comes back round — a line left standing shows through every later gap as if the workflow now running had said it.

That gap is also where a step goes when it has nothing else to stand on, and a step that goes to the network stays there. `Ui.working(label, work)` is `run_in_panel`'s counterpart for it: the app's own frame grows a `BusyLine` under the header, in the margin the activity log uses, so a step that also narrates itself reads as this line and then its output rather than as somewhere else. Only after `BUSY_DELAY` — announcing the tenth of a second most steps take would be a mark that appears and vanishes at every choice the user makes. Build uses it twice, around reading a stack's scripts and around replacing them, because both fetch and neither has a panel; a full frame that stays put for four seconds is indistinguishable from a wedged one. The mark turns on a timer that exists only while something is being waited for, and a cancel reaches the work rather than orphaning it: `asyncio.wait` hands a cancel on without touching what it was waiting for, and a fetch left running past the workflow that wanted it is a subprocess nothing will ever reap.

What frees the menu loop is every session letting go of the screen (`_settle` over `session.foreground`), so anything that holds it and never lets go stops the loop coming round: the app draws its own empty frame and the only key still doing anything is the quit chord. A session is born *wanting* the foreground, because a session is normally born to run something and what clears it is being backgrounded — which never happens to a tab that was never started. So `SessionRegistry.restore` clears it, and three tabs left over from yesterday are not three things the next workflow's ending has to get past.

Esc is how the user walks back through all of this, so the last one cannot also be how they leave: backing out of the top menu asks first (`_confirm_quit(deliberate=False)`). The quit chords `Ctrl+Q` and `Ctrl+C` are aimed rather than walked into and go straight out — unless a run is live, which always asks, because that is N directories abandoned rather than none.

Entrances are for taking the edge off a repaint, not for being watched: the grid is sized first and then the whole menu body — trail, notice, title, subtitle and cards — comes in as one, over `CARD_ENTRANCE_DURATION`. Staggering the cards read as the menu loading, and every step of every workflow paid for it. Staggering the body against the chrome was worse: density can only be measured once there is a layout to measure, so a menu that reveals its title first is legible for a tenth of a second before it has any cards, and half-built at a glance is not this menu loading but a different menu — which made every step of every workflow look like it went somewhere else on the way. What shows in the meantime is the same chrome the gap between screens already shows, so the two are one pause rather than two.

Threads are not the lever here — Textual is single-threaded and the interface is idle during a transition. What does block it is a synchronous subprocess, so anything run while a screen is up goes through `ProcessRunner.capture` rather than `run`.

## Window shape

The window opens at the size `DEFAULT_PLAN` names — a square of `START_SIDE` a side by default, held to a floor of `MIN_WIDTH` x `MIN_HEIGHT` — and those four constants are the whole of what is meant to be edited. `plan_for` reads the *plan* rather than the constants behind it, so the two cannot disagree: the version that read `START_SIDE` there honoured a non-square `DEFAULT_PLAN` only on a screen too small to measure, which is to say on nobody's machine. Both come off the screen rather than out of the source, because a floor the display has no room for is a floor nothing can stand on: `plan_for` shrinks the start size to the work area's height less `SCREEN_MARGIN` where there is not room for the whole of it — the width coming down with it, so the shape survives and a square stays a square — and a shrunken start size becomes its own floor, since a floor bigger than the window it is the floor for would resize the window for opening at the size it was told to open at. The *work area* rather than the display, so the bottom edge and the footer's key hints do not open behind the taskbar. `TuiConsole` reads the plan once, at mount: a floor that moved under a window the user had already settled would resize it for having been dragged onto another display.

A window under the floor that cannot be put back on it is `WINDOW_NOTICE` (`▲ window 1168x560 → 800x600`) in the header — what it is against what it should be, because "too small" without a number leaves the user dragging an edge and guessing. That is a *maximized* window on a short screen, or one two asks did not manage to grow; see below for why there are only two.

**A resize from the app is the most expensive thing in this codebase, and there are exactly two moments where one is allowed.** This started out holding the window to a floor *and* to a `1.263:1` ratio, correcting it ten times a second, and on a 150%-scaled display it pegged the CPU and the GPU until the display driver reset — a black screen, an unthemed title bar coming back, and an interface that could be pointed at but not used. Three things compounded, and only the first is obvious:

- The window being corrected is usually **another process's** — under Windows Terminal the window on screen belongs to Terminal — and `SetWindowPos` on a foreign window blocks the calling thread, which is Textual's event loop, until that process has handled the resize and re-rasterized its whole grid.
- Every correction is a real resize, so the terminal remeasures its cell grid and hands the app a new size: a full relayout and repaint here, on top of the terminal's own re-render and a compositor pass.
- It never converged. A terminal snaps a window to whole character cells, and DPI virtualization rounds every size on the way in and again on the way back out, so what is read back is never quite what was asked for, the test fails again, and the next tick asks again. Remembering the last size that was refused cannot help when no two refusals are the same size.

So the ratio is a layout target and nothing checks it: nobody hits a ratio by dragging a window edge — on a scaled display nothing lands within a pixel of one — and a notice that is always showing is a notice nobody reads. What is left is `SizeGuard`, written against all three of those and allowed two moments. `open_at_start_size` asks once, as the app mounts, and not at all if the window is already that size, maximized (the user asked for the whole screen more recently than this did) or minimized. `hold` asks only when a window that does not fit has **stopped being dragged** — `dragging()` reads `GetAsyncKeyState` and says to wait — because a drag inwards is where every one of those ten-a-second corrections came from: the window is under the floor for the whole of one, and the user is still holding the edge being fought over. Non-convergence is bounded rather than reasoned about: `RESIZE_ATTEMPTS` asks are all one shortfall ever gets, and the budget refills only once the window has fit, so a size this window cannot have costs two calls and then goes back to being a sentence in the chrome. `SNAP_SLACK` is why it is usually reached on the first ask — a terminal snaps a window down to whole cells, so a request for exactly the floor comes back under it and leaves the notice standing over a window that looks right; the slack goes on the short edge only, so an edge that already clears its floor stays where the user dragged it.

Reading is cheap in a way asking never was, and that is what pays for the poll: `GetWindowRect` reads the window manager's own record rather than asking the owning process, `GetAsyncKeyState` reads state the input system already holds, `user32` is loaded once, and `_say_about_window` writes to the headers only when the measurement changed. A tick on a window nobody is touching is two reads and no drawing at all, which is why `WINDOW_POLL_INTERVAL` can be fast enough (`0.2`) to notice a button coming up. Anything added here must keep both halves of that — **no `SetWindowPos` per tick**, and no redraw per tick. `tests/test_window_shape.py` counts calls on a fake `user32`: a hundred ticks over a window being dragged, one maximized, one minimized, or one with room in it all have to answer zero, and a floor that cannot be reached has to answer `RESIZE_ATTEMPTS` rather than one per tick forever.

The *window's pixel rectangle* is not the terminal's cell grid, and `terminal_window.py` still never asks for a grid, and must not: a grid demanded by escape sequence is a number the app made up about a window that never changed, and from then on every mouse report names a cell nothing was drawn in. Measuring and sizing are Windows-only (`os.name`), go through `ctypes` rather than a new dependency — `pygetwindow` would be a dependency for `GetWindowRect` and `SetWindowPos`, which are four lines of `ctypes` next to the ones already here — and never run under a test pilot (`is_headless`): the only window a unit test could find is the one the developer is sitting in, and resizing that is worse than measuring it.

**Which window is the whole problem.** `GetConsoleWindow` does not name the window the user can see, and it does not fail to, either. Under Windows Terminal — and an editor's built-in terminal, and anything else hosting the console through a pseudo-console — it returns a `PseudoConsoleWindow` that reports itself **visible** and measures **0x0**, while the window on screen is Terminal's own `CASCADIA_HOSTING_WINDOW_CLASS` belonging to another process. Every check one would think to apply passes. So `CONSOLE_WINDOW_CLASS` is checked by name — only a real `ConsoleWindowClass` is this process's own window — and everything else falls through to the foreground window, which is the one the app was launched from. Read once, while the app is still in front, so alt-tabbing away can never measure somebody else's window and report it as this one. Measuring the pseudo-console is not a silent failure any more but a loud one: 0x0 is a header notice that never goes away.

`python -m unittest` cannot cover any of this — a pilot has no window at all — which is why the guard against running headless matters and why `tools/window_trace.py` exists: it prints every candidate handle with its class, its measurement and whether that reads as cramped, plus the plan — the screen it measured, the square the app would open at and the floor it would hold. Run it *in the terminal that misbehaves*, because the answer differs per host. It has no `--resize`, and must not grow one: a resize belongs to `SizeGuard` and to the two moments it is allowed.

## graphify

There is a knowledge graph at `graphify-out/` — god nodes, community structure, cross-file
relationships. It is **gitignored on purpose**: every file in it is regenerated from source
by an AST pass that costs nothing, and `graph.json` churns on every edit.

Build it on first use. This machine has no LLM API key set, so the `claude-cli` backend is
the one that works — it drives the locally installed `claude` CLI instead:

```sh
graphify extract . --backend claude-cli   # first build
graphify extract . --code-only            # structure only, no backend needed
graphify update .                         # after any code change (AST only, no cost)
```

- Codebase questions: `graphify query "<question>"` before reading source. `graphify path
  "<A>" "<B>"` for relationships, `graphify explain "<concept>"` for one concept. Each
  returns a scoped subgraph, usually much smaller than the report or raw search.
- `graphify-out/GRAPH_REPORT.md` is for broad architecture review only.
- Run `graphify update .` after any code change, so the graph is not quietly a version behind.

## Working agreement

- Prefer the smallest complete vertical slice.
- Keep each capability independently executable and testable.
- Model Flutter, React, and other stacks as versioned template packs.
- Keep template selection separate from template rendering and filesystem writes.
- Put subprocesses, filesystem access, networking, and configuration behind ports.
- Use argument arrays with `shell=False` for subprocesses.
- Preview destructive changes and require explicit confirmation.
- Never expose credentials, tokens, private payloads, or environment secrets.
- Avoid dependencies until their value clearly exceeds their maintenance cost. `textual` (the interactive TUI) is the one exception so far — keep it that way; put any new external tool behind a port instead of a fresh dependency where possible.
- Do not write comments that repeat what the code already says.
- Preserve existing behavior unless the requested change says otherwise.

## Adding a capability

1. Define any stable contract in `domain/`.
2. Implement external adapters in `infrastructure/`.
3. Add the workflow under `capabilities/`.
4. Register it in `bootstrap.py`.
5. Add line art for its key in `presentation/icons.py` and a one-line detail in `presentation/hints.py`, so its card isn't the default placeholder.
6. Add focused tests under `tests/`.
7. Run all commands in the definition of done.
8. Run `graphify update .`.

The menu grid wraps at three cards per row (`CARDS_PER_ROW`), so registering a fourth capability starts a second row rather than squeezing the first — no layout change is needed per capability. There are nine, in three rows; the menu numbers them in registration order, so a new one is **appended** rather than inserted, or every number people have learned moves.

The last three are about the toolbox rather than about projects: **App Setup** carries the whole configuration out as one JSON document and reads one back (`domain/settings_document.py`), **Check for Updates** asks a release feed whether there is a newer build (`domain/updates.py`, `infrastructure/release_feed.py`), and **Advanced** is where the feed is configured.

The app also asks for itself, once, as it starts: `application/updates.py` runs as a worker off `on_mount`, and everything about it follows from nobody having asked — it may not delay the first paint, every failure is silence (the manual card is where a failure is explained, because that is somebody asking), and it asks at most once every `CHECK_INTERVAL_HOURS` because sixty requests an hour is a budget a restart should not spend. What it finds it downloads and *writes down*, so a second launch makes no request at all; a remembered installer is trusted only if the file is still there and still newer than what is running, or the badge survives the install it was offering. Installing is `Ctrl+U` on the header badge and **never** the capability's own doing: shutting the app down cancels every run including the one asking, so the chrome owns it and the capability only records what it fetched. The installer is started by a **third** process that waits for this one to exit — `infrastructure/handover.py`, Windows PowerShell 5.1 rather than `pwsh` because this is the one place that cannot assume a developer's machine. Arming comes first and quitting follows immediately; reversed, there is nothing left to arm it (`docs/decisions/0004`, `docs/pitfalls.md` 6.1). Importing is deliberately forgiving — an unreadable field keeps the value already in place — which is only defensible because every gap it fell back on is printed; "imported" over a document half of which was skipped is the outcome that shape exists to prevent.

## Adding a template pack (stack)

1. Copy `templates/_skeleton/` to `templates/<stack>/` and rename package references.
2. Set `STACK_NAME` and implement `scaffold_new_project`, `scaffold_controller`, and `build` in `behavior.py` — this is the only file meant to change per stack. Every behavior function takes `(context, services)` and gets its ports from `PackServices`. `templates/python/` is the reference for writing a tree file by file; `templates/react_native/` is the reference for cloning one.
3. Leave `pack.py` as a thin `TemplatePack` adapter that dispatches to `behavior.py`, forwarding `generators()` and `preflight()`.
4. If the stack has a script repository, name it as `SCRIPTS` and forward `script_source`, `script_actions` and `run_script` to `templates/scripts.py` — the machinery is shared, so a pack declares the repository and nothing else about it. `templates/react_native/` is the reference.
5. Register the pack in `bootstrap.py`'s `TemplatePackRegistry`.
6. Add line art for the stack's key in `presentation/icons.py` so its card isn't the default placeholder, and a one-line detail in `presentation/hints.py` for the menu's focus hint. A workflow read off a script repository carries its own detail instead, so only add art for the keys its manifest uses.
7. Add focused tests under `tests/`.
8. Run all commands in the definition of done.
9. Run `graphify update .`.

## Definition of done

- `python -m company_tui check` passes — it runs the three below and reports a skip
  rather than omitting it. An empty test discovery is a FAIL, not a pass: this
  repository shipped with `tests/` gitignored and `discover` answering OK over nothing.
- `python -m unittest discover` passes.
- `python -m company_tui list` succeeds.
- `python -m company_tui doctor` succeeds.
- `.\script.ps1 check-all` passes. It is the same gate CI runs, and it reports a
  missing linter as SKIP rather than FAIL — an incomplete machine is not a broken
  repository — while listing every skip, because "everything passed" when three
  checks never ran is the report that gets believed and should not be.
- New decisions go in `docs/decisions/`; anything that failed silently goes in
  `docs/pitfalls.md`.
- New decisions and failure paths are tested.
- Domain boundaries remain independent of concrete tools.
- Graphify reflects the current source tree.
