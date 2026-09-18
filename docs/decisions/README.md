# Decision records

One record per architectural decision, numbered and **append-only**. A reversed decision is
superseded by a new record, never edited in place; a correction to a live one is marked
*amended* with its date.

`CLAUDE.md` holds the *rules*; these hold *why each rule exists* and what would justify
changing it. Read the record before arguing with a rule — most of the obvious objections
are already under "Alternatives rejected".

| # | Decision | Status |
|---|---|---|
| [0001](0001-a-project-declares-its-own-commands.md) | A project declares its own commands, and the toolbox reads them | ACCEPTED |
| [0002](0002-the-version-is-one-file.md) | The version is one file, and the gate is one command | ACCEPTED |
| [0003](0003-a-share-link-is-a-secret.md) | A share link is a secret, and the checksum is what gets committed | ACCEPTED |
| [0004](0004-the-toolbox-can-install-its-own-update.md) | The toolbox can install its own update, through a process that outlives it | ACCEPTED, amended |
| [0005](0005-a-listing-can-answer-itself.md) | A listing can answer itself, and no command may find out whether it will | ACCEPTED |
| [0006](0006-a-command-may-be-a-place-rather-than-a-run.md) | A command may be a place rather than a run, and the toolbox knows nothing about where | ACCEPTED, amended |
| [0007](0007-the-interface-is-arranged-in-a-browser.md) | The interface is arranged in a browser, over the part of it that is arrangement | ACCEPTED |

Changing behaviour a record describes means updating it in the same change, or writing the
superseding one. A record still arguing for the old behaviour is worse than no record.

`docs/pitfalls.md` is the other half — the failures rather than the decisions.

## Not yet recorded

- **The session model** — one `RunSession` per run, a strip per context, `CURRENT_SESSION`
  as a `ContextVar`, and why `scope` is a snapshot while `place` is live.
- **Why the interface bans emoji**, by Unicode block with a named allowlist rather than by
  width. Enforced by `tests/test_glyphs.py`, explained in `docs/pitfalls.md` 3.3.
- **The window-shape poll** — reading `GetWindowRect` on a timer rather than asking the
  owning process, and the two things that must stay true: no `SetWindowPos` per tick, no
  redraw per tick.
