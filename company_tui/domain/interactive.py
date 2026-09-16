"""The list protocol: `@dti:` lines a command may speak, and the pick sent back."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from company_tui.domain import naming

INTERACTIVE_VAR = f"{naming.APP_NAME}_INTERACTIVE"
"""Set in the child's environment, and the whole of how a command knows to speak."""

ENABLED = "1"

PREFIX = f"@{naming.APP_SLUG}:"
ROWS = f"{PREFIX}rows"
END = f"{PREFIX}end"
PICK = f"{PREFIX}pick"

MAX_PAYLOAD = 512 * 1024
"""A listing is a menu. Anything past this is a command streaming into the wrong door."""


@dataclass(frozen=True, slots=True)
class Row:
    """One choice. `id` is opaque here and echoed back exactly as it arrived."""

    id: str
    label: str
    kind: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Listing:
    """Rows to show, what to say above them, and an optional countdown."""

    rows: tuple[Row, ...] = ()
    title: str = ""
    hint: str = ""

    timeout: int = 0
    """Seconds before `default` wins. Zero - and absent, and unreadable - waits."""

    default: str = ""
    """The row that wins on expiry, always one of `rows`. Set only with a `timeout`."""

    @property
    def counts_down(self) -> bool:
        """Whether this listing answers itself. Both fields, or it waits."""
        return self.timeout > 0 and bool(self.default)

    def untimed(self) -> "Listing":
        """The same listing with the countdown taken out."""
        return replace(self, timeout=0, default="")


@dataclass(frozen=True, slots=True)
class Finished:
    """`@dti:end`: done with the list, back to plain streaming."""


def pick(identifier: str) -> str:
    """The line written back on stdin when a row is chosen."""
    return f"{PICK} {identifier}"


def parse(line: str) -> Listing | Finished | None:
    """A listing, an end, or `None` for a line that is ordinary output.

    `None` covers everything this build does not understand, which is deliberate:
    an unknown verb, malformed JSON and a row missing its `id` all fall through to
    being printed as text rather than raising. A command written for a later
    version must not be able to break an older toolbox, and a half-read line must
    not be able to empty the screen.
    """
    if not line.startswith(PREFIX):
        return None
    if line.strip() == END:
        return Finished()

    head, _, payload = line.partition(" ")
    if head != ROWS or len(payload) > MAX_PAYLOAD:
        return None
    try:
        document = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    if not isinstance(document, Mapping):
        return None

    rows = document.get("rows")
    if not isinstance(rows, list):
        return None
    read: list[Row] = []
    for entry in rows:
        row = _row(entry)
        if row is None:
            return None
        read.append(row)
    rows_read = tuple(read)
    timeout, default = _countdown(document, rows_read)
    return Listing(
        rows=rows_read,
        title=_text(document, "title"),
        hint=_text(document, "hint"),
        timeout=timeout,
        default=default,
    )


def _countdown(document: Mapping[str, Any], rows: tuple[Row, ...]) -> tuple[int, str]:
    """Seconds and the winning id, or `(0, "")` for a listing that waits.

    Both travel together or neither does, and everything unreadable answers the
    second way: a timeout naming no row of this listing is dropped whole rather
    than aimed at the first one. A countdown is a command saying which answer is
    right when nobody is at the keyboard, and guessing at that is how somebody
    loses what they meant to keep.
    """
    seconds = document.get("timeout")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return (0, "")
    if seconds <= 0:
        return (0, "")
    winner = document.get("default")
    if not isinstance(winner, str) or not any(row.id == winner for row in rows):
        return (0, "")
    return (max(1, int(seconds)), winner)


def _row(entry: Any) -> Row | None:
    """One row, or `None` when it is not one. Only `id` and `label` are required."""
    if not isinstance(entry, Mapping):
        return None
    identifier = entry.get("id")
    label = entry.get("label")
    if not isinstance(identifier, str) or not identifier:
        return None
    if not isinstance(label, str) or not label:
        return None
    if "\n" in identifier or "\r" in identifier:
        return None
    return Row(
        id=identifier,
        label=label,
        kind=_text(entry, "kind"),
        detail=_text(entry, "detail"),
    )


def _text(section: Mapping[str, Any], key: str) -> str:
    value = section.get(key)
    return value if isinstance(value, str) else ""


class ListView(ABC):
    """Where a listing is shown and a pick comes back from.

    A port, so `ProcessRunner` can hand rows somewhere without knowing whether that
    is a Textual screen, a plain stdout fallback, or a test.
    """

    @abstractmethod
    async def show(self, listing: Listing) -> str | None:
        """Render `listing`; return the `id` picked, or `None` to stop the command."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """The command is done with the list, or has exited."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Untimed(ListView):
    """`view` with every countdown taken out on the way through.

    Where the timer is switched off, what reaches the screen has no `timeout` in it
    at all, rather than a screen holding a flag it has to remember to check. It is
    also what keeps the degraded path honest: a command is never told whether its
    countdown is live, so nothing can be written to depend on one.
    """

    view: ListView

    async def show(self, listing: Listing) -> str | None:
        return await self.view.show(listing.untimed())

    def close(self) -> None:
        self.view.close()


@dataclass(slots=True)
class RecordingListView(ListView):
    """A `ListView` that answers from a script. For tests and for `PlainConsole`."""

    answers: list[str | None] = field(default_factory=list)
    seen: list[Listing] = field(default_factory=list)
    closed: int = 0

    async def show(self, listing: Listing) -> str | None:
        self.seen.append(listing)
        return self.answers.pop(0) if self.answers else None

    def close(self) -> None:
        self.closed += 1
