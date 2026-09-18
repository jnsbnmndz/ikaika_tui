# 6. A command may be a place rather than a run, and the toolbox knows nothing about where

> **Status: ACCEPTED (2026-09-18), amended 2026-09-18** with the detail pane and the
> multi-line prompt. Protocol `domain/interactive.py`, screen
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

### A row may have a body, and it is shown exactly as it was sent

Plenty of things you browse have something worth reading in place — a record's fields, a
document's text, a change's diff, a run's log — and this view has nowhere else to put one:
there is no terminal on it and the status line is a line. `detail_body` is that place.

**Plain text**, because a pane that rendered markup would be making typographic decisions
about content whose meaning it does not know; a command wanting emphasis can spend a blank
line on it. It reaches the widget as a `rich.text.Text` rather than a markup string for the
same reason, one level down: this is somebody else's log, and a bracket in it is a bracket.

**It scrolls and it never re-wraps.** This is not a cosmetic preference. A unified diff
re-wrapped at the pane's width stops lining its `+`/`-` column up and becomes unreadable at
the exact moment somebody is relying on it; log output, fixed-width tables and stack traces
all fail the same way. So the rule is general — content appears as it was sent, and the pane
scrolls sideways — rather than a special case for any one of them.

**Display only.** Nothing in it is editable. Changing something stays an action plus a
confirmation, so there is exactly one path by which a command learns the user wants a
change, which is what keeps the confirmation rule above meaningful.

### Large bodies are asked for, and that has to terminate

A listing carrying every row's log inline is a listing that stops arriving: `MAX_PAYLOAD`
applies to these lines like any other, and staying under it is the whole point of
`"detail": "on-demand"`. DTI then writes `@dti:detail <rowId>` and the command answers with
a fresh `@dti:rows` — the ordinary verb, so a build that never heard of the request still
draws what it is sent.

The answer redraws the pane the request came from, so two things have to hold or the
exchange never ends: the redraw puts the focus back on the row it was on **by id**, and a
row already asked about is not asked again while it is still the one selected. What is
remembered is the row being looked at rather than every row ever looked at — a body can
change, and a set of ids outliving the place it came from would answer for a different
listing's "1".

The request waits for the selection to **settle** (`DETAIL_DELAY`). A held arrow key walks a
dozen rows, and a request per row is a dozen round trips for eleven bodies nobody looked at.

### One text field, and it may be a note

`"multiline": true` on `@dti:ask`. A note, a description or a review comment is not a
filename, and these screens need to take one back.

The answer stays **one line**, which is the invariant the whole protocol rests on: newlines
are written `\n`, and backslashes are doubled. Both, not just the newline — escaping one
without the other is not reversible, and `C:\new` would arrive as two lines. `@dti:ask` and
`@dti:answer` were introduced in this same change, so there is no command anywhere relying
on the unescaped form; one rule for both shapes is cheaper to hold than two.

It is submitted by Tab and then the button rather than by a chord. Tab is already what a
`TextArea` does with the focus, and every chord free enough to bind here is one some
terminal cannot send.

### Neither is a switch of its own

Both sit behind `browser_view`. They are parts of that view, not features beside it, and a
third flag would be a third thing to explain. Both are ignorable in the usual way: a command
sending `detail_body` to a build without the pane loses the pane and not the listing, and one
sending `multiline` to an older build gets a single-line box. There is no way to detect
either, because a command that can detect them is one somebody writes a branch against, and
the degraded path stops being exercised the day after.

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
- **Re-wrapping the detail pane to its width.** It is what a text pane usually does, and it
  destroys the one thing a diff, a log or a stack trace is read for.
- **Rendering `detail_body` as markup.** Then the toolbox is deciding what a `[` in somebody
  else's log means.
- **Making the pane editable.** It would be a second path by which a command learns the user
  wants a change, and the confirmation rule only means something while there is one.
- **A `detail_pane` or `multiline` setting of its own.** Three switches for one view.

## What would change this

A command wanting to show two things at once — a listing and a live progress line for work
it is doing behind it. `@dti:status` is a line and `@dti:rows` blocks, so today that is one
or the other. It would want a non-blocking listing, and that is the first thing here that
would need a verb of its own.
