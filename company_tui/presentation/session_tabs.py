"""The strip of tabs above the terminal, one per run of this context.

Tabs read the way terminal tabs do: the one on screen is lit and the rest say
what they are up to with a glyph. Each carries its own close mark, and the strip
scrolls, so ten runs are ten reachable tabs rather than three tabs and a guess.

Only this context's runs are here. A run started from another stack is in that
stack's strip, and what says so is the count on the menu card leading back to it
(`SessionRegistry.running_under`), the running total in the chrome, and `Ctrl+B`.

The strip only reports; the console decides. Every gesture leaves here as a
message so that adding, closing and renaming stay one decision made in one
place, next to the tasks they affect.
"""

from collections.abc import Sequence

from textual import events
from textual.containers import Horizontal, HorizontalScroll
from textual.message import Message
from textual.widgets import Static

from company_tui.presentation.chrome import HoverLight
from company_tui.presentation.session import RunSession

CLOSE_MARK = "✕"

TAB_KEYS = (
    ("⌃T", "new", "ctrl+t"),
    ("⌃W", "close", "ctrl+w"),
    ("F2", "rename", "f2"),
)
"""The keys that act on the strip, shown at the foot of the pane rather than in
the strip. Each says which key it stands for, since a glyph is not a key name."""

TAB_SCROLL_STEP = 8
"""Columns per wheel notch — about a short tab, so one notch moves the strip by
something you can follow rather than by a character or by the whole width."""


class SessionTab(HoverLight, Horizontal):
    """One run, named, badged with what it is doing, and closable on its own."""

    DEFAULT_CSS = """
    SessionTab {
        width: auto;
        height: 1;
        margin-right: 2;
        pointer: pointer;
    }

    SessionTab .tab--label {
        width: auto;
        height: 1;
        color: $text-muted;
    }

    SessionTab .tab--close {
        width: auto;
        height: 1;
        margin-left: 1;
        color: $text-disabled;
    }

    SessionTab.-hovered .tab--label {
        color: $foreground;
    }

    SessionTab .tab--close:hover {
        color: $error;
        text-style: bold;
    }

    SessionTab.-active .tab--label {
        color: $accent;
        text-style: bold;
    }

    SessionTab.-asking .tab--label {
        color: $warning;
    }

    SessionTab.-failed .tab--label {
        color: $error;
    }
    """

    class Chosen(Message):
        def __init__(self, session: RunSession) -> None:
            self.session = session
            super().__init__()

    class Closed(Message):
        def __init__(self, session: RunSession) -> None:
            self.session = session
            super().__init__()

    def __init__(self, session: RunSession, active: bool) -> None:
        classes = [f"-{session.status.value}"]
        if active:
            classes.append("-active")
        super().__init__(classes=" ".join(classes))
        self.session = session

    def compose(self):
        yield Static(
            f"{self.session.status.glyph} {self.session.name}", classes="tab--label"
        )
        yield Static(CLOSE_MARK, classes="tab--close")

    def on_click(self, event: events.Click) -> None:
        event.stop()
        widget = event.widget
        if widget is not None and widget.has_class("tab--close"):
            self.post_message(self.Closed(self.session))
        else:
            self.post_message(self.Chosen(self.session))


class NewSessionTab(Static):
    """Another run in this context, one press away.

    Held away from the last tab rather than following it at the same spacing:
    it is a control among names, and a click meant for a tab's close mark that
    lands here starts a run instead of ending one.
    """

    DEFAULT_CSS = """
    NewSessionTab {
        width: auto;
        height: 1;
        margin: 0 2 0 2;
        color: $text-disabled;
        pointer: pointer;
    }

    NewSessionTab:hover {
        color: $accent;
        text-style: bold;
    }
    """

    class Pressed(Message):
        pass

    def __init__(self) -> None:
        super().__init__("+")

    def on_click(self) -> None:
        self.post_message(self.Pressed())


class SessionTabs(HorizontalScroll):
    """The strip itself, rebuilt from the registry whenever anything changes.

    The whole width is the tabs'. The keys that act on them live at the foot of
    the pane instead, because anything sharing this row is width the tabs do not
    get — and tabs are the one thing here that has no fixed size.
    """

    DEFAULT_CSS = """
    /* Two rows, not one: the border takes a row of its own, and a strip sized
       to the border alone has nowhere left to put the tabs. The scrollbar is
       hidden because it would take the other one — the active tab scrolls
       itself into view instead, and the wheel scrolls the rest. */
    SessionTabs {
        width: 100%;
        height: 2;
        padding: 0 1;
        border-bottom: solid $primary-lighten-1;
        overflow-x: auto;
        overflow-y: hidden;
        scrollbar-size-horizontal: 0;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._shown: tuple = ()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """A strip one row tall has nowhere to go but sideways.

        Textual sends the wheel to the vertical axis unless a modifier is held,
        and there is no vertical axis here — so without this the wheel does
        nothing over the one thing on screen that most looks like it takes one.
        """
        self._wheel(event, 1)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._wheel(event, -1)

    def _wheel(self, event: events.MouseEvent, direction: int) -> None:
        if not self.max_scroll_x:
            return
        event.stop()
        self.scroll_to(x=self.scroll_x + direction * TAB_SCROLL_STEP, animate=False)

    def show(self, sessions: Sequence[RunSession], active: RunSession) -> None:
        # Rebuilt only when it would come out different. The panel re-renders on
        # every state change a run reports, and tearing the strip down that
        # often costs more than the strip does.
        signature = tuple((id(s), s.name, s.status, s is active) for s in sessions)
        if signature == self._shown:
            return
        self._shown = signature

        # Rebuilt in one go, on the message pump, rather than in a worker that
        # awaits the removal: a worker can be cancelled by the next rebuild
        # halfway through mounting, and a half-mounted subtree leaves the app
        # waiting forever for messages that will never be processed.
        self.remove_children()
        tabs: list[Static] = [
            SessionTab(session, session is active) for session in sessions
        ]
        tabs.append(NewSessionTab())
        self.mount_all(tabs)
        for tab in tabs:
            if isinstance(tab, SessionTab) and tab.session is active:
                self.call_after_refresh(tab.scroll_visible, animate=False)
