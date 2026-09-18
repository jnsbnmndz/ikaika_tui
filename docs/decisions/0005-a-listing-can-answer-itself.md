# 5. A listing can answer itself, and no command may find out whether it will

> **Status: ACCEPTED (2026-09-16).** Protocol `domain/interactive.py`, countdown
> `presentation/screens.py: PickScreen`, gate `templates/scripts.py: _list_view`.

## Context

`@dti:rows` waits forever. That is right for browsing, where the whole point is a person
choosing, and wrong for the questions a command asks on its way past: retry or give up,
overwrite or skip, keep going or stop. Those have a right answer when nobody is at the
keyboard, and the command is the only thing that knows which one it is. Without a way to
say so, an unattended run stops at the first of them and is still sitting there in the
morning.

## Decision

### Two optional fields on the payload that already exists, not a new verb

`{"rows": [...], "timeout": 20, "default": "stop"}`. Nothing else moves: the same stdin
pipe, the same `@dti:pick <id>` coming back, the same view. A new verb would have needed
its own parse, its own screen and its own return path, and three things that can disagree
about what a listing is.

### `timeout` without a valid `default` is dropped whole

Not "timeout, and the first row wins". A countdown is a command naming the answer that is
right when nobody is there; a countdown whose answer was not named — a typo in the id, a
`default` this listing does not contain, a `timeout` that is a string — has nothing to say,
and silently picking row zero is how somebody loses what they meant to keep. Both fields
travel together or neither does (`_countdown`).

The rows themselves are never harmed by it. An unreadable `timeout` costs the countdown and
nothing else, because the listing is still a perfectly good listing — which is the same
rule as everything else here, where what is not understood is ignored rather than fatal.

### Any interaction ends it, permanently

Arrow key, typing, a click, the pointer moving onto another row. Nothing re-arms it. A
choice taken away part-way through reading it is worse than never offering to answer it:
the person is looking at the list *because* they are deciding, and the timer's whole
premise — that nobody is there — is disproved by the first key.

### Expiry is an answer, never an abandonment

It dismisses with the default row's `id`, which travels back as an ordinary `@dti:pick`.
Not `None`: `None` is Esc, which the runner reads as "nothing is going to answer this" and
kills the child. A timer that ran out has answered the question.

### A second setting, and off it is taken out rather than passed along

`timed_prompts` sits beside `interactive_lists` in `[experimental]`, off. Off, the gate
wraps the view in `Untimed` and the `timeout` is gone from every listing before the screen
sees one — rather than the screen being handed a flag it has to remember to check. One
place decides, and what reaches the screen cannot disagree with it.

### A command is never told whether its countdown is live

There is no capability handshake, nothing in `DTI_INTERACTIVE`, no reply saying "timed".
A command sending `timeout` cannot find out whether anything will act on it, which means no
command can be written to depend on the timer — and that is what keeps the degraded path
honest. On an older toolbox, with the setting off, or in a plain terminal, the list renders
and waits. That has to be a path commands actually take, not one they detect and route
around.

## Alternatives rejected

- **A new verb (`@dti:ask`) for timed questions.** Two shapes of listing, two parses, two
  screens. The rows payload already carries everything a question needs.
- **Defaulting to the first row when `default` is missing.** See above; the failure is
  silent, arrives only when nobody is watching, and is indistinguishable from a person
  having chosen.
- **Pausing the countdown on interaction and resuming it.** Resuming it is the surprise
  arriving late instead of early.
- **Telling the command the timer is live.** Then a command can require one, and the
  toolbox that cannot run one stops working rather than degrading.
- **Reusing `interactive_lists` for both.** A countdown is the part that acts without
  being asked. Somebody who wants lists but not a clock has to be able to say so.

## What would change this

A command needing to *cancel* or *extend* a countdown it has already sent — a long upload
that wants to keep a "stop?" question alive while it makes progress. That is a second
listing today, which redraws. It would want a verb of its own, and that verb would be the
first thing here a command could detect.
