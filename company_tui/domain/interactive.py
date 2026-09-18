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

VIEW = f"{PREFIX}view"
STATUS = f"{PREFIX}status"
ASK = f"{PREFIX}ask"
OPEN = f"{PREFIX}open"
ACTION = f"{PREFIX}action"
ANSWER = f"{PREFIX}answer"
DETAIL = f"{PREFIX}detail"
"""The browser's half. Understood only where one can be drawn; text everywhere else."""

ALIGNS = ("left", "right", "center")
ON_DEMAND = "on-demand"
"""What a listing's `detail` says to have bodies asked for rather than sent."""

BROWSER = "browser"
"""What a manifest's `view` says to get one."""

MAX_PAYLOAD = 512 * 1024
"""A listing is a menu. Anything past this is a command streaming into the wrong door."""


@dataclass(frozen=True, slots=True)
class Row:
    """One choice. `id` is opaque here and echoed back exactly as it arrived."""

    id: str
    label: str
    kind: str = ""
    detail: str = ""

    cells: Mapping[str, str] = field(default_factory=dict)
    """What this row puts under each declared column, for a browser's table.

    A row carrying cells and no label of its own is labelled by its first cell, so
    the same row is still a readable line where there is no table to put it in."""

    detail_body: str = ""
    """This row's body, plain text, for the pane beside the table. Display only.

    Plain because a pane that rendered markup would be making typographic decisions
    about content whose meaning it does not know, and because it is shown exactly
    as it arrived - a diff, a log or a stack trace re-wrapped at the pane's width
    is unreadable at the moment somebody is relying on it."""


@dataclass(frozen=True, slots=True)
class Column:
    """One column of a browser's table, as the command declared it."""

    key: str
    label: str = ""
    width: int = 0
    """Cells wide, or 0 for whatever is left over."""

    grow: bool = False
    align: str = ""


@dataclass(frozen=True, slots=True)
class Node:
    """One entry of the tree down the left. `parent` empty is a root."""

    id: str
    label: str
    parent: str = ""


@dataclass(frozen=True, slots=True)
class ViewSpec:
    """`@dti:view`: the shape of the table and the tree beside it."""

    columns: tuple[Column, ...] = ()
    tree: tuple[Node, ...] = ()


@dataclass(frozen=True, slots=True)
class Action:
    """One thing offered on the action bar for as long as this listing is up.

    `danger` is styling and nothing else. What a dangerous action costs is the
    command's to explain, in its own words, as a listing of its own."""

    id: str
    label: str
    key: str = ""
    danger: bool = False


@dataclass(frozen=True, slots=True)
class Status:
    """`@dti:status`: one line under the list, in the command's own words."""

    text: str = ""


@dataclass(frozen=True, slots=True)
class Ask:
    """`@dti:ask`: the one place a text field belongs, for a value nothing can list."""

    prompt: str = ""
    value: str = ""

    multiline: bool = False
    """Whether a note rather than a name. Absent is exactly the single-line box."""


@dataclass(frozen=True, slots=True)
class Opened:
    """The user entered a row."""

    row: str


@dataclass(frozen=True, slots=True)
class Detailed:
    """The user settled on a row whose body has not been sent yet."""

    row: str


@dataclass(frozen=True, slots=True)
class Invoked:
    """The user ran an action, on a row or on wherever they are."""

    action: str
    row: str = ""


@dataclass(frozen=True, slots=True)
class Listing:
    """Rows to show, what to say above them, and an optional countdown."""

    rows: tuple[Row, ...] = ()
    title: str = ""
    hint: str = ""

    breadcrumb: tuple[str, ...] = ()
    actions: tuple[Action, ...] = ()

    on_demand: bool = False
    """Whether a row's body is asked for when it is selected rather than sent here.

    What it exists for is `MAX_PAYLOAD`: a listing carrying every row's log inline
    is a listing that stops arriving. Absent, nothing is ever requested and nothing
    is shown that was not sent."""

    pane: bool = False
    """Whether this is the browser's own list rather than a question over it.

    Set by the one key that separates them: a listing carrying `breadcrumb` is
    where the user is, and replaces the pane; one without it is a question and
    comes up as a modal over it. The command decides, and can therefore ask
    something in the middle of a browse without the browse being lost."""

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


