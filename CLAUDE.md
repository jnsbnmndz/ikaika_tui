# CLAUDE.md

Guidance for working in this repository.

This is the IKAIKA developer toolbox (v0.0.0+1) — a Python company developer toolbox for repeatable scaffolding and automation. It must remain usable for Flutter, React, and future stacks without coupling the core application to a specific framework.

The interactive UI is branded: `presentation/branding.py` defines `IKAIKA_THEME` (colors drawn from the company logo) plus the name/tagline/version, registered and activated by `TuiConsole` on mount. New CSS should reference theme tokens (`$primary`, `$accent`, `$surface`, `$panel`, `$text-muted`, ...) rather than hardcoded colors, so it stays on-brand and adapts if the theme changes.

Every screen sits inside the same chrome from `presentation/chrome.py`: an `AppFrame` border, an `AppHeader` (logo mark, name, tagline, version, workspace status, and a count of runs still going) and an `AppFooter` (key hints on the left, signature on the right). Compose new screens inside `AppFrame` so the app reads as one surface. Menus are responsive — `CardMenuScreen` lays its cards out in a grid at most `CARDS_PER_ROW` wide and swaps full tiles for single-row entries when there isn't room for them, and the accent color is reserved for whatever currently has focus.

Every key hint is also a button. A `KeyHint` reads its own label back into the key it names (`key_for`) and clicking it presses that key, so the mouse reaches everywhere the keyboard does without a second set of controls to keep in step with the first — and so a hint cannot drift from what it does. A hint naming a range rather than a key stays inert instead of lighting up for a press it could never send, and so does one whose key is dead at the time. Add a hint by putting it in a footer's tuples; do not wire a handler to it.

Nothing the interface draws may be an emoji, and `tests/test_glyphs.py` checks rather than trusts. A codepoint with Unicode `Emoji=Yes` is rendered from an emoji font instead of a text one: double width, so every column after it is wrong, in a colour that ignores the theme and at a weight nothing like the box-drawing art beside it. This is easy to get wrong because these codepoints read fine in an editor — a stop mark on the Run button and a stopwatch on each run's timestamp both got in that way. Draw from the geometric shapes, dingbat and box-drawing blocks (`◆ ✓ ▲ ✗ ● ○ ✕ ❯ ▸ ■`); if nothing legible is available, use no glyph and let colour do the work.

Anything clickable made of more than one widget mixes in `HoverLight` (`presentation/chrome.py`) rather than writing a `:hover` rule. Textual puts `:hover` on the *innermost* widget under the pointer, so `Parent:hover .child` asks about a state its ancestor never has and silently never matches — which is why a hint could only light the half being pointed at and why a tab lit nothing at all. The mixin gives the parent a `-hovered` class off `Enter`/`Leave`; hang the rule on that.

## Commands

```sh
python -m company_tui        # interactive Textual UI
python -m company_tui list   # plain stdout, scriptable
python -m company_tui doctor # plain stdout, scriptable
python -m unittest discover
```

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

Several runs happen at once, and the panel shows one of them. A `RunSession` (`presentation/session.py`) owns everything one run has — its form, its values, its log, its task, whatever it is waiting on — and `RunScreen` renders whichever session is selected, replaying that session's log when it attaches. The strip above the terminal gets the whole width: it scrolls to the wheel as well as to the keyboard, keeps the active tab in view, and gives each tab a close mark. The keys that act on it live at the foot of the pane, under the stdin row — anything sharing the strip's row is width the tabs do not get, and the tabs are the only thing there with no fixed size. Esc leaves a run going and hands back the menu it was started from, one step back rather than out to the top; Stop is on the button. Nothing is persisted: a killed subprocess cannot be resumed, so restoring the log of a dead run would show a scaffold that never finished as if it had.

Esc on a running panel backgrounds the run and puts back the menu that started it (`_resume_behind`), by opening a sibling session whose `preset` repeats every step except the last — so the run keeps going in its own tab and the user is one step back, not out at the front door. That sibling has to be spawned *before* the old run is backgrounded: freeing the foreground with nothing else holding it releases the menu loop, and the top menu it puts up would land underneath. A panel with no menu behind it (`len(steps) < 2`) has no step to go back to, and there Esc is only ever leaving.

Taking the panel off the screen and backgrounding a run are separate acts, and only the second one frees the menu loop. A run whose panel closed because the user backed out of its form is still mid-workflow and about to show a menu of its own; freeing the loop there pushes a second menu over the top of it.

