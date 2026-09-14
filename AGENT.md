# Agent Guide

**[CLAUDE.md](CLAUDE.md) is the rules** — one copy, for agents and people alike. Read it
before changing anything. What follows is only the handful most easily broken by writing
code before reading it.

## Comments live at the top of a file and nowhere else

One module docstring saying what the file is for, in a line or two. Classes and functions
get a single line; constants get a single line or none. **No inline `#` commentary** — the
only exceptions are tool directives (`# noqa`, `# type:`), which are instructions rather
than prose.

```python
"""Starts an installer that runs after this process exits."""

class WindowsHandover(HandoverPort):
    """`HandoverPort` over a detached PowerShell waiter written at runtime."""

    def hand_over(self, installer: Path) -> str:
        if os.name != "nt":
            return NOT_WINDOWS
```

## The reasoning goes in `docs/`, not beside the code

- `docs/decisions/` — why a thing is built the way it is.
- `docs/pitfalls.md` — what went wrong, and the rule that followed.

Write it there, where one copy serves the whole repository, and cite it by number
(`docs/pitfalls.md 6.4`) where a line needs it. A finding that only exists as a comment is
one the next sweep deletes.

## Behaviour and its description change together

The docs that describe it **and the text on screen**. A card's description, an option's
`help`, a dialog's wording and a focus hint are the documentation users actually read, and
they go stale the same way a comment does — a control that describes what it no longer does
is the same defect, only visible to everyone.

## Before you call it done

`.\script.ps1 check-all` and `python -m company_tui check`, then `graphify update .`. The
full list is in CLAUDE.md.

---

This file is a pointer on purpose. It used to restate CLAUDE.md in full and drifted out of
date — two copies of one set of rules is one copy nobody maintains. The four above are
repeated deliberately, because they govern the first thing anyone writes.
