"""The two-pane browser: a breadcrumb, a tree, a table, an action bar, a status line.

Everything here is drawn from what the command sent and nothing else. There is no
terminal and no Run button, the columns are the ones `@dti:view` declared, and the
action bar holds exactly what the last `@dti:rows` offered - so a command listing
database tables gets the same view as one listing files, and this file contains
nothing that assumes either. `docs/decisions/0006` is why.
"""

import asyncio

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import (
    Horizontal,
    ScrollableContainer,
    Vertical,
    VerticalScroll,
)
from textual.message import Message
from textual.screen import Screen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from company_tui.domain.interactive import (
    Action,
    Column,
    Detailed,
    Invoked,
    Listing,
    Node,
    Opened,
    Row,
    Status,
    ViewSpec,
)
from company_tui.presentation.chrome import AppFooter, AppFrame, AppHeader, HoverLight

TRAIL_SEPARATOR = " › "
BROWSER_EMPTY = "Nothing here."
BROWSER_WAITING = "Waiting for the command..."
TREE_GLYPH = "▸"

DETAIL_DELAY = 0.25
"""Seconds a row has to stay selected before its body is asked for.

A held arrow key walks a dozen rows, and one request per row is a dozen round
trips for eleven bodies nobody looked at."""
DEFAULT_COLUMN = Column(key="", label="", grow=True)
"""What a table has when the command declared no columns: one, of row labels."""


def _laid_out(widget: Widget, column: Column) -> Widget:
    """A cell sized and aligned the way the command asked for that column."""
    if column.grow:
        widget.styles.width = "1fr"
    elif column.width:
        widget.styles.width = column.width
    else:
        widget.styles.width = "auto"
    if column.align:
        widget.styles.text_align = column.align
    return widget


class BrowseRow(Widget, can_focus=True):
    """One row of the table, as cells under the declared columns."""

    DEFAULT_CSS = """
    BrowseRow {
        width: 100%;
        height: 1;
        layout: horizontal;
    }

    BrowseRow .browse--cell {
        color: $foreground;
        margin-right: 2;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    BrowseRow:focus .browse--cell {
        color: $accent;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("enter", "open", "Open"),
        ("up", "previous", "Up"),
        ("down", "next", "Down"),
    ]
    """On the row, never the screen: a `VerticalScroll` answers the arrows first
    and the list would look frozen (`docs/pitfalls.md` 9.1)."""

    class Opened(Message):
        def __init__(self, identifier: str) -> None:
            self.identifier = identifier
            super().__init__()

    def __init__(self, row, columns: tuple[Column, ...]) -> None:
        super().__init__()
        self.row = row
        self._columns = columns

    def compose(self) -> ComposeResult:
        for column in self._columns:
            text = self.row.cells.get(column.key, "") if column.key else self.row.label
            yield _laid_out(Static(text, classes="browse--cell"), column)

    def on_click(self) -> None:
        self.focus()
        self.action_open()

    def on_enter(self) -> None:
        self.focus()

    def action_open(self) -> None:
        self.post_message(self.Opened(self.row.id))

    def action_previous(self) -> None:
        self.screen.focus_previous()

    def action_next(self) -> None:
        self.screen.focus_next()


class TreeRow(Widget, can_focus=True):
    """One node of the tree down the left, at the depth its parents give it."""

    DEFAULT_CSS = """
    TreeRow {
        width: 100%;
        height: 1;
        layout: horizontal;
    }

    TreeRow .tree--glyph {
        width: 2;
        color: $text-muted;
    }

    TreeRow .tree--label {
        width: 1fr;
        color: $text-muted;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    TreeRow.-at .tree--glyph,
    TreeRow.-at .tree--label {
        color: $foreground;
    }

    TreeRow:focus .tree--glyph,
    TreeRow:focus .tree--label {
        color: $accent;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("enter", "open", "Open"),
        ("up", "previous", "Up"),
        ("down", "next", "Down"),
    ]

    class Opened(Message):
        def __init__(self, identifier: str) -> None:
            self.identifier = identifier
            super().__init__()

    def __init__(self, node: Node, depth: int) -> None:
        super().__init__()
        self.node = node
        self._depth = depth

    def compose(self) -> ComposeResult:
        yield Static(TREE_GLYPH, classes="tree--glyph")
        label = Static(self.node.label, classes="tree--label")
        label.styles.padding = (0, 0, 0, self._depth * 2)
        yield label

    def on_click(self) -> None:
        self.focus()
        self.action_open()

    def on_enter(self) -> None:
        self.focus()

    def action_open(self) -> None:
        self.post_message(self.Opened(self.node.id))

    def action_previous(self) -> None:
        self.screen.focus_previous()

    def action_next(self) -> None:
        self.screen.focus_next()


class ActionChip(HoverLight, Widget):
    """One thing the current listing offers, with the key that runs it.

    The click and the key both end in the screen's `_fire`, over this chip's own
    `Action`, so the two cannot come to mean different things - the same reason
    every key hint in the app is also the button for that key.
    """

    DEFAULT_CSS = """
    ActionChip {
        width: auto;
        height: 1;
        margin-right: 3;
        layout: horizontal;
        pointer: pointer;
    }

    ActionChip .chip--key {
        width: auto;
        color: $foreground;
        text-style: bold;
    }

    ActionChip .chip--label {
        width: auto;
        margin-left: 1;
        color: $text-muted;
    }

    ActionChip.-danger .chip--key,
    ActionChip.-danger .chip--label {
        color: $error;
    }

    ActionChip.-hovered .chip--key,
    ActionChip.-hovered .chip--label {
        color: $accent;
        text-style: bold;
    }
    """

    class Fired(Message):
        def __init__(self, action: Action) -> None:
            self.action = action
            super().__init__()

    def __init__(self, action: Action) -> None:
        super().__init__(classes="-danger" if action.danger else "")
        self.action = action

    def compose(self) -> ComposeResult:
        yield Static(self.action.key.upper(), classes="chip--key")
        yield Static(self.action.label, classes="chip--label")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Fired(self.action))


