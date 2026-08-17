# TODO

Planned work, with a feasibility call on each.

---

## 1. Session management — multiple runs, like terminal tabs — **done**

All five phases landed. The shape held: the hard part was never the UI, it was
that one workflow owned one screen and one console. It no longer does.

### What it does now

A tab strip above the terminal pane. `⌃T` adds a run, `⌃W` closes one, `F2`
renames one, `⌃PgUp`/`⌃PgDn`, the wheel and the mouse switch between them. Esc
leaves a run going and hands back the menu it was started from, one step back
rather than out to the front; Stop moved to the button. The
chrome carries a count of what is still going, and `Ctrl+B` goes back into it
from anywhere. Every line a run printed is still there when you return,
including after an accidental Esc.

### How it came out

- **`RunSession`** (`presentation/session.py`) owns the form, the values, the
  log, the task and the pending question. `SessionRegistry` holds them all in
  one place, tagged with `session.steps` — the context the run was started from.
- **`RunScreen` is a view.** It renders whichever session is selected, rebuilds
  the config pane on a tab switch, and replays that session's log on attach. All
  of `_terminal_history`, `_trail`, `_result_acknowledged` and the `_answer`
  future moved onto the session.
- **`CURRENT_SESSION`, a `ContextVar`,** decides where a line goes. This was the
  load-bearing decision and it paid off exactly as expected: not one capability
  or pack changed to make routing work.
- **A worker per run.** `Application.run()` hands each capability to
  `Ui.start_run` as a callable; the console runs it as a Textual worker — a
  worker rather than a bare task, so a run started from a keypress can still
  push a screen of its own. `start_run` returns when the run lets go of the
  screen, which is what frees the menu without ending anything.
- **The strip filters, the registry does not.** A live run from another context
  stays visible, dimmed, at the end of the strip.
- **`session.preset`** makes "+" mean "another one of these": a sibling repeats
  the parent's menu answers instead of making the user walk them again.

### The risks, as they actually landed

- **Log buffers** are a `deque(maxlen=LOG_LIMIT)` from the start, as planned.
- **Quit with runs in flight** confirms first, then unwinds every worker — both
  from `Ctrl+Q` and from backing out of the main menu.
- **Two runs, one directory** is refused by `domain/destinations.py`, claimed
  before the work is handed over rather than after. Refused rather than queued:
  a second run silently waiting looks exactly like one that has hung.

### One thing worth knowing

`_stop_run` deliberately does not go through `request_stop`. Stop is the user
saying "stop this run", and the workflow is meant to survive it and report the
stop; closing a tab or quitting takes the workflow itself away, so the
cancellation has to travel all the way out. Conflating the two makes a closed
tab's workflow carry on and hang on its own acknowledgement.

### Not done, on purpose

**Persisting sessions across app restarts.** A killed subprocess cannot be
resumed, so restoring the logs of a dead run would show a completed scaffold
that never happened. Sessions stay in memory for the life of the app.

---

## 2. A strip per context, not one strip — **done**

Every run in a workflow used to share one strip, so walking from React Native to
Flutter and back landed in the same tab, one run deep, with both stacks' prompts
in the same terminal:

```text
$ Scaffold › New Project › React Native
$ Scaffold › New Project › Flutter
```

Now it is one terminal *per* context. React Native's tabs are React Native's,
Flutter's are Flutter's, and each of Scaffold › Components, Build › React Native
and the rest has its own set starting at Tab 1. Go into React Native, start a
run, back out to Flutter, and Flutter opens on its own empty Tab 1 — with React
Native's run still going in React Native's strip when you return to it.

### The one decision it turned on

`session.scope` was a live property over `session.steps`, and `_record` rewrites
`steps` on every menu answer. So walking to another stack did not move you to a
different session — it **re-homed the session you were already in**. The tab
followed the user. That was the whole bug, and the fix is the opposite of what
the plan first suggested: `scope` is now a snapshot taken at creation, `place` is
what `steps` currently says, and they differ exactly when the workflow has walked
somewhere the tab does not belong.

`TuiConsole._relocate` acts on that difference at `open_run_panel` — the first
moment the context is fully known, since a menu deeper than the last one answered
has not been asked yet. The workflow carries on in a session belonging to the new
context, taking its worker with it; the tab behind is dropped, because nothing
ever ran in it and a tab nobody can reach from the strip they walked to is
litter. `_here()` is why `_retire` and `report_failure` still find the right
session afterwards: the workflow may not end in the session it started in.

