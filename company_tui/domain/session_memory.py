"""What a tab is worth keeping after the app is closed, and who keeps it.

A run cannot be resumed — a killed subprocess is gone, and no amount of stored
state brings it back. What can be kept is everything the *user* put in: which
stack the tab belongs to, what they renamed it to, what they typed in the form,
and what the last run printed. Coming back to a project should not mean walking
the same three menus, retyping the same destination and renaming the same tab.

So this is deliberately a record of answers, not of work. `RememberedSession`
carries no task, no process, no lifecycle flags and no "it was running" — a tab
restored from one is idle, with its history above the prompt and its form ready
to send again.

The port is here rather than in `presentation` because `infrastructure` may
depend on the domain and not the other way round; the dataclass is plain data
for the same reason. What a session *is* stays in `presentation/session.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from company_tui.domain.options import OptionValue


@dataclass(frozen=True)
class RememberedSession:
    """One tab, as it deserves to come back.

    `scope` is where the tab belongs and is carried in its own right, **not**
    derived from `steps`. The two differ exactly when a workflow walked back to
    re-ask a step: `_enter_step` trims `steps` so the breadcrumb corrects itself,
    while the scope it was created under stays put. Deriving one from the other
    is how a React Native tab came back belonging to `("Scaffold",)` and turned
    up in no strip at all.

    `log` is pairs of message and marker rather than rendered lines, because a
    rendered line carries the colours of the theme it was assembled under.
    """

    name: str
    base: str
    scope: tuple[str, ...] = ()
    steps: dict[str, str] = field(default_factory=dict)
    title: str = ""
    trail: tuple[str, ...] = ()
    values: dict[str, OptionValue] = field(default_factory=dict)
    log: tuple[tuple[str, str], ...] = ()
    stamp: str = ""


class SessionMemory(Protocol):
    """Where tabs are kept between one run of the app and the next.

    Keyed by workspace: one machine holds several projects, and the tabs of one
    are not the tabs of another. Both sides are total — a store that cannot be
    read is an empty one, and a store that cannot be written is a lost
    convenience rather than a lost run, so neither may raise into a workflow.
    """

    def remembered(self, workspace: str) -> tuple[RememberedSession, ...]:
        ...

    def remember(self, workspace: str, sessions: Sequence[RememberedSession]) -> None:
        ...
