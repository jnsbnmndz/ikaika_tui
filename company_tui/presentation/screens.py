"""Every screen the app pushes: menus, dialogs, the run picker and the splash."""

from collections.abc import Callable, Sequence

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import (
    Center,
    Container,
    Grid,
    Horizontal,
    Vertical,
    VerticalScroll,
)
from textual.message import Message
from textual.screen import ModalScreen, Screen, ScreenResultType
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Input, Static

from company_tui.domain.interactive import Listing, Row
from company_tui.presentation.branding import (
    APP_TAGLINE,
    APP_VERSION,
    SPLASH_MARK,
    WORDMARK,
)
from company_tui.presentation.card import Card, MenuEntry
from company_tui.presentation.chrome import (
    BUSY_FRAMES,
    BUSY_INTERVAL,
    AppFooter,
    AppFrame,
    AppHeader,
    KeyHint,
)
from company_tui.presentation.hints import hint_for
from company_tui.presentation.session import RunSession

CARD_ENTRANCE_DURATION = 0.12
"""One short fade for the whole grid."""

TRAIL_SEPARATOR = " › "

CARDS_PER_ROW = 3
"""Widest the card grid ever gets. More than three tiles across stops reading as."""

CARD_MIN_WIDTH = 26
CARD_MIN_HEIGHT = 16
ROW_GUTTER = 1
COLUMN_GUTTER = 2
MENU_CHROME_HEIGHT = 6