### What followed from it

- **`visible(scope)` is a real filter.** It used to return `mine + theirs` so a
  live run could not vanish behind a menu. With separate strips that tail is
  self-defeating — Flutter's strip would show React Native's tab, which is the
  thing being removed — so it went, and `running_under` took over the job.
- **Numbering is per context** (`_unique(base, scope)`), so Flutter's first run
  is `Scaffold`, not `Scaffold 3`.
- **`SessionTab`'s `-foreign` state is gone**, along with the `scope != active`
  term in the strip's rebuild signature. Nothing foreign reaches the strip.
- **`_resumable` only considers sessions with `panel_open`.** A workflow
  part-way through its menus owns a session with no form on it, and `Ctrl+B`
  landing on one put up a run panel with an empty configuration pane. That was a
  latent bug; making the menus create more such sessions brought it out.
- **The prompt needed nothing.** A fresh context means a fresh session with an
  empty log, so `_open_prompt` writes one without the trail-comparison branch
  ever firing.

### The indicator

`SessionRegistry.running_under(place)` counts live runs by **prefix**, so the
card for a stack counts that stack's runs and the card for `Scaffold` counts all
of them. `MenuEntry.running` carries it into `Card`, which shows `N running`
under the name; `CardMenuScreen.show_counts` keeps it current from
`_refresh_badges`, so a card stops offering a way back into a run that has
finished. The row is `visibility: hidden` rather than absent when there is
nothing to say, so a card with a run behind it is not a different shape from the
one beside it.

### A second pass: a session is not a tab

Reported again as "going back to React Native creates a new tab". It does not,
and that was checked properly this time rather than reasoned about: eight
hand-built sequences (running, finished-while-away, back via the stack menu, the
target menu and the top menu, and a detour through Flutter) plus eighty random
walks of twenty-two steps through the real object graph. Every one of them
reused the tab. Nothing left in the navigation can produce a second one — only
`⌃T` and the strip's `+` can.

What the pass did turn up was the thing that *looks* like it. Every workflow
owns a session from `start_run`, before it knows which context it is for — it
carries the breadcrumb and the answers while the user walks menus. Those were
being counted as tabs:

- **the chrome reported them.** Leaving a run going said `1 running · 1 waiting`
  when there was one run and one menu. The waiting one was the menu.
- **a strip could show one.** A workflow that walked into a stack, opened
  nothing and walked on left a session homed there, which appeared in that
  strip as a tab nothing had ever been in.
- **`_relocate` could attach one**, putting up a run panel with an empty
  configuration pane — the same latent bug `_resumable` already guards against.

`session.opened`, set by `load`, is the line: `visible` and `summary` count
tabs, and `_relocate` only ever attaches one with a form actually on it.
`_unique` deliberately still numbers against every session in the scope, so two
workflows arriving at once cannot both be called `Scaffold`.

The other half was the strip's own feedback. `SessionTab:hover .tab--label`
never matched — Textual puts `:hover` on the innermost widget, so the rule asked
about a state the tab itself never has — which meant nothing lit up under the
pointer, two columns from a `+` that starts a run. The `HoverLight` mixin from
`KeyHint` now covers both, and the `+` sits further out.

---

## 3. Smaller open items (DON'T TOUCH IT FOR NOW)

- **Generator folders are guesses.** `app/screens`, `components`, `services`,
  `hooks` for React Native, and `tests` for Python. They are editable in the
  form, but they should default to the real layout of the structure repo.
  Confirm and correct.
- **Flutter and React packs are stubs.** Both return `available=False`. Once
  there is a structure repo for each, they become a `TemplateSource` plus an
  `IdentityRewrite` for the file that carries the project's name — `pubspec.yaml`
  for Flutter, `package.json` for React — and follow `templates/react_native/`.
- **`build` only reports the Python version.** It does not build anything.
- **`deploy` and `scripts` are placeholders.** Neither does anything yet.
- **Doctor never fails.** It reports a missing tool and still exits 0, so it
  cannot gate anything in CI. Deliberate for now; revisit if that changes.
- **Other noisy commands want `QuietRun`.** `npm install` goes through it now.
  Gradle, `flutter pub get`, `pod install` and `pip install` are the same shape
  and should use it when those packs land. `git clone` deliberately does not —
  its output is short, and its progress percentages are the reassurance that
  something is happening.