def opened(identifier: str) -> str:
    """Written back when a row is entered in the browser."""
    return f"{OPEN} {identifier}"


def acted(action: str, identifier: str = "") -> str:
    """Written back when an action is invoked, on a row or on where the user is."""
    return f"{ACTION} {action} {identifier}".rstrip()


def detail(identifier: str) -> str:
    """Written back when a row is selected whose body was not sent with the listing."""
    return f"{DETAIL} {identifier}"


def answered(text: str) -> str:
    """Written back to `@dti:ask`. Nothing after the verb is a cancel.

    One message is one line, so a note comes back with its newlines written `\\n`
    and its backslashes doubled. Both, not just the newline: escaping one without
    the other is not reversible, and `C:\\new` would arrive as two lines.
    """
    if not text:
        return ANSWER
    escaped = (
        text.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )
    return f"{ANSWER} {escaped}"


def said(answer: "Opened | Invoked | Detailed") -> str:
    """Whichever line reports what the user just did in the browser."""
    if isinstance(answer, Opened):
        return opened(answer.row)
    if isinstance(answer, Detailed):
        return detail(answer.row)
    return acted(answer.action, answer.row)


Event = Listing | ViewSpec | Status | Ask | Finished


def parse(line: str) -> "Event | None":
    """One event, or `None` for a line that is ordinary output.

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
    if head == STATUS:
        return Status(payload.strip())
    if head not in (ROWS, VIEW, ASK) or len(payload) > MAX_PAYLOAD:
        return None
    try:
        document = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    if not isinstance(document, Mapping):
        return None
    if head == VIEW:
        return _spec(document)
    if head == ASK:
        return Ask(
            prompt=_text(document, "prompt"),
            value=_text(document, "value"),
            multiline=document.get("multiline") is True,
        )
    return _listing(document)


def _listing(document: Mapping[str, Any]) -> Listing | None:
    rows = document.get("rows")
    if not isinstance(rows, list):
        return None
    read: list[Row] = []
    for entry in rows:
        row = _row(entry)
        if row is None:
            return None
        read.append(row)

    crumbs = _crumbs(document)
    if crumbs is None:
        return None
    actions = _actions(document.get("actions"))
    if actions is None:
        return None

    rows_read = tuple(read)
    timeout, default = _countdown(document, rows_read)
    return Listing(
        rows=rows_read,
        title=_text(document, "title"),
        hint=_text(document, "hint"),
        breadcrumb=crumbs,
        actions=actions,
        on_demand=document.get("detail") == ON_DEMAND,
        pane="breadcrumb" in document,
        timeout=timeout,
        default=default,
    )


def _crumbs(document: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Where the user is, or `None` for a `breadcrumb` this build cannot read."""
    if "breadcrumb" not in document:
        return ()
    crumbs = document.get("breadcrumb")
    if not isinstance(crumbs, list):
        return None
    if any(not isinstance(crumb, str) for crumb in crumbs):
        return None
    return tuple(crumbs)