class BrowserScreen(Screen[None]):
    """Where a command that is a place rather than a run puts the user.

    `browse` is the whole of how it is driven: it draws a listing and then waits,
    and what it returns is what the user did. Esc is `Stopped`, which the console
    turns into a cancel of the run behind it - there is nothing else here that
    could end a browse, since every other way out belongs to the command.
    """

    BINDINGS = [("escape", "leave", "Leave")]

    ALLOW_SELECT = False

    DEFAULT_CSS = """
    BrowserScreen {
        background: $background;
    }

    BrowserScreen #browse-body {
        width: 100%;
        height: 1fr;
        padding: 1 2 0 2;
    }

    BrowserScreen #browse-crumbs {
        width: 100%;
        height: 1;
        color: $text-muted;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    BrowserScreen #browse-title {
        width: 100%;
        height: 1;
        color: $primary;
        text-style: bold;
    }

    BrowserScreen #browse-panes {
        width: 100%;
        height: 1fr;
        margin-top: 1;
    }

    BrowserScreen #browse-tree {
        width: 30;
        height: 100%;
        border-right: solid $primary-lighten-1;
        padding-right: 1;
        scrollbar-size-vertical: 1;
    }

    BrowserScreen #browse-tree.-empty {
        display: none;
    }

    BrowserScreen #browse-table {
        width: 1fr;
        height: 100%;
        padding-left: 2;
        scrollbar-size-vertical: 1;
    }

    BrowserScreen #browse-heads {
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    BrowserScreen #browse-heads.-empty {
        display: none;
    }

    BrowserScreen .browse--head {
        color: $text-disabled;
        margin-right: 2;
        text-style: bold;
        text-wrap: nowrap;
    }

    BrowserScreen #browse-rows {
        width: 100%;
        height: auto;
    }

    BrowserScreen #browse-detail {
        width: 1fr;
        height: 100%;
        border-left: solid $primary-lighten-1;
        padding-left: 2;
        scrollbar-size: 1 1;
    }

    BrowserScreen #browse-detail.-empty {
        display: none;
    }

    BrowserScreen #detail-body {
        width: auto;
        height: auto;
        color: $foreground;
        text-wrap: nowrap;
    }

    BrowserScreen #browse-empty {
        width: 100%;
        color: $text-disabled;
    }

    BrowserScreen #browse-actions {
        width: 100%;
        height: 1;
        margin-top: 1;
    }

    BrowserScreen #browse-status {
        width: 100%;
        height: 1;
        color: $text-muted;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    class Stopped(Message):
        """Esc. The run behind this is what actually ends."""

    def __init__(self, title: str, trail=(), subtitle: str = "") -> None:
        super().__init__()
        self._title = title
        self._trail = tuple(trail)
        self._subtitle = subtitle
        self._columns: tuple[Column, ...] = ()
        self._actions: tuple[Action, ...] = ()
        self._answer: asyncio.Future | None = None
        self._at = ""
        self._said = False
        self._row: Row | None = None
        self._on_demand = False
        self._wanted = ""
        self._wait: Timer | None = None

    def compose(self) -> ComposeResult:
        with AppFrame():
            yield AppHeader()
            with Vertical(id="browse-body"):
                yield Static(self._title, id="browse-title")
                yield Static(self._crumb_line(()), id="browse-crumbs")
                with Horizontal(id="browse-panes"):
                    yield VerticalScroll(id="browse-tree", classes="-empty")
                    with VerticalScroll(id="browse-table"):
                        yield Horizontal(id="browse-heads", classes="-empty")
                        yield Vertical(id="browse-rows")
                    with ScrollableContainer(id="browse-detail", classes="-empty"):
                        yield Static(id="detail-body")
                yield Horizontal(id="browse-actions")
                yield Static(BROWSER_WAITING, id="browse-status")
            yield AppFooter(
                [("↑↓", "Move"), ("Enter", "Open"), ("Tab", "Body"), ("Esc", "Leave")]
            )

    def _crumb_line(self, crumbs: tuple[str, ...]) -> str:
        return TRAIL_SEPARATOR.join((*self._trail, *crumbs)) or self._subtitle

    def describe(self, spec: ViewSpec) -> None:
        """Take the shape of the table, and the tree beside it."""
        self._columns = spec.columns
        self.call_later(self._redraw_frame, spec)

    def say(self, status: Status) -> None:
        self._said = True
        self.call_later(self._write_status, status.text)

    def _write_status(self, text: str) -> None:
        """A status outlives the listing it was sent with. `@dti:rows` blocks until
        the user answers it, so a command saying something about what it is about to
        show has to say it first, and what it said then has to still be there."""
        for line in self.query("#browse-status"):
            line.update(text)

    async def _redraw_frame(self, spec: ViewSpec) -> None:
        heads = self.query_one("#browse-heads", Horizontal)
        await heads.remove_children()
        heads.set_class(not spec.columns, "-empty")
        if spec.columns:
            await heads.mount_all(
                _laid_out(Static(column.label, classes="browse--head"), column)
                for column in spec.columns
            )

        tree = self.query_one("#browse-tree", VerticalScroll)
        await tree.remove_children()
        tree.set_class(not spec.tree, "-empty")
        if spec.tree:
            await tree.mount_all(
                TreeRow(node, depth) for node, depth in _depths(spec.tree)
            )
        self._mark_tree()

    async def browse(self, listing: Listing) -> "Opened | Invoked | None":
        """Draw where the user is, then wait for them to do something about it."""
        await self._draw(listing)
        self._answer = asyncio.get_running_loop().create_future()
        try:
            return await self._answer
        finally:
            self._answer = None

    async def _draw(self, listing: Listing) -> None:
        """Put this listing up, leaving the user on the row they were already on.

        By id, and not at the top: `on-demand` answers a selection with a listing,
        so a redraw that moved the selection would ask about the new one forever
        (`docs/pitfalls.md` 9.6).
        """
        self.query_one("#browse-crumbs", Static).update(
            self._crumb_line(listing.breadcrumb)
        )
        self._on_demand = listing.on_demand

        focused = self.focused
        was = focused.row.id if isinstance(focused, BrowseRow) else ""

        columns = self._columns or (DEFAULT_COLUMN,)
        rows = self.query_one("#browse-rows", Vertical)
        await rows.remove_children()
        if listing.rows:
            await rows.mount_all(BrowseRow(row, columns) for row in listing.rows)
        else:
            await rows.mount(Static(BROWSER_EMPTY, id="browse-empty"))

        self._actions = listing.actions
        bar = self.query_one("#browse-actions", Horizontal)
        await bar.remove_children()
        if listing.actions:
            await bar.mount_all(ActionChip(action) for action in listing.actions)

        if listing.hint:
            self._said = True
            self._write_status(listing.hint)
        elif not self._said:
            self._write_status("")

        drawn = list(self.query(BrowseRow))
        here = next((row for row in drawn if row.row.id == was), None)
        here = here or (drawn[0] if drawn else None)
        if here is not None:
            here.focus()
        self._selected(here)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Only a row: the scrollers around them take the focus too, and neither of
        those is a selection (`docs/pitfalls.md` 9.4)."""
        if isinstance(event.widget, BrowseRow):
            self._selected(event.widget)

    def _selected(self, row: "BrowseRow | None") -> None:
        self._row = row.row if row is not None else None
        self._show_body()
        self._want_body()

    def _show_body(self) -> None:
        """The pane is there when the selected row has a body, and gone when it is not.

        `Text` rather than a markup string, because this is somebody else's log and
        a bracket in it is a bracket. `no_wrap` with a pane that scrolls sideways,
        because a diff re-wrapped at this width stops lining its markers up at the
        moment somebody is relying on them.
        """
        body = self._row.detail_body if self._row is not None else ""
        pane = self.query_one("#browse-detail", ScrollableContainer)
        pane.set_class(not body, "-empty")
        if not body:
            return
        self.query_one("#detail-body", Static).update(Text(body, no_wrap=True))
        pane.scroll_home(animate=False)

    def _want_body(self) -> None:
        """Ask for a body this listing did not carry, once the selection has settled."""
        self._stop_waiting()
        if not self._on_demand or self._row is None:
            return
        if self._row.detail_body or self._row.id == self._wanted:
            return
        self._wait = self.set_timer(DETAIL_DELAY, self._ask_for_body)

    def _ask_for_body(self) -> None:
        self._wait = None
        if self._row is None or self._row.detail_body:
            return
        self._wanted = self._row.id
        self._settle(Detailed(self._row.id))

    def _stop_waiting(self) -> None:
        if self._wait is not None:
            self._wait.stop()
            self._wait = None

    def on_unmount(self) -> None:
        """A screen that has gone cannot be the one a request was armed for."""
        self._stop_waiting()

    def _mark_tree(self) -> None:
        for row in self.query(TreeRow):
            row.set_class(row.node.id == self._at, "-at")

    def _settle(self, answer: "Opened | Invoked | None") -> None:
        if self._answer is not None and not self._answer.done():
            self._answer.set_result(answer)

    def on_browse_row_opened(self, message: BrowseRow.Opened) -> None:
        message.stop()
        self._at = message.identifier
        self._mark_tree()
        self._settle(Opened(message.identifier))

    def on_tree_row_opened(self, message: TreeRow.Opened) -> None:
        message.stop()
        self._at = message.identifier
        self._mark_tree()
        self._settle(Opened(message.identifier))

    def on_action_chip_fired(self, message: ActionChip.Fired) -> None:
        message.stop()
        self._fire(message.action)

    def on_key(self, event: events.Key) -> None:
        for action in self._actions:
            if action.key and event.key == action.key:
                event.stop()
                event.prevent_default()
                self._fire(action)
                return

    def _fire(self, action: Action) -> None:
        """Report the action, and whichever row the user had under the keyboard.

        A row when the focus was on one, and nothing when it was in the tree, on
        the bar, or on an empty table. What that means is the command's business:
        this only says what the user was looking at.
        """
        focused = self.focused
        row = focused.row.id if isinstance(focused, BrowseRow) else ""
        self._settle(Invoked(action.id, row))

    def action_leave(self) -> None:
        self.post_message(self.Stopped())


def _depths(nodes: tuple[Node, ...]) -> tuple[tuple[Node, int], ...]:
    """Each node with how far in it sits, counted through its parents.

    A parent nothing declares, and a cycle, both read as depth zero rather than
    raising: this is somebody else's tree and a toolbox that refused to draw a
    malformed one would be refusing to show what is actually there.
    """
    known = {node.id: node for node in nodes}
    read: list[tuple[Node, int]] = []
    for node in nodes:
        depth = 0
        seen = {node.id}
        parent = node.parent
        while parent and parent in known and parent not in seen:
            seen.add(parent)
            depth += 1
            parent = known[parent].parent
        read.append((node, depth))
    return tuple(read)
