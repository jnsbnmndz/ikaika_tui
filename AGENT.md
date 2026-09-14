# Agent Guide

**[CLAUDE.md](CLAUDE.md) is the rules** — one copy, for agents and people alike. Read it
before changing anything. What follows is only the handful most easily broken by writing
code before reading it.

## Comments live at the top of a file and nowhere else

**In every language here**, not just Python.

| | The header is | Below it |
|---|---|---|
| `.py` | a module docstring, a line or two | one line on classes and functions, one line or none on constants |
| `.ps1` `.yml` `.toml` | a leading `#` block | nothing |
| `.nsi` | a leading `;` block | nothing |

A header is a summary and the switches, plus the one or two rules that must not be broken,
each citing where the reasoning lives. Not an essay.

```python
"""Starts an installer that runs after this process exits."""

class WindowsHandover(HandoverPort):
    """`HandoverPort` over a detached PowerShell waiter written at runtime."""

    def hand_over(self, installer: Path) -> str:
        if os.name != "nt":
            return NOT_WINDOWS
```

**Three exceptions.** Tool directives (`# noqa`, `# type:`) are instructions, not prose.
Another language embedded in a file — the PowerShell inside `handover.py`'s `SCRIPT`, and
`run:` blocks in a workflow — is that script's own documentation, not this file's. And
third-party generated config (`.serena/`) is not ours to sweep.

**Sweep with the language's own parser, never a regex.** Only a parser tells a `#` that
starts a comment from one inside a here-string, and only a block-scalar-aware pass knows
that a `#` in a `run:` block is somebody's shell script. Re-parse after; refuse the file if
it no longer parses.

## The reasoning goes in `docs/`, not beside the code

- `docs/decisions/` — why a thing is built the way it is.
- `docs/pitfalls.md` — what went wrong, and the rule that followed.

Cite it by number (`docs/pitfalls.md 6.4`) where a line needs it. A finding that only
exists as a comment is one the next sweep deletes — **so a sweep moves it first**. Read
what a file's comments claim before stripping it, and check each finding has a home.

## Behaviour and its description change together

The docs that describe it **and the text on screen**. A card's description, an option's
`help`, a dialog's wording and a focus hint are the documentation users actually read, and
they go stale the same way a comment does — a control that describes what it no longer does
is the same defect, only visible to everyone.

## Before you call it done

`.\script.ps1 check-all` and `python -m company_tui check`, then `graphify update .`. Use
`-Build` before a release: it is the only check that freezes, and it starts the frozen exe,
because a freeze that succeeds is not a build that runs. The full list is in CLAUDE.md.

---

This file is a pointer on purpose. It used to restate CLAUDE.md in full and drifted out of
date — two copies of one set of rules is one copy nobody maintains. The four above are
repeated deliberately, because they govern the first thing anyone writes.
