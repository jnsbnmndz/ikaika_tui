from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from company_tui.presentation.icons import art_for


def running_text(count: int) -> str:
    """What a card says about the runs going on behind it.

    Words, with no glyph in front of them. Every pointer, clock and stop shape
    worth reaching for lives in the block terminals render from an emoji font
    instead of a text one — double width, its own colour, and nothing like the
    line art beside it. The accent colour is what makes this line stand out.
    """
    return f"{count} running" if count else ""


@dataclass(frozen=True, slots=True)
class MenuEntry:
    key: str
    name: str
    description: str
    running: int = 0
    """Runs still going at or below this option. A menu that says nothing about
    them makes the user open every door to find the one they left work behind."""


class Card(Widget, can_focus=True):
    """One menu option.

    The `-compact` class collapses the card to a single row for terminals too
    narrow to give every option a full tile; the compose tree stays the same so
    only the stylesheet decides which layout is in play. A merely short terminal
    keeps the tiles and scrolls them instead.

    Hovering focuses the card rather than styling it separately, so the accent
    border marks exactly one option whether you arrived by mouse or by keyboard.
    The card has no fill of its own in any state — only the border speaks — and
    `max-height` stops a tall terminal from stretching the tiles out of shape.
    """

    BINDINGS = [("enter", "select", "Select")]

    DEFAULT_CSS = """
    Card {
        width: 100%;
        max-width: 42;
        height: 100%;
        max-height: 18;
        border: round $primary-lighten-1;
        background: transparent;
        padding: 0 1;
    }

    Card:focus {
        border: double $accent;
    }

    Card .card--badge {
        width: 4;
        height: 3;
        border: round $primary-lighten-2;
        color: $text-muted;
        text-align: center;
    }

    Card:focus .card--badge {
        border: double $accent;
        color: $accent;
        text-style: bold;
    }

    Card .card--art-slot {
        width: 100%;
        height: 1fr;
        min-height: 5;
        align: center middle;
    }

    Card .card--art {
        width: auto;
        height: auto;
        color: $secondary;
    }

    Card:focus .card--art {
        color: $accent;
    }

    Card .card--name {
        width: 100%;
        height: 1;
        margin-bottom: 1;
        text-align: center;
        text-style: bold;
        color: $foreground;
    }

    Card .card--running {
        width: 100%;
        height: 1;
        text-align: center;
        color: $accent;
        text-style: bold;
    }

    /* Kept in the layout with nothing to say, so a card with a run behind it
       is not a different shape from the one next to it. */
    Card .card--running.-idle {
        visibility: hidden;
    }

    Card .card--description {
        width: 100%;
        height: 3;
        text-align: center;
        color: $text-muted;
    }

    Card .card--hotkey {
        width: 100%;
        height: 1;
        color: $text-disabled;
    }

    Card:focus .card--hotkey {
        color: $accent;
    }

    Card.-compact {
        height: 3;
        width: 100%;
        max-width: 100%;
        margin: 0 0 1 0;
        layout: horizontal;
    }

    Card.-compact .card--badge,
    Card.-compact .card--art-slot {
        display: none;
    }

    Card.-compact .card--name {
        width: 16;
        height: 1;
        margin-bottom: 0;
        text-align: left;
    }

    Card.-compact .card--description {
        width: 1fr;
        height: 1;
        margin: 0 2;
        text-align: left;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    Card.-compact .card--running {
        width: auto;
        margin-right: 2;
        text-align: right;
    }

    Card.-compact .card--hotkey {
        width: 4;
        text-align: right;
    }
    """

    class Selected(Message):
        def __init__(self, card: "Card") -> None:
            self.card = card
            super().__init__()

    class Focused(Message):
        def __init__(self, card: "Card") -> None:
            self.card = card
            super().__init__()

    def __init__(self, entry: MenuEntry, index: int) -> None:
        super().__init__(id=f"card-{index}")
        self.entry = entry
        self.index = index

    def compose(self) -> ComposeResult:
        yield Static(f"{self.index + 1:02d}", classes="card--badge")
        with Container(classes="card--art-slot"):
            yield Static(art_for(self.entry.key), classes="card--art")
        yield Static(self.entry.name, classes="card--name")
        yield Static(
            running_text(self.entry.running),
            classes=self._running_classes(self.entry.running),
        )
        yield Static(self.entry.description, classes="card--description")
        yield Static(f"[{self.index + 1}]", classes="card--hotkey", markup=False)

    def show_running(self, count: int) -> None:
        """Say what is going on behind this card, as it changes.

        Said once at compose time it would be a snapshot, and a card still
        offering to take you back into a run that has finished is worse than
        one that never mentioned it.
        """
        for line in self.query(".card--running").results(Static):
            line.update(running_text(count))
            line.set_class(not count, "-idle")

    @staticmethod
    def _running_classes(count: int) -> str:
        return "card--running" if count else "card--running -idle"

    def on_focus(self) -> None:
        self.post_message(self.Focused(self))

    def on_enter(self) -> None:
        self.focus()

    def on_click(self) -> None:
        self.focus()
        self.post_message(self.Selected(self))

    def action_select(self) -> None:
        self.post_message(self.Selected(self))