That same session then serves the rest of the workflow, so what a form was answered with belongs to the attempt rather than to the session and `load` re-arms it. A session that carried "backed out" forward would answer the next form before it was on screen, and the menu the user came back to would send them straight back to itself. Its log follows the same line: a `$` prompt marks a run, so walking in and out of a form reuses the prompt already there rather than stacking up a transcript of runs that never happened.

Which log a line lands in is decided by `CURRENT_SESSION`, a `ContextVar` set when a session's task starts. Async tasks inherit the context they were created in, so every `write`/`ask`/`confirm` inside a workflow — and every subprocess callback under it — resolves to that workflow's own session without a single capability knowing sessions exist. **Never route output by "the panel that is open"**; that is the model this replaced, and it is wrong the moment there is more than one run.

`Application.run()` hands each capability to `Ui.start_run` as a callable rather than awaiting it. The console runs it as its own Textual worker (a worker, not a bare task, so a run started from a keypress can still push a screen), and `start_run` returns when that run lets go of the screen — which is not when it finishes. Keeping the workflow as a callable is also what makes the strip's "+" one more call: a second tab in the same context repeats the first one's menu answers from `session.preset` instead of asking again.

Every context gets its own strip. A session's `scope` is the breadcrumb it was made under (`{capability, scaffold_target, template_pack}`), **settled once, at creation** — deliberately a snapshot and not a reading of `steps`, which keeps changing as the workflow walks. A tab that re-homed itself on every choice would follow the user out of the context it is holding a directory and a log for, which is how one terminal came to carry two stacks' runs. A workflow that walks somewhere else gets a session *there* instead: `_relocate` moves it at `open_run_panel`, which is the first moment the context is fully known, and drops the tab behind it because nothing ever ran in it. `session.place` is where the workflow has got to; `session.scope` is where the tab belongs, and they differ exactly when a move is due.

A tab outlives the workflow that made it. `_retire` frees a session (`task = None`) rather than removing it once anything has been run there (`session.ran`), so walking back into a stack picks that tab up — its output, the time it ran and the form it was sent all still in it, and `load` keeps the answers rather than blanking them. Only a tab nothing was ever run in is dropped. Walking into a stack whose tabs are all mid-run attaches the run instead of opening a form beside it: there is nothing to fill in, and the workflow that walked in waits for the screen, which it gets back as the menu it came from. That is also why `_resume_behind` checks whether anything else is already holding the foreground — two workflows putting up the same menu is two menus.

Not every session is a tab. Every workflow owns one from the moment it starts, long before it knows which context it is for — it is what carries the breadcrumb and the answers while the user is still walking menus — so `session.opened`, set by `load`, is what makes one a tab. `visible` and `summary` count tabs; counting sessions is how a strip grew an entry nothing had ever been in and the chrome reported a run waiting that was really a menu. For the same reason `_relocate` only ever attaches a tab with a form actually on it: one whose own workflow has walked off to a menu has nothing to show, and attaching it put up a run panel with an empty configuration pane.

They still live in one `SessionRegistry` — a session that existed only inside its own context would be reachable only by walking the menus back to it from memory. `visible(scope)` is a real filter, so a run from elsewhere is not in this strip at all; what stops it being forgotten is `running_under(place)`, which counts by *prefix* so each menu card says how many runs are going behind it, plus the running total in the chrome and `Ctrl+B` — which opens `RunsScreen`, the one view that can list every run there is, each saying where it lives. Tabs are numbered per context too, so every stack opens on its own first tab. Work you cannot see is work you forget about — but a tail of runs from everywhere else puts back exactly what a strip per context removes.

Two things follow from runs happening side by side. Log buffers are capped (`LOG_LIMIT`) — `npm install` alone emits tens of thousands of lines, and N sessions holding all of them is a leak with a progress bar on it. And a destination can only be written by one run at a time (`domain/destinations.py`), claimed by `ScaffoldCapability` before the work is handed over: two runs aimed at the same directory is not a race either can win, since one removes the tree the other is halfway through cloning into.

## Scaffolding

Every project the toolbox produces carries `ikaika.script.json` — `version`, `name`, `description`, `title` — whether it was cloned or written file by file. It is what makes a directory an IKAIKA project: `ProjectFinalizer.require_project` refuses to finish a scaffold without one, and the generators refuse to run outside one. Only those four keys belong to the toolbox; a template's other keys are read and written back untouched, in order and at the template's own indent (`domain/json_document.py`).

