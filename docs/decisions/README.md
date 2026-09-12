# Decision records

One record per architectural decision, numbered and **append-only**. A reversed decision is
superseded by a new record, never edited in place.

`CLAUDE.md` and `AGENT.md` hold the *rules*; these hold *why each rule exists*, what it
cost, and what would justify changing it. Read the record before arguing with a rule - most
of the obvious objections are already in an "Alternatives rejected" section.

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-a-project-declares-its-own-commands.md) | A project declares its own commands, and the toolbox reads them | ACCEPTED | 2026-09-05 |
| [0002](0002-the-version-is-one-file.md) | The version is one file, and the gate is one command | ACCEPTED | 2026-09-05 |
| [0003](0003-a-share-link-is-a-secret.md) | A share link is a secret, and the checksum is what gets committed | ACCEPTED | 2026-09-08 |
| [0004](0004-the-toolbox-can-install-its-own-update.md) | The toolbox can install its own update, through a process that outlives it | ACCEPTED | 2026-09-08 |

## Working with these

- Changing behaviour a record describes: update it in the same change, or write the
  superseding one. A record still arguing for the old behaviour is worse than no record.
- `docs/pitfalls.md` is the other half - the failures rather than the decisions. A rule with
  the wreck behind it is easier to keep than a rule on its own.

## Not yet recorded

- **The session model** - one `RunSession` per run, a strip per context, `CURRENT_SESSION`
  as a `ContextVar`, and why `scope` is a snapshot while `place` is live. Currently written
  up in `TODO.md` as completed work, which is the wrong place for it: that file is a plan,
  and this is the reasoning somebody would otherwise undo.
- **Why the interface bans emoji**, and why the ban is by Unicode block with a named
  allowlist rather than by width. Enforced by `tests/test_glyphs.py` and explained in
  `docs/pitfalls.md` 3.3.
- **The window-shape poll** - reading `GetWindowRect` on a timer rather than asking the
  owning process, and the two things that must stay true of it (no `SetWindowPos` per tick,
  no redraw per tick).
