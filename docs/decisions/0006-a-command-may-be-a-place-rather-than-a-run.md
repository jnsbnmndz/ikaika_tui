# 6. A command may be a place rather than a run, and the toolbox knows nothing about where

> **Status: ACCEPTED (2026-09-18).** Protocol `domain/interactive.py`, screen
> `presentation/browser_screen.py`, gate `templates/scripts.py: browses`, launch
> `presentation/tui_console.py: browse`.

## Context

The run panel answers one shape of work: configure it, run it, read what it printed. A
command that is a *place* — a remote file store, a bucket, a package registry, a database's
tables, a log archive, a branch's history — has to pretend to be that shape. The user fills
in a form for a walk they have not decided on yet, presses Run, and then navigates through
modal pick-lists stacked over a terminal they have no use for. Every one of those three
parts is wrong for the job, and the pick-lists only exist because the list protocol
(`docs/decisions/0005` and the one before it) gave them somewhere to appear at all.

## Decision

### The manifest says so, before anything is launched

`"view": "browser"` on a script entry. Read before the run starts, because what it decides
is which screen the user is looking at — a run cannot ask for a different surface halfway
through, and one that could would be a form the user filled in for nothing.

### The screen is the whole surface

Breadcrumb, tree, table, action bar, status line. No terminal and no Run button: there is
nothing to configure and nothing to stream, so they are not hidden, they are absent. Esc is
the only way out that belongs to the toolbox; every other way out belongs to the command.

A browser action is therefore launched on the answers its manifest already carries
(`script_actions.answers`), because a form is for a run you configure.

### The command owns all of it, and this toolbox knows nothing about what is being browsed

The columns are the ones `@dti:view` declared. The rows are what `@dti:rows` sent. The
action bar is exactly what the last `@dti:rows` offered and nothing else, so a command that
varies its actions by location — permissions, state, node type — gets that by saying so
each time, and nothing here has to learn why it varies. `presentation/browser_screen.py`
contains no word that is true of files and not of database tables.

Two smaller rules fall out of that. Cells are **strings and only strings**: a command
already decides that 4402816 bytes reads as "4.2 MB", and a toolbox that started formatting
numbers would be deciding it instead, for a column whose meaning it does not know. And the
table has no glyph column, because a glyph is a claim about what a row *is*.

### `danger` is styling, and the confirmation stays with the command

A dangerous action is drawn in `$error` and that is the whole of what `danger` does. What
it costs is explained by the command, in the command's own words, as an ordinary `@dti:rows`
pick-list shown as a modal over the browser — with the countdown from `timed_prompts` where
that is on. **The toolbox must never invent an "are you sure"**: only the command knows what
is about to happen, and a dialog written here would be a generic sentence standing in front
of a specific consequence.

### One key tells a pane from a question

A listing carrying `breadcrumb` is where the user is and replaces the pane; one without it
is a question and comes up over it. The key being *present* is what decides, not what is in
it, so a browser at its own root is still a pane. The command therefore asks something
mid-browse without the browse being lost, and neither shape needed a verb of its own.

### One text-input verb, used sparingly

`@dti:ask` for a value nothing can list — a name for a thing that does not exist yet.
Everything else in this view is a row or an action. `@dti:answer` with nothing after it is a
cancel, which is also what an empty answer is; the command cannot tell them apart and does
not need to.

### It is gated, and off it is an ordinary script

`browser_view` in `[experimental]`, off, beside `interactive_lists` and `timed_prompts`. Off
— or on an older toolbox, or on a plain terminal — a `"view": "browser"` command runs with a
form and a terminal: `@dti:view`, `@dti:status` and `@dti:ask` come back as ordinary output
to be read by a person, and `@dti:rows` is the pick-list it always was. A row carrying only
`cells` is labelled by its first cell so that it is still legible there.

### The command is never told which surface it got

No handshake, nothing extra in `DTI_INTERACTIVE`, no reply saying "browser". The only thing
that differs is the verb of the line coming back — `@dti:pick`, `@dti:open` or
`@dti:action` — and a command has to read that verb anyway. So a command is written once,
for both, and cannot be written to require the browser and break without it. That is the
same rule as the countdown, for the same reason.

## Alternatives rejected

- **A verb per shape** — `@dti:tree`, `@dti:table`, `@dti:bar`. Three parses, three ways to
  be half-drawn, and a listing that means something different depending on which arrived
  last.
- **Actions declared once, in `@dti:view`.** Cheaper, and wrong: the bar would then be a
  claim about everywhere, and a command with per-location permissions would have to disable
  what it had already declared — which means the toolbox holding state about why.
- **A confirmation dialog for `danger: true`.** It reads as the responsible choice and is
  the opposite: the toolbox would be writing the wording for a consequence only the command
  knows.
- **Letting a command request the browser mid-run.** Then a form was filled in for nothing,
  and the surface changes under the user.
- **Telling the command which surface it has.** Then a command can require the browser, and
  the degraded path stops being a path anything takes.

## What would change this

A command wanting to show two things at once — a listing and a live progress line for work
it is doing behind it. `@dti:status` is a line and `@dti:rows` blocks, so today that is one
or the other. It would want a non-blocking listing, and that is the first thing here that
would need a verb of its own.
