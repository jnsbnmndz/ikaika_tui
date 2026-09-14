# 2. The version is one file, and the gate is one command

> **Status: ACCEPTED (2026-09-05).** `VERSION` at the repository root, read by `presentation/branding.py`. Gate at `company_tui/check.py`.

## Context

The version was a literal in `branding.py` *and* a number in `CLAUDE.md` — two copies of one
fact, and the one on screen is the one that goes stale. Separately, the definition of done
listed three commands to run by hand; nothing ran them together, and one had been passing
over an empty test directory for as long as `tests/` was gitignored.

## Decision

**`VERSION` holds `x.y.z+n` and everything derives from it.** A release rewrites that file
and nothing else. `branding.py` reads it and **falls back rather than raising** — an app
that refuses to start because it cannot find a text file is worse than a vague title bar,
and an installed wheel has no repository around it. The build number rises **globally**
across version names, because that is the rule the installer depends on.

`domain/identity.DEFAULT_VERSION` is deliberately not this: it is the version stamped into
a project the toolbox *creates*.

**`python -m company_tui check` is the gate**, running the tests, `list` and `doctor` as
subprocesses of `sys.executable`. Two rules:

- **A skip is reported, never omitted.** A run must never look like it verified something
  it did not.
- **A check that stops checking is a failure.** An empty discovery is FAIL — precisely how
  this repository shipped with no tests while citing two test files by name.

## Consequences

- `CLAUDE.md` states no version number; it points at `VERSION`.
- The pre-push hook is opt-in, because installing one in somebody's checkout is a surprise.

## Alternatives rejected

- **Read from package metadata.** Correct for a wheel, wrong in a checkout — it reports
  whatever was last installed, not what the source says now.
- **Keep the literal and test that it matches.** A test that two copies agree is a way of
  keeping two copies.