class CardMenuScreen(Screen[int | None]):
    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("left", "focus_previous_card", "Prev"),
        ("right", "focus_next_card", "Next"),
        ("up", "focus_row_up", "Up"),
        ("down", "focus_row_down", "Down"),
    ]

    ALLOW_SELECT = False
    """A menu is buttons, not a document. Left as selectable, a press-and-drag."""

    DEFAULT_CSS = """
    CardMenuScreen {
        align: center middle;
        background: $background;
    }

    CardMenuScreen #menu-body {
        width: 100%;
        height: 1fr;
        padding: 1 2 0 2;
    }

    CardMenuScreen #menu-trail {
        width: 100%;
        height: 1;
        color: $secondary;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    CardMenuScreen #menu-trail.-empty {
        display: none;
    }

    CardMenuScreen #menu-notice {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $warning;
        text-style: bold;
    }

    CardMenuScreen #menu-notice.-empty {
        display: none;
    }

    CardMenuScreen #menu-title {
        width: 100%;
        height: 1;
        text-style: bold;
        color: $accent;
    }

    CardMenuScreen #menu-subtitle {
        width: 100%;
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
    }

    CardMenuScreen #cards-scroll {
        width: 100%;
        height: 1fr;
        overflow: hidden;
    }

    CardMenuScreen #cards-scroll.-scroll {
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }

    CardMenuScreen #cards {
        width: 100%;
        height: 100%;
        grid-gutter: 1 2;
        align: center top;
    }

    CardMenuScreen #cards-scroll.-scroll #cards {
        height: auto;
    }

    CardMenuScreen #cards.-compact {
        layout: vertical;
        align-vertical: top;
    }

    CardMenuScreen.-compact #menu-subtitle {
        display: none;
    }

    CardMenuScreen #menu-hint {
        width: 100%;
        height: 1;
        margin-top: 1;
    }

    CardMenuScreen #hint-key {
        width: auto;
        text-style: bold;
        color: $accent;
    }

    CardMenuScreen #hint-text {
        width: 1fr;
        margin-left: 2;
        color: $text-muted;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    CardMenuScreen.-compact #menu-title {
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        title: str,
        entries: Sequence[MenuEntry],
        subtitle: str = "",
        back_label: str = "Back",
        trail: Sequence[str] = (),
        notice: str = "",
        runs: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._entries = tuple(entries)
        self._subtitle = subtitle
        self._back_label = back_label
        self._trail = tuple(trail)
        self._notice = notice
        self._runs = runs
        self._columns = min(CARDS_PER_ROW, max(len(self._entries), 1))
        self._rows = -(-len(self._entries) // self._columns)
        self._compact = False

    def compose(self) -> ComposeResult:
        with AppFrame():
            yield AppHeader()
            with Vertical(id="menu-body"):
                yield Static(
                    TRAIL_SEPARATOR.join(self._trail),
                    id="menu-trail",
                    classes="" if self._trail else "-empty",
                )
                yield Static(
                    self._notice,
                    id="menu-notice",
                    classes="" if self._notice else "-empty",
                )
                yield Static(self._title, id="menu-title")
                yield Static(self._subtitle, id="menu-subtitle")
                with Container(id="cards-scroll"), Grid(id="cards"):
                    for index, entry in enumerate(self._entries):
                        yield Card(entry, index)
                with Horizontal(id="menu-hint"):
                    yield Static(id="hint-key")
                    yield Static(id="hint-text")
            yield AppFooter(self._footer_hints())

    def _footer_hints(self) -> list[tuple[str, str]]:
        hints = [("↑↓/←→", "Navigate"), ("Enter", "Select")]
        jumpable = min(len(self._entries), 9)
        if jumpable > 1:
            hints.append((f"1–{jumpable}", "Jump"))
        if self._runs:
            hints.append(("Ctrl+B", self._runs))
        hints.append(("Esc", self._back_label))
        return hints

    def show_runs(self, runs: str) -> None:
        """Say what is still going, as it changes."""
        if runs == self._runs or not self.is_mounted:
            return
        self._runs = runs
        self.query_one(AppFooter).show_hints(self._footer_hints())

    def show_counts(self, running_under: Callable[[tuple[str, ...]], int]) -> None:
        """Re-read what is going on behind each card."""
        for card in self.query(Card):
            card.show_running(running_under((*self._trail, card.entry.name)))

    def on_mount(self) -> None:
        self.query_one("#cards").styles.grid_size_columns = self._columns
        self.query_one("#menu-body").styles.opacity = 0.0
        first = next(iter(self.query(Card)), None)
        if first is not None:
            first.focus()
            self._show_hint(first)
        self.call_after_refresh(self._reveal)

    def _reveal(self) -> None:
        """Size the grid, then bring the menu in — in that order, and as one."""
        self._sync_density()
        self.query_one("#menu-body").styles.animate(
            "opacity", value=1.0, duration=CARD_ENTRANCE_DURATION, easing="out_cubic"
        )

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._sync_density)

    def _sync_density(self) -> None:
        body = self.query_one("#menu-body")
        if not body.size.width or not body.size.height:
            return
        self._apply_density(body.size.width, body.size.height)

    def _apply_density(self, width: int, height: int) -> None:
        needed_width = (
            CARD_MIN_WIDTH * self._columns + COLUMN_GUTTER * (self._columns - 1)
        )
        needed_height = (
            self._rows * CARD_MIN_HEIGHT
            + (self._rows - 1) * ROW_GUTTER
            + MENU_CHROME_HEIGHT
        )
        compact = width < needed_width
        scroll = compact or height < needed_height

        self._compact = compact
        self.set_class(compact, "-compact")
        cards = self.query_one("#cards")
        cards.set_class(compact, "-compact")
        self.query_one("#cards-scroll").set_class(scroll, "-scroll")
        cards.styles.grid_rows = str(CARD_MIN_HEIGHT) if scroll else "1fr"
        for card in self.query(Card):
            card.set_class(compact, "-compact")

    def on_card_focused(self, message: Card.Focused) -> None:
        self._show_hint(message.card)

    def _show_hint(self, card: Card) -> None:
        entry = card.entry
        self.query_one("#hint-key", Static).update(entry.name.upper())
        self.query_one("#hint-text", Static).update(
            entry.detail or hint_for(entry.key, entry.description)
        )

    def on_card_selected(self, message: Card.Selected) -> None:
        self.dismiss(message.card.index)

    def on_key(self, event: events.Key) -> None:
        if not event.key.isdigit():
            return
        index = int(event.key) - 1
        if 0 <= index < len(self._entries):
            event.stop()
            self.dismiss(index)

    def action_focus_previous_card(self) -> None:
        self._shift_focus(-1)

    def action_focus_next_card(self) -> None:
        self._shift_focus(1)

    def action_focus_row_up(self) -> None:
        self._shift_focus(-self._row_stride(), wrap=False)

    def action_focus_row_down(self) -> None:
        self._shift_focus(self._row_stride(), wrap=False)

    def _row_stride(self) -> int:
        """One row down is a whole row of cards, unless they are stacked."""
        return 1 if self._compact else self._columns

    def _shift_focus(self, delta: int, wrap: bool = True) -> None:
        cards = list(self.query(Card))
        if not cards:
            return
        current = next((index for index, card in enumerate(cards) if card.has_focus), 0)
        target = current + delta
        target = target % len(cards) if wrap else max(0, min(len(cards) - 1, target))
        cards[target].focus()

    def action_go_back(self) -> None:
        self.dismiss(None)


class DialogScreen(ModalScreen[ScreenResultType]):
    """Shared look for the small prompts that interrupt a workflow."""

    DEFAULT_CSS = """
    DialogScreen {
        align: center middle;
        background: $background 70%;
    }

    DialogScreen > Container {
        width: 64;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    DialogScreen .dialog--heading {
        width: 100%;
        height: auto;
    }

    DialogScreen .dialog--prompt {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $foreground;
    }

    DialogScreen .dialog--actions {
        width: 100%;
        height: auto;
        padding-top: 1;
        border-top: solid $primary-lighten-1;
        align-horizontal: right;
    }

    DialogScreen .dialog--escape {
        width: 1fr;
        height: 3;
        align: left middle;
    }

    /* A row of buttons deep enough for a label with its key under it. Both
       buttons take the height whether or not they carry a key, because two
       actions at two different heights read as two different kinds of thing. */
    DialogScreen .dialog--actions.-keyed Button {
        height: 4;
    }

    /* Outlined, never filled, and the border is what says which one is
       focused — the same grammar as the run panel's SEND. A filled answer
       reads as an answer already chosen, which is the last thing a dialog
       asking before something destructive should say. `!important` and the
       tint reset are what it takes to get out from under Textual's own Button
       rules, which paint a background on focus and hover. */
    DialogScreen Button {
        min-width: 14;
        height: 3;
        margin-left: 2;
        border: round $primary-lighten-1 !important;
        background: transparent !important;
        color: $foreground;
        text-style: bold;
        content-align: center middle;
    }

    /* Focus doubles the line, and does nothing else at all. Textual's own
       `$button-focus-text-style` is `bold reverse`, and the reverse is what
       paints a block behind the label — the button's colours swapped, which
       reads as a filled button however transparent the background is. Hover and
       press are held to the same rule: the label never changes colour, nothing
       behind it is ever painted, and the border carries the whole state. */
    DialogScreen Button:hover,
    DialogScreen Button.-active,
    DialogScreen Button:focus {
        background: transparent;
        background-tint: 0%;
        tint: $background 0%;
        text-style: bold !important;
    }

    /* A border that changed colour would be the answer's own colour arguing
       with the focus colour; doubling says the same thing without collision. */
    DialogScreen Button:focus {
        border: double $accent !important;
    }

    DialogScreen Input {
        margin-bottom: 1;
        border: round $primary-lighten-1;
        background: $panel;
    }

    DialogScreen Input:focus {
        border: round $accent;
    }
    """

CONFIRM_MARK = "▲"
"""What a confirmation is about, before the sentence is read."""

class ConfirmScreen(DialogScreen[bool]):
    """A question with two answers, one of which usually cannot be undone."""

    DEFAULT_CSS = """
    ConfirmScreen .dialog--mark {
        width: 3;
        height: 1;
        color: $warning;
        text-style: bold;
    }

    /* The question, in the colour of the mark beside it, so the two read as one
       thing rather than as a bullet that happens to precede a sentence. */
    ConfirmScreen #confirm-prompt {
        width: 1fr;
        color: $warning;
        text-style: bold;
    }

    /* What the question means, for anyone who wants it. The title alone answers
       "what is this", and this answers "what happens if I say yes" — which is
       the part worth having before a step that cannot be undone. */
    ConfirmScreen #confirm-detail {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $text-muted;
    }

    /* The way back, and the thing there is no way back from. */
    ConfirmScreen #no {
        color: $warning;
        border: round $warning !important;
    }

    ConfirmScreen #no:focus {
        border: double $warning !important;
    }

    ConfirmScreen #yes {
        color: $error;
        border: round $error !important;
    }

    ConfirmScreen #yes:focus {
        border: double $error !important;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        prompt: str,
        trail: str = "",
        detail: str = "",
        confirm: str = "CONFIRM",
        key: str = "",
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._trail = trail
        self._detail = detail
        self._confirm = confirm
        self._key = key

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = self._trail or "Confirm"
            with Horizontal(classes="dialog--heading"):
                yield Static(CONFIRM_MARK, classes="dialog--mark")
                yield Static(self._prompt, id="confirm-prompt", classes="dialog--prompt")
            if self._detail:
                yield Static(self._detail, id="confirm-detail")
            actions = "dialog--actions -keyed" if self._key else "dialog--actions"
            with Horizontal(classes=actions):
                with Horizontal(classes="dialog--escape"):
                    yield KeyHint("Esc", "Cancel", dim=True)
                yield Button("CANCEL", id="no", flat=True)
                yield Button(self._answer(), id="yes", flat=True)

    def _answer(self) -> Text:
        """The affirmative, with the key that also does it under the label."""
        label = Text(self._confirm, style="bold")
        if self._key:
            label.append("\n")
            label.append(self._key, style="not bold")
        return label

    def on_key(self, event: events.Key) -> None:
        """The key printed on the affirmative is the affirmative."""
        if self._key and event.key == self._key.lower():
            event.stop()
            event.prevent_default()
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputScreen(DialogScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, trail: str = "", value: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._trail = trail
        self._value = value

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = self._trail or "Input"
            yield Static(self._prompt, id="input-prompt", classes="dialog--prompt")
            yield Input(self._value, id="input-value")
            with Horizontal(classes="dialog--actions"):
                with Horizontal(classes="dialog--escape"):
                    yield KeyHint("Esc", "Go back", dim=True)
                yield Button("Submit", id="submit", variant="primary", flat=True)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.dismiss(self.query_one("#input-value", Input).value.strip())

    def action_cancel(self) -> None:
        self.dismiss("")


class RunRow(Widget, can_focus=True):
    """One run in the picker: what it is doing, what it is called, where it is."""

    DEFAULT_CSS = """
    RunRow {
        width: 100%;
        height: 1;
        layout: horizontal;
    }

    RunRow .run--glyph {
        width: 2;
        color: $text-muted;
    }

    RunRow .run--name {
        width: 14;
        color: $foreground;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    RunRow .run--where {
        width: 1fr;
        margin-left: 1;
        color: $text-disabled;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    RunRow .run--state {
        width: auto;
        margin-left: 1;
        color: $text-muted;
    }

    RunRow:focus .run--glyph,
    RunRow:focus .run--name,
    RunRow:focus .run--where,
    RunRow:focus .run--state {
        color: $accent;
        text-style: bold;
    }

    RunRow.-asking .run--glyph,
    RunRow.-asking .run--state {
        color: $warning;
    }

    RunRow.-failed .run--glyph,
    RunRow.-failed .run--state {
        color: $error;
    }
    """

    BINDINGS = [
        ("enter", "choose", "Go"),
        ("up", "previous", "Up"),
        ("down", "next", "Down"),
    ]
    """On the row, not the screen: the scroller answers arrow keys on the way up.

    `RunsScreen` declared these and they never fired, so the list could only be
    clicked - see `PickRow` and docs/pitfalls.md 9.1."""

    class Chosen(Message):
        def __init__(self, session: RunSession) -> None:
            self.session = session
            super().__init__()

    def __init__(self, session: RunSession) -> None:
        super().__init__(classes=f"-{session.status.value}")
        self.session = session

    def compose(self) -> ComposeResult:
        status = self.session.status
        yield Static(status.glyph, classes="run--glyph")
        yield Static(self.session.name, classes="run--name")
        yield Static(
            TRAIL_SEPARATOR.join(self.session.scope), classes="run--where"
        )
        yield Static(status.value, classes="run--state")

    def on_click(self) -> None:
        self.action_choose()

    def on_enter(self) -> None:
        self.focus()

    def action_choose(self) -> None:
        self.post_message(self.Chosen(self.session))

    def action_previous(self) -> None:
        self.screen.focus_previous()

    def action_next(self) -> None:
        self.screen.focus_next()


class RunsScreen(DialogScreen[RunSession | None]):
    """Everything in flight, in one list, from wherever the user is."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("up", "focus_previous", "Up"),
        ("down", "focus_next", "Down"),
    ]

    DEFAULT_CSS = """
    /* Wider than the other dialogs: every row carries the whole breadcrumb, and
       a run identified as `Scaffold › New Project › Rea…` is not identified. */
    RunsScreen > Container {
        width: 84;
    }

    RunsScreen #runs {
        width: 100%;
        height: auto;
        max-height: 14;
        margin-bottom: 1;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, sessions: Sequence[RunSession]) -> None:
        super().__init__()
        self._sessions = tuple(sessions)

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = "Runs"
            with VerticalScroll(id="runs"):
                for session in self._sessions:
                    yield RunRow(session)
            with Horizontal(classes="dialog--actions"):
                with Horizontal(classes="dialog--escape"):
                    yield KeyHint("Esc", "Close", dim=True)

    def on_mount(self) -> None:
        first = next(iter(self.query(RunRow)), None)
        if first is not None:
            first.focus()

    def on_run_row_chosen(self, message: RunRow.Chosen) -> None:
        message.stop()
        self.dismiss(message.session)

    def action_cancel(self) -> None:
        self.dismiss(None)


