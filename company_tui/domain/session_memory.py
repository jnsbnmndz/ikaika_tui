"""What a tab is worth keeping after the app is closed, and who keeps it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from company_tui.domain.options import OptionValue


@dataclass(frozen=True)
class RememberedSession:
    """One tab, as it deserves to come back."""

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
    """Where tabs are kept between one run of the app and the next."""

    def remembered(self, workspace: str) -> tuple[RememberedSession, ...]:
        ...

    def remember(self, workspace: str, sessions: Sequence[RememberedSession]) -> None:
        ...
