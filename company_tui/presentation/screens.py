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
from textual.widget import Widget
from textual.widgets import Button, Input, Static

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
"""One short fade for the whole grid.

Cards used to fade in one at a time, which read as the menu loading rather than
arriving: the last of six started a third of a second after the first, and every
step of every workflow paid it. Entrances are for taking the edge off a repaint,
not for being watched."""

TRAIL_SEPARATOR = " › "

CARDS_PER_ROW = 3
"""Widest the card grid ever gets. More than three tiles across stops reading as
a set of choices and starts reading as a wall, so extra entries wrap instead."""

# All measured against the menu body, not the terminal, so they keep holding if
# the frame is ever sized smaller than the terminal.
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
    """A menu is buttons, not a document. Left as selectable, a press-and-drag
    across a card starts a text selection instead of pressing it — and a drag
    that is still open when the window is deactivated comes back as a highlight
    that follows the mouse and swallows the next click."""

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
                # A plain container, not a scrollable one: a scrollable container
                # binds the arrow keys to scrolling and would swallow them before
                # the grid could move the focus. The focused card scrolls itself
                # into view anyway.
                with Container(id="cards-scroll"), Grid(id="cards"):
                    for index, entry in enumerate(self._entries):
                        yield Card(entry, index)
                with Horizontal(id="menu-hint"):
                    yield Static(id="hint-key")
                    yield Static(id="hint-text")
            yield AppFooter(self._footer_hints())

    def _footer_hints(self) -> list[tuple[str, str]]:
        hints = [("↑↓/←→", "Navigate"), ("Enter", "Select")]
        # Only as far as a single keypress reaches. A menu long enough to run
        # out of digits is one a script repository grew, and a hint offering a
        # jump the keyboard cannot make is worse than one that stops short.
        jumpable = min(len(self._entries), 9)
        if jumpable > 1:
            hints.append((f"1–{jumpable}", "Jump"))
        # A run left going has to be reachable from here, or leaving it was the
        # same thing as losing it.
        if self._runs:
            hints.append(("Ctrl+B", self._runs))
        hints.append(("Esc", self._back_label))
        return hints

    def show_runs(self, runs: str) -> None:
        """Say what is still going, as it changes.

        Said once at compose time it would be a snapshot, and a menu offering a
        way back into a run that has already finished is worse than a menu that
        never mentioned it.
        """
        if runs == self._runs or not self.is_mounted:
            return
        self._runs = runs
        self.query_one(AppFooter).show_hints(self._footer_hints())

    def show_counts(self, running_under: Callable[[tuple[str, ...]], int]) -> None:
        """Re-read what is going on behind each card.

        The menu knows where it stands; what each card leads to is that plus
        the card's own name, which is the context a run there would belong to.
        """
        for card in self.query(Card):
            card.show_running(running_under((*self._trail, card.entry.name)))

    def on_mount(self) -> None:
        self.query_one("#cards").styles.grid_size_columns = self._columns
        # The whole body, not just the grid. Density can only be measured once
        # there is a layout to measure, so the cards cannot be there on the
        # first frame — and a trail, a title and a subtitle that arrive ahead of
        # them is a menu caught half-built, which at a glance is indistinguishable
        # from a different menu. Hidden rather than absent, so nothing shifts
        # when it arrives and what shows meanwhile is the same chrome the gap
        # between screens already shows.
        self.query_one("#menu-body").styles.opacity = 0.0
        first = next(iter(self.query(Card)), None)
        if first is not None:
            # Focused before the reveal, not after: a keypress in the frame in
            # between should land on the menu, not on nothing.
            first.focus()
            self._show_hint(first)
        self.call_after_refresh(self._reveal)

    def _reveal(self) -> None:
        """Size the grid, then bring the menu in — in that order, and as one.

        Sizing first is what keeps the cards from being shown at one size and
        then visibly re-flowing to another; revealing as one is what keeps the
        menu from being read before it is all there.
        """
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
        # Only a narrow body collapses the tiles into a list — a short one keeps
        # the cards at full size and scrolls them, because a squashed card stops
        # being a card while a scrollbar costs nothing.
        compact = width < needed_width
        scroll = compact or height < needed_height

        self._compact = compact
        self.set_class(compact, "-compact")
        cards = self.query_one("#cards")
        cards.set_class(compact, "-compact")
        self.query_one("#cards-scroll").set_class(scroll, "-scroll")
        # A grid row only keeps its height if it is told one; left to itself it
        # divides whatever room there is, which is the squashing we are avoiding.
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
        # Wrapping along a row is helpful; wrapping between rows would jump the
        # focus somewhere the arrow key did not point.
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
"""What a confirmation is about, before the sentence is read.

Not the warning sign it looks like in a design: `U+26A0` has an emoji form, so it
comes out double width in a colour of its own — see `tests/test_glyphs.py`. This
is the plain geometric triangle, and the colour does the rest.
"""