ROW_GLYPHS = {"folder": "▸", "file": "·", "back": "❯"}
ROW_FALLBACK = "·"
"""Line art per `kind`, with one for a kind this build has never heard of.

`kind` is presentation only and a command may invent any word for it, so an
unknown one has to render as something rather than as nothing."""

PICK_TITLE = "Choose"
PICK_EMPTY = "Nothing to choose from."

PICK_COUNTDOWN = "{seconds}s → {label}"
"""How long is left and which row wins, in the line somebody is already reading."""

COUNTDOWN_TICK = 1.0
"""One second, because the hint is counting seconds. A constant so a test can run
the clock faster than somebody would sit through."""


class PickRow(Widget, can_focus=True):
    """One row of a listing: what it is, what it is called, and what it says."""

    DEFAULT_CSS = """
    PickRow {
        width: 100%;
        height: 1;
        layout: horizontal;
    }

    PickRow .pick--glyph {
        width: 2;
        color: $text-muted;
    }

    PickRow .pick--label {
        width: 1fr;
        color: $foreground;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    PickRow .pick--detail {
        width: auto;
        margin-left: 2;
        color: $text-disabled;
        text-wrap: nowrap;
    }

    PickRow:focus .pick--glyph,
    PickRow:focus .pick--label,
    PickRow:focus .pick--detail {
        color: $accent;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("enter", "choose", "Choose"),
        ("up", "previous", "Up"),
        ("down", "next", "Down"),
    ]
    """Here rather than on the screen, because the row is what has focus.

    A `VerticalScroll` binds the arrow keys to scrolling and answers them on the
    way up, so a screen-level `focus_next` is never reached and the list looks
    frozen. The focused widget is asked first, which is the one place a key can be
    caught before the scroller takes it."""

    class Chosen(Message):
        def __init__(self, identifier: str) -> None:
            self.identifier = identifier
            super().__init__()

    def __init__(self, row: Row) -> None:
        super().__init__()
        self.row = row

    def compose(self) -> ComposeResult:
        yield Static(ROW_GLYPHS.get(self.row.kind, ROW_FALLBACK), classes="pick--glyph")
        yield Static(self.row.label, classes="pick--label")
        if self.row.detail:
            yield Static(self.row.detail, classes="pick--detail")

    def on_click(self) -> None:
        self.action_choose()

    def on_enter(self) -> None:
        self.focus()

    def action_choose(self) -> None:
        self.post_message(self.Chosen(self.row.id))

    def action_previous(self) -> None:
        self.screen.focus_previous()

    def action_next(self) -> None:
        self.screen.focus_next()


class PickScreen(DialogScreen[str | None]):
    """Rows a command handed over, as a list rather than as log text.

    Dismisses with the chosen `id`, or `None` for Esc — which the runner reads as
    "nothing is going to answer this" and stops the command. The id is echoed back
    exactly as it arrived; nothing here interprets it.

    A listing may count down to a row of its own naming, and that expiry dismisses
    with the row's `id` like any other answer — never with `None`, which would stop
    the command rather than answer it. Any interaction ends the countdown for good.
    """

    BINDINGS = [
        ("escape", "cancel", "Stop"),
        ("up", "focus_previous", "Up"),
        ("down", "focus_next", "Down"),
    ]

    DEFAULT_CSS = """
    PickScreen > Container {
        width: 84;
    }

    PickScreen #pick-hint {
        width: 100%;
        margin-bottom: 1;
        color: $text-muted;
    }

    PickScreen #pick-rows {
        width: 100%;
        height: auto;
        max-height: 16;
        margin-bottom: 1;
        scrollbar-size-vertical: 1;
    }

    PickScreen #pick-empty {
        width: 100%;
        margin-bottom: 1;
        color: $text-disabled;
    }
    """

    def __init__(self, listing: Listing) -> None:
        super().__init__()
        self._listing = listing
        self._remaining = listing.timeout if listing.counts_down else 0
        self._timer: Timer | None = None
        self._opened_on: Widget | None = None

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = self._listing.title or PICK_TITLE
            if self._listing.hint or self._remaining:
                yield Static(self._hint_line(), id="pick-hint")
            if self._listing.rows:
                with VerticalScroll(id="pick-rows"):
                    for row in self._listing.rows:
                        yield PickRow(row)
            else:
                yield Static(PICK_EMPTY, id="pick-empty")
            with Horizontal(classes="dialog--actions"):
                with Horizontal(classes="dialog--escape"):
                    yield KeyHint("Esc", "Stop", dim=True)

    def on_mount(self) -> None:
        first = next(iter(self.query(PickRow)), None)
        if first is not None:
            first.focus()
        self._opened_on = first
        if self._remaining:
            self._timer = self.set_interval(COUNTDOWN_TICK, self._tick)

    def on_unmount(self) -> None:
        """Nothing left to fire into. Only the timer, since the line it writes is gone."""
        self._stop_timer()

    def on_key(self, event: events.Key) -> None:
        self._stop_countdown()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._stop_countdown()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """A row other than the one this screen opened on - the pointer moved over
        the list, which is somebody reading it and never sends a key.

        Only a row: the scroller around them takes the focus first on the way up,
        and a screen that treated its own arrival as an interaction would cancel
        every countdown before it drew one.
        """
        if isinstance(event.widget, PickRow) and event.widget is not self._opened_on:
            self._stop_countdown()

    def on_pick_row_chosen(self, message: PickRow.Chosen) -> None:
        message.stop()
        self.dismiss(message.identifier)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _hint_line(self) -> str:
        """What the command said, then what is about to happen and when."""
        if not self._remaining:
            return self._listing.hint
        counting = PICK_COUNTDOWN.format(
            seconds=self._remaining, label=self._winner_label()
        )
        return f"{self._listing.hint}   {counting}" if self._listing.hint else counting

    def _winner_label(self) -> str:
        """The row's own words, falling back to its id rather than to nothing."""
        return next(
            (row.label for row in self._listing.rows if row.id == self._listing.default),
            self._listing.default,
        )

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining > 0:
            self._say_remaining()
            return
        self._stop_timer()
        self.dismiss(self._listing.default)

    def _stop_countdown(self) -> None:
        """For good, and nothing re-arms it.

        An interaction is somebody reading the list, and a choice taken away
        mid-read is worse than never offering to answer it at all.
        """
        if self._timer is None and not self._remaining:
            return
        self._stop_timer()
        self._remaining = 0
        self._say_remaining()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _say_remaining(self) -> None:
        line = next(iter(self.query("#pick-hint")), None)
        if isinstance(line, Static):
            line.update(self._hint_line())