A pack decides only how the tree appears. What happens next is `ProjectFinalizer` (`domain/scaffolding.py`), the same for every stack: stamp the identity, seed `.env` from `.env.example`, drop the template's `.git` and start a repository with a first commit. Files besides the manifest that also carry the project's name are stack-specific and declared as `IdentityRewrite`s — for React Native that is Expo's `app.json` (`templates/react_native/expo.py`), which spells the name four ways and inherits the template's EAS project id unless it is dropped.

A name is parsed once, in `context_from`, into a `ProjectName` (`domain/project_name.py`) that hands each stack its own spelling — `slug`, `snake`, `compact`, `pascal`, `camel`, `title`. Parsing is also the guard: `.`, `..`, and absolute paths are refused before a pack turns the name into a directory it will delete and recreate. Use `ProjectName.existing` to read a name back out of a manifest, where validation does not apply.

Where a stack clones from, which ref of it is current, the organisation's bundle prefix and the workspace root come from `ConfigPort` (`ikaika.toml`), not from constants — pinning a template should be a settings edit. The Settings capability is that edit: the same run panel, writing either the project file or the user one, and `FileConfig` forgets what it read on save so the change applies without a restart. Packs declare the executables they need as `ToolRequirement`s so a run fails fast with a sentence and Doctor can report the same facts.

## Transitions

Every step of a workflow pops one screen before pushing the next, so the app's own screen shows in between. It carries the same chrome, and its activity log stays hidden (`-quiet`) until something is written to it, so the gap reads as the same surface rather than as somewhere else. A workflow that sends the user back therefore passes a `notice` to the menu they land on instead of writing to the console, which would put the message behind whatever comes next. What a workflow without a panel does write there is read at the pause that follows it, and the log is emptied and hidden again when the menu loop comes back round — a line left standing shows through every later gap as if the workflow now running had said it.

Esc is how the user walks back through all of this, so the last one cannot also be how they leave: backing out of the top menu asks first (`_confirm_quit(deliberate=False)`). The quit chords `Ctrl+Q` and `Ctrl+C` are aimed rather than walked into and go straight out — unless a run is live, which always asks, because that is N directories abandoned rather than none.

Entrances are for taking the edge off a repaint, not for being watched: the grid is sized first and then the whole menu body — trail, notice, title, subtitle and cards — comes in as one, over `CARD_ENTRANCE_DURATION`. Staggering the cards read as the menu loading, and every step of every workflow paid for it. Staggering the body against the chrome was worse: density can only be measured once there is a layout to measure, so a menu that reveals its title first is legible for a tenth of a second before it has any cards, and half-built at a glance is not this menu loading but a different menu — which made every step of every workflow look like it went somewhere else on the way. What shows in the meantime is the same chrome the gap between screens already shows, so the two are one pause rather than two.

Threads are not the lever here — Textual is single-threaded and the interface is idle during a transition. What does block it is a synchronous subprocess, so anything run while a screen is up goes through `ProcessRunner.capture` rather than `run`.

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

The menu grid wraps at three cards per row (`CARDS_PER_ROW`), so registering a fourth capability starts a second row rather than squeezing the first — no layout change is needed per capability.

## Adding a template pack (stack)

1. Copy `templates/_skeleton/` to `templates/<stack>/` and rename package references.
2. Set `STACK_NAME` and implement `scaffold_new_project`, `scaffold_controller`, and `build` in `behavior.py` — this is the only file meant to change per stack. Every behavior function takes `(context, services)` and gets its ports from `PackServices`. `templates/python/` is the reference for writing a tree file by file; `templates/react_native/` is the reference for cloning one.
3. Leave `pack.py` as a thin `TemplatePack` adapter that dispatches to `behavior.py`, forwarding `generators()` and `preflight()`.
4. Register the pack in `bootstrap.py`'s `TemplatePackRegistry`.
5. Add line art for the stack's key in `presentation/icons.py` so its card isn't the default placeholder, and a one-line detail in `presentation/hints.py` for the menu's focus hint.
6. Add focused tests under `tests/`.
7. Run all commands in the definition of done.
8. Run `graphify update .`.

## Definition of done

- `python -m unittest discover` passes.
- `python -m company_tui list` succeeds.
- `python -m company_tui doctor` succeeds.
- New decisions and failure paths are tested.
- Domain boundaries remain independent of concrete tools.
- Graphify reflects the current source tree.