def _actions(value: Any) -> tuple[Action, ...] | None:
    """What the bar offers for this listing alone, `()` for none declared.

    Per listing and never remembered: a command that offers different things in
    different places gets that by saying so each time, and nothing here has to
    know why it varies.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    read: list[Action] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            return None
        identifier = entry.get("id")
        label = entry.get("label")
        if not isinstance(identifier, str) or not identifier:
            return None
        if not _one_line(identifier) or " " in identifier:
            return None
        if not isinstance(label, str) or not label:
            return None
        key = _text(entry, "key").strip().lower()
        read.append(
            Action(
                id=identifier,
                label=label,
                key=key if len(key) == 1 else "",
                danger=entry.get("danger") is True,
            )
        )
    return tuple(read)


def _spec(document: Mapping[str, Any]) -> ViewSpec | None:
    """`@dti:view`, or `None` when the shape it declares cannot be drawn."""
    declared = document.get("columns")
    if not isinstance(declared, list) or not declared:
        return None
    columns: list[Column] = []
    for entry in declared:
        if not isinstance(entry, Mapping):
            return None
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            return None
        width = entry.get("width")
        align = _text(entry, "align").strip().lower()
        columns.append(
            Column(
                key=key,
                label=_text(entry, "label") or key,
                width=width if isinstance(width, int) and not isinstance(width, bool)
                and width > 0 else 0,
                grow=entry.get("grow") is True,
                align=align if align in ALIGNS else "",
            )
        )

    tree = _nodes(document.get("tree"))
    if tree is None:
        return None
    return ViewSpec(columns=tuple(columns), tree=tree)


def _nodes(value: Any) -> tuple[Node, ...] | None:
    """The tree down the left, `()` where the command declared none."""
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    read: list[Node] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            return None
        identifier = entry.get("id")
        label = entry.get("label")
        if not isinstance(identifier, str) or not identifier:
            return None
        if not _one_line(identifier):
            return None
        if not isinstance(label, str) or not label:
            return None
        parent = entry.get("parent")
        read.append(
            Node(id=identifier, label=label, parent=parent if isinstance(parent, str) else "")
        )
    return tuple(read)


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
    """One row, or `None` when it is not one. An `id`, and something to call it."""
    if not isinstance(entry, Mapping):
        return None
    identifier = entry.get("id")
    if not isinstance(identifier, str) or not identifier:
        return None
    if not _one_line(identifier):
        return None

    cells = _cells(entry.get("cells"))
    if cells is None:
        return None
    label = entry.get("label")
    if not isinstance(label, str) or not label:
        label = next((value for value in cells.values() if value), "")
    if not label:
        return None
    return Row(
        id=identifier,
        label=label,
        kind=_text(entry, "kind"),
        detail=_text(entry, "detail"),
        cells=cells,
        detail_body=_text(entry, "detail_body"),
    )


def _cells(value: Any) -> dict[str, str] | None:
    """A row's columns, `{}` where it declares none.

    Strings, and only strings. A command already decides that 4402816 bytes reads
    as "4.2 MB"; a toolbox that started formatting numbers would be deciding it
    instead, for a column whose meaning it does not know.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return None
    read: dict[str, str] = {}
    for key, cell in value.items():
        if not isinstance(key, str) or not isinstance(cell, str):
            return None
        read[key] = cell
    return read


def _one_line(identifier: str) -> bool:
    """Whether this id can be written back as one line, which is the whole wire."""
    return "\n" not in identifier and "\r" not in identifier


def _text(section: Mapping[str, Any], key: str) -> str:
    value = section.get(key)
    return value if isinstance(value, str) else ""


class ListView(ABC):
    """Where a listing is shown and a pick comes back from.

    A port, so `ProcessRunner` can hand rows somewhere without knowing whether that
    is a Textual screen, a plain stdout fallback, or a test.

    The browser's half is concrete and inert, and `browsing` is the one question
    asked about it. A view answering `False` is never handed `@dti:view`,
    `@dti:status` or `@dti:ask` at all - the runner leaves them as output to print -
    so an implementation written before any of this existed is still a correct one,
    and a command sending them where no browser can be drawn is read by a person
    instead.
    """

    @abstractmethod
    async def show(self, listing: Listing) -> str | None:
        """Render `listing`; return the `id` picked, or `None` to stop the command."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """The command is done with the list, or has exited."""
        raise NotImplementedError

    @property
    def browsing(self) -> bool:
        """Whether this view is a place to move around in rather than a question."""
        return False

    def describe(self, spec: ViewSpec) -> None:  # noqa: B027 - inert on purpose; see the class
        """Take the table's columns and the tree beside it."""

    async def browse(self, listing: Listing) -> "Opened | Invoked | Detailed | None":
        """Show where the user is; report what they did, or `None` to stop."""
        raise NotImplementedError

    def say(self, status: Status) -> None:  # noqa: B027 - inert on purpose; see the class
        """Put one line under the list."""

    async def ask(self, question: Ask) -> str | None:
        """One text field. `None` is a cancel, which the command is told about."""
        return None


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

    @property
    def browsing(self) -> bool:
        return self.view.browsing

    def describe(self, spec: ViewSpec) -> None:
        self.view.describe(spec)

    async def browse(self, listing: Listing) -> "Opened | Invoked | Detailed | None":
        return await self.view.browse(listing.untimed())

    def say(self, status: Status) -> None:
        self.view.say(status)

    async def ask(self, question: Ask) -> str | None:
        return await self.view.ask(question)


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