class ContinueScreen(DialogScreen[None]):
    BINDINGS = [("enter", "dismiss_continue", "Continue"), ("escape", "dismiss_continue", "Continue")]

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = "Done"
            yield Static(
                "Press Enter or click to continue", classes="dialog--prompt"
            )

    def action_dismiss_continue(self) -> None:
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)


class SplashScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_splash", "Continue"), ("enter", "dismiss_splash", "Continue")]

    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
        background: $background;
    }

    SplashScreen > Container {
        width: 34;
        height: auto;
        align-horizontal: center;
    }

    /* Sized to the art and centred as one block. Centring each line separately
       would slide the ragged lines of the mark out of register with each
       other, which for a picture means taking it apart. */
    SplashScreen #mark {
        width: auto;
        height: auto;
        color: $accent;
    }

    SplashScreen #wordmark {
        width: 100%;
        margin-top: 1;
        text-align: center;
        text-style: bold;
        color: $foreground;
    }

    SplashScreen #tagline {
        width: 100%;
        text-align: center;
        color: $text-muted;
    }

    SplashScreen #version {
        width: 100%;
        margin-bottom: 1;
        text-align: center;
        color: $text-disabled;
    }

    SplashScreen #hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        with Container():
            with Center():
                yield Static(SPLASH_MARK, id="mark")
            yield Static(WORDMARK, id="wordmark")
            yield Static(APP_TAGLINE, id="tagline")
            yield Static(APP_VERSION, id="version")
            yield Static("Press any key to continue", id="hint")

    def on_mount(self) -> None:
        container = self.query_one(Container)
        container.styles.opacity = 0.0
        container.styles.animate("opacity", value=1.0, duration=0.6, easing="out_cubic")

    def action_dismiss_splash(self) -> None:
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)