class ConfirmScreen(DialogScreen[bool]):
    """A question with two answers, one of which usually cannot be undone.

    Colour says which is which and the border says which one is focused, rather
    than the focused answer being filled in. Everything this asks about — quit
    with runs going, overwrite an existing tree, close a live tab — is a step
    the user does not get back, so neither answer may look pre-selected.
    """

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
        """The affirmative, with the key that also does it under the label.

        The key is on the button rather than only in a hint, because this is the
        one dialog reached by a chord: someone who pressed `Ctrl+Q` to get here
        should be able to see that pressing it again is the same answer.
        """
        label = Text(self._confirm, style="bold")
        if self._key:
            label.append("\n")
            label.append(self._key, style="not bold")
        return label

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputScreen(DialogScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, trail: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._trail = trail

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = self._trail or "Input"
            yield Static(self._prompt, id="input-prompt", classes="dialog--prompt")
            yield Input(id="input-value")
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

    BINDINGS = [("enter", "choose", "Go")]

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


class RunsScreen(DialogScreen[RunSession | None]):
    """Everything in flight, in one list, from wherever the user is.

    Each context keeps its own strip, so no one strip can show them all. This
    is the view that can: what is running, what is waiting on an answer and
    what has finished and not been read, each saying where it lives — and one
    press or click away from being on screen.
    """

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
            # The mark is sized to the art, so it needs something that centres a
            # child narrower than itself. `align-horizontal` on the container
            # does not: its other children are full width, so the row of content
            # already fills it and there is nothing left to centre.
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
    """What the app shows between saying yes to an update and going away.

    THE WINDOW VANISHING IS THE PROBLEM THIS SOLVES

    Pressing INSTALL AND RESTART used to close the app on the spot. Everything
    after that is correct and none of it is visible: a detached waiter sits on
    this pid, the installer runs silently, and a few seconds later a window
    opens on the new version. What the user gets is their terminal disappearing
    and something new appearing by itself, which is what a crash looks like and
    what a program they did not start looks like - so the one moment the app is
    doing exactly what it was asked to do is the one moment it looks like it is
    not.

    So the app says so, and says it on the way out rather than not at all.

    IT IS THE SPLASH, DELIBERATELY

    The same mark and the same wordmark the app opens on. The new build comes up
    on `SplashScreen` moments later, so leaving on the same picture makes the
    two windows read as one app restarting rather than as one closing and
    another opening - which is the half of the jump the old process can still do
    something about.

    NOTHING DISMISSES IT

    No bindings and no click handler. By the time this is on screen the handover
    is armed, something else is waiting on this pid, and there is nowhere to go
    back to - so a key that appeared to cancel would be a control that lies. It
    is the only screen in the app with no way out, and that is the honest shape
    for it.
    """

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
        # Turning rather than still. This screen is up for as long as shutting
        # down takes, which is one moment with nothing running and several with
        # a subprocess tree to kill - and a still frame held for four seconds is
        # the wedged window the mark exists to rule out.
        self._turn()
        self.set_interval(BUSY_INTERVAL, self._turn)

    def _turn(self) -> None:
        glyph = BUSY_FRAMES[self._frame % len(BUSY_FRAMES)]
        self.query_one("#installing", Static).update(
            f"{glyph}  " + INSTALLING_TITLE.format(version=self._version)
        )
        self._frame += 1