INSTALLING_TITLE = "Installing {version}"
INSTALLING_DETAIL = "This window closes and reopens on the new version."


class InstallingScreen(ModalScreen[None]):
    """What the app shows between saying yes to an update and going away."""

    BINDINGS = []

    DEFAULT_CSS = """
    InstallingScreen {
        align: center middle;
        background: $background;
    }

    InstallingScreen > Container {
        width: 52;
        height: auto;
        align-horizontal: center;
    }

    /* Sized to the art and centred as one block - see SplashScreen, which has
       the same arrangement for the same reason. */
    InstallingScreen #mark {
        width: auto;
        height: auto;
        color: $accent;
    }

    InstallingScreen #wordmark {
        width: 100%;
        margin-top: 1;
        text-align: center;
        text-style: bold;
        color: $foreground;
    }

    InstallingScreen #installing {
        width: 100%;
        margin-top: 1;
        text-align: center;
        color: $secondary;
    }

    InstallingScreen #detail {
        width: 100%;
        text-align: center;
        color: $text-muted;
    }

    """

    def __init__(self, version: str) -> None:
        super().__init__()
        self._version = version
        self._frame = 0

    def compose(self) -> ComposeResult:
        with Container():
            with Center():
                yield Static(SPLASH_MARK, id="mark")
            yield Static(WORDMARK, id="wordmark")
            yield Static(id="installing")
            yield Static(INSTALLING_DETAIL, id="detail")

    def on_mount(self) -> None:
        self._turn()
        self.set_interval(BUSY_INTERVAL, self._turn)

    def _turn(self) -> None:
        glyph = BUSY_FRAMES[self._frame % len(BUSY_FRAMES)]
        self.query_one("#installing", Static).update(
            f"{glyph}  " + INSTALLING_TITLE.format(version=self._version)
        )
        self._frame += 1
