"""Config form on the left, live terminal on the right.

Every flag is filled in before anything runs, so a workflow is not a sequence of
modal questions answered blind. Once it starts the form stays on screen as a
record of what was asked for, and the right pane narrates what is happening —
including any question the run turns out to need, answered in the same stdin box
a real terminal would use.

The screen is a *view*, not the owner of the run. Everything it shows lives on a
`RunSession`; the screen renders whichever session is selected and replays that
session's log when it attaches. That is what lets a run keep going after the
panel is left behind, and what lets the tab strip swap one run for another
without either of them noticing.

The one button carries the whole lifecycle — Run, then Stop while it works, then
Run again — so there is always something to press and never a state the user is
stuck in. It is the *only* button here: leaving is Esc, and the footer hint that
says so is itself the button for it, so the mouse reaches the exit without a
second control beside Run that has to be kept in step with it. Esc is the way
out rather than the way to stop: while work is running it detaches, leaving the
run going.

Both halves say what they want before being asked: a required field is marked on
its label, a line under the form names whatever is still missing, and an empty
terminal says it is empty rather than merely being blank. All three are knowable
without pressing anything, so none of them waits for a press that goes nowhere.
"""

from collections.abc import Sequence

from rich.segment import Segment
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.screen import Screen
from textual.selection import Selection
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, RichLog, Select, Static

from company_tui.domain.options import (
    Option,
    OptionKind,
    RefreshOutcome,
    OptionValue,
    missing_required,
)
from company_tui.presentation.branding import TOGGLE_ON
from company_tui.presentation.chrome import AppFooter, AppFrame, AppHeader, KeyHint
from company_tui.presentation.icons import TERMINAL_ART
from company_tui.presentation.screens import ConfirmScreen
from company_tui.presentation.path_screen import PathScreen
from company_tui.presentation.session import (
    MARKERS,
    TRAIL_SEPARATOR,
    RunSession,
    SessionRegistry,
)
from company_tui.presentation.session_tabs import (
    TAB_KEYS,
    NewSessionTab,
    SessionTab,
    SessionTabs,
)

STDIN_IDLE = "Waiting for process input…"
STDIN_ACTIVE = "Type a response, then Enter"

REQUIRED_MARK = " *"

EMPTY_TITLE = "Ready to scaffold"
EMPTY_HINT = "Configure the project, then press Ctrl+R."

NEEDED_MARK = "ⓘ  "
"""A terminal-safe circled information mark, kept to one cell so validation
copy stays aligned in terminals that substitute emoji fonts for warning signs."""

COPY_LABEL = "COPY"
COPIED_LABEL = "COPIED"
COPY_TOOLTIP = "Copy every line in this terminal. Ctrl+C copies a selection."
CLEAR_TOOLTIP = "Empty this terminal, back to the prompt the run started under."
COPIED_FOR = 1.4
"""How long COPY says it worked before going back to offering to.

Said on the button rather than in the terminal, because the terminal is the
thing that was just copied and a line announcing the copy would be one more line
the next copy carries. A clipboard write is an escape sequence the terminal
either honours or drops without answering, so this reports that the app sent it,
which is the whole of what the app knows."""


def needed_text(missing: Sequence[str]) -> str:
    """What the form still wants, named rather than counted.

    One field is the ordinary case and reads as a sentence; several read as a
    list, because a sentence naming four things is no longer a sentence.
    """
    if not missing:
        return ""
    if len(missing) == 1:
        return f"{NEEDED_MARK}Enter {missing[0].lower()} to continue."
    return f"{NEEDED_MARK}Still to fill in: {', '.join(missing)}."


class RunActionButton(Button):
    """Keep concise state labels while rendering stronger action copy."""

    def __init__(self, *args, action_name: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._action_name = action_name.upper()

    def render(self):
        state = str(self.label)
        if state == "Run":
            return f"❯  RUN {self._action_name}"
        if state == "Stop":
            return "■  STOP"
        if state == "Stopping":
            return "■  STOPPING…"
        if state == "Run again":
            return f"↻  RUN {self._action_name} AGAIN"
        return state.upper()


PREVIEW_ID = "will-run"
"""The row showing the command line the current answers add up to."""


class FieldToggle(Checkbox):
    """A checkbox that is only the box.

    Textual's is a mark and its label in one widget, which makes the text of a
    question part of the control that answers it. Here the label is a `Static`
    beside this, and this is the box on its own: one cell of mark inside a
    border, so a click has to land on the box to count and hover lights what
    the pointer is actually over.

    The side characters go because they are what makes the stock checkbox three
    cells wide. With a border of its own it does not need them, and one cell is
    what a mark inside a box wants to be.
    """

    BUTTON_LEFT = ""
    BUTTON_INNER = "✕"
    BUTTON_RIGHT = ""

    def render(self):
        """The mark when it is on, an empty box when it is not.

        Textual's own `render` pads the label a cell either side and assembles
        it with the button, which for an empty label is still two cells of
        padding — three cells of content in a box one cell wide, and what shows
        in it is the ellipsis of the overflow rather than the mark. It also
        draws the mark whether or not the box is on, in the colour of whatever
        is behind it, which is a mark that has to be hidden rather than not
        drawn. Off is nothing in the box.
        """
        return self._button if self.value else Content("")


class SelectableLog(RichLog):
    """The run's output, with the pointer able to pick text out of it.

    Textual selects by reading a per-cell offset off whatever a widget drew and
    handing that widget back a range in its own coordinates. `RichLog` writes
    neither: it keeps finished `Strip`s and paints them, so a drag across one
    reports no offsets at all. The screen reads that as "select the whole
    widget" and the whole widget then answers with nothing, because the
    inherited `get_selection` looks for a renderable a log does not have — which
    is why the terminal was the one pane here that could not be copied out of.

    Both halves are supplied. `render_line` stamps each cell with where in the
    log it came from and paints whatever is selected; `get_selection` reads the
    text back off the same strips. That reading is the wrapped line as it
    appears on screen, which is the point — this is the mouse taking what it is
    pointing at. `RunSession.transcript` is the other reading, every line at its
    own length, and that is what COPY sends.
    """

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        index = scroll_y + y
        strip = super().render_line(y)
        selection = self.text_selection
        if selection is not None and 0 <= index < len(self.lines):
            span = selection.get_span(index)
            if span is not None:
                start, end = span
                if end == -1:
                    end = len(self.lines[index].text)
                strip = self._highlight(strip, start - scroll_x, end - scroll_x)
        # The offsets go on last, over the highlight rather than under it: they
        # are what the next drag reads, and a strip rebuilt after them carries
        # none.
        return strip.apply_offsets(scroll_x, index)

    def _highlight(self, strip: Strip, start: int, end: int) -> Strip:
        """Paint `start`-`end` of an already-cropped line as selected.

        Over the line's own colours rather than under them. `Strip.apply_style`
        puts a style underneath, where every cell the log has already coloured
        wins and the selection changes nothing — which is what a log full of
        marker colours is. `post_style` is the same combination the other way
        round.

        Partial, so what arrives is a background and nothing else. The whole
        style resolves its unset foreground against what is behind it, and this
        theme leaves that foreground unset: it comes back as the selection
        colour written over itself, one block of flat colour with the line
        inside it invisible.
        """
        width = strip.cell_length
        start = max(0, min(start, width))
        end = max(start, min(end, width))
        if start == end:
            return strip
        style = self.screen.get_component_rich_style("screen--selection", partial=True)
        before, selected, after = strip.divide([start, end, width])
        painted = Strip(
            Segment.apply_style(selected, post_style=style), selected.cell_length
        )
        return Strip.join([before, painted, after])

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = "\n".join(strip.text.rstrip() for strip in self.lines)
        return selection.extract(text), "\n"


class VisualStatic(Static):
    """Expose stable semantic copy while painting reference-specific copy."""

    def __init__(self, content: str, *, visual: str, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._visual = visual

    def render(self):
        return self._visual


class DisplayKeyHint(KeyHint):
    """A key hint whose spoken/tested label can differ from its painted copy."""

    def __init__(
        self,
        key: str,
        label: str,
        *,
        display_key: str,
        display_label: str,
        **kwargs,
    ) -> None:
        super().__init__(key, label, **kwargs)
        self._display_key = display_key
        self._display_label = display_label

    def compose(self) -> ComposeResult:
        yield VisualStatic(
            self._key, visual=self._display_key, classes="hint--key"
        )
        yield VisualStatic(
            self._label, visual=self._display_label, classes="hint--label"
        )


class RunScreen(Screen[None]):
    BINDINGS = [
        ("escape", "back_or_close", "Back"),
        ("ctrl+r", "primary", "Run"),
        ("ctrl+t", "new_session", "New run"),
        ("ctrl+w", "close_session", "Close run"),
        ("ctrl+pageup", "previous_session", "Previous run"),
        ("ctrl+pagedown", "next_session", "Next run"),
        ("f2", "rename_session", "Rename run"),
    ]

    NARROW_WIDTH = 82

    # Esc means something different at each stage, and a footer that says
    # otherwise is worse than no footer at all.
    HINTS_READY = (("Tab", "Switch field"), ("Ctrl+R", "Run"), ("Esc", "Back"))
    HINTS_RUNNING = (("Ctrl+R", "Stop"), ("Esc", "Leave running"))
    HINTS_DONE = (("Ctrl+R", "Run again"), ("Esc", "Close"))

    MARKERS = MARKERS

    DEFAULT_CSS = """
    RunScreen {
        align: center middle;
        background: $background;
    }

    RunScreen #panes {
        width: 100%;
        height: 1fr;
        padding: 1 2 0 2;
    }

    RunScreen #config {
        width: 38%;
        min-width: 30;
        height: 100%;
        border: round $primary-lighten-1;
        border-title-color: $accent;
        border-title-style: bold;
        padding: 1 2;
        margin-right: 1;
    }

    RunScreen #fields {
        width: 100%;
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    RunScreen #terminal-pane {
        width: 1fr;
        height: 100%;
        border: round $primary-lighten-1;
        border-title-color: $accent;
        border-title-style: bold;
    }

    RunScreen #tabs-stack {
        width: 100%;
        height: 2;
        layers: rule tabs;
    }

    RunScreen #tabs-rule {
        dock: bottom;
        layer: rule;
        width: 100%;
        height: 1;
        border-top: solid $primary-lighten-1;
    }

    RunScreen #tabs {
        layer: tabs;
    }

    RunScreen #tab-keys {
        width: 100%;
        height: 2;
        margin-top: 1;
        padding: 0 1;
        border-bottom: solid $primary-lighten-1;
    }

    RunScreen #tab-keys KeyHint {
        margin-right: 3;
    }

    RunScreen #tab-keys KeyHint .hint--key {
        color: $accent;
        text-style: bold;
    }

    RunScreen #tab-keys KeyHint .hint--label {
        color: $text-muted;
    }

    RunScreen #terminal-body {
        width: 100%;
        height: 1fr;
        layers: output guide;
    }

    RunScreen #terminal {
        layer: output;
        width: 100%;
        height: 100%;
        padding: 0 1;
        background: transparent;
        overflow-x: hidden;
        scrollbar-size-vertical: 1;
    }

    /* Over the log rather than instead of it. The log has to keep its real
       width whatever is on top, because that width is what every line it is
       given gets wrapped to — hidden, it wraps them all to nothing.

       Held off the first row on purpose: the prompt line there is the only
       place the panel says which stack this tab belongs to, and with a tab per
       context that is the one thing a blank terminal must not cover. */
    /* Said here rather than left to a framework default that resolves its
       foreground against the background it is about to paint — which comes
       back as one flat block with the line inside it invisible. A background
       and nothing else, so the markers keep their colours: which line failed
       is the thing somebody copying a run out of here is after. */
    RunScreen > .screen--selection {
        background: $primary;
    }

    RunScreen #terminal-empty {
        layer: guide;
        width: 100%;
        height: 1fr;
        margin-top: 2;
        align: center middle;
        background: transparent;
        display: none;
    }

    RunScreen.-empty #terminal-empty {
        display: block;
    }

    /* Full width and centred text, not `width: auto`. `align` on the parent
       centres the children as one block, so auto-width leaves each line flush
       with the left edge of the widest one — which put the art out at the start
       of the hint rather than over the middle of it. */
    RunScreen #terminal-art {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        text-align: center;
        color: $accent;
    }

    RunScreen #terminal-title {
        width: 100%;
        height: 1;
        text-align: center;
        color: $foreground;
        text-style: bold;
    }

    RunScreen #terminal-hint {
        width: 100%;
        height: 1;
        text-align: center;
        color: $text-disabled;
    }

    RunScreen #terminal-input {
        width: 100%;
        height: 6;
        border-top: solid $primary-lighten-1;
        padding: 1 1 0 1;
    }

    RunScreen #stdin-row {
        border-top: none transparent;
        width: 100%;
        height: 3;
    }

    RunScreen.-asking #stdin-row {
        border-top: none $accent;
    }

    RunScreen #stdin-box {
        width: 1fr;
        height: 3;
        margin-right: 1;
        border: round $primary-lighten-1;
        background: transparent;
        align: left middle;
    }

    /* A run is actually waiting on an answer, so the row stops reading as
       furniture. Nothing else on the panel is asking the user for anything,
       and a question nobody notices is a run that has silently stopped. */
    RunScreen.-asking #stdin-box {
        border: round $accent;
    }

    RunScreen #stdin-label {
        width: 3;
        height: 1;
        content-align: center middle;
        color: $text-muted;
        text-style: bold;
    }

    RunScreen.-asking #stdin-label {
        color: $accent;
        text-style: bold;
    }

    RunScreen #stdin {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: transparent;
    }

    RunScreen.-asking #stdin {
        background: $panel;
    }

    /* Three of them share this row, so they share a width: a row of buttons
       that are each as wide as their own word reads as three unrelated
       controls. Nine cells is CLEAR with a cell either side of it, and it is
       what the box beside them can spare — the input is answering a yes/no or
       a name, not holding a paragraph. */
    RunScreen #stdin-send,
    RunScreen #terminal-copy,
    RunScreen #terminal-clear {
        width: 9;
        min-width: 9;
        height: 3;
        border: round $primary-lighten-1 !important;
        background: transparent;
        color: $foreground;
        text-style: bold;
        content-align: center middle;
    }

    RunScreen #terminal-copy,
    RunScreen #terminal-clear {
        margin-left: 1;
    }

    RunScreen #stdin-send:focus,
    RunScreen #terminal-copy:focus,
    RunScreen #terminal-clear:focus {
        border: round $accent !important;
        background: transparent;
        background-tint: 0%;
    }

    /* Send is disabled for most of a run's life — it only takes anything while
       something is actually asking — so dimming it would leave the row looking
       broken. These two are disabled only when the terminal is empty, which is
       a real "nothing to do here", and they say so. */
    RunScreen #stdin-send:disabled {
        opacity: 100%;
        color: $foreground;
    }

    RunScreen #terminal-copy:disabled,
    RunScreen #terminal-clear:disabled {
        opacity: 45%;
    }

    RunScreen #stdin-keys {
        width: 100%;
        height: 1;
    }

    RunScreen #stdin-keys KeyHint {
        margin-right: 2;
    }

    RunScreen #stdin-keys #stdin-newline-hint .hint--key {
        color: $accent;
        text-style: bold;
    }

    RunScreen #stdin-keys #stdin-newline-hint .hint--label {
        color: $text-muted;
    }

    RunScreen .section--title {
        width: 100%;
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        text-style: bold;
    }

    RunScreen .field--label {
        width: 100%;
        height: 1;
        color: $foreground;
    }

    RunScreen .field--help {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $text-disabled;
    }

    RunScreen .field--info {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        color: $secondary;
    }

    RunScreen .field--input {
        width: 100%;
        margin-bottom: 1;
        border: round $primary-lighten-1;
        background: transparent;
    }

    RunScreen .field--input:focus {
        border: round $primary-lighten-3;
    }

    /* The field keeps the row's width and the button takes what it needs, so a
       long path is still readable in the box that holds it. */
    RunScreen .field--path {
        width: 100%;
        height: auto;
    }

    RunScreen .field--path .field--input {
        width: 1fr;
        margin-bottom: 0;
    }

    /* A fetched list and its Update button. The list takes what is left after the
       button, which is the opposite of the default: a Select is width:100% and would
       push the button past the edge of the pane, where it is laid out and invisible. */
    RunScreen .field--fetched {
        width: 100%;
        height: auto;
    }

    RunScreen .field--fetched Select {
        width: 1fr;
        margin-bottom: 0;
    }

    RunScreen .field--browse {
        width: auto;
        min-width: 10;
        height: 3;
        margin-left: 1;
        border: round $primary-lighten-1 !important;
        background: transparent;
        color: $foreground;
    }

    /* Focus doubles the line and does nothing else, the same as the dialogs.
       Textual's `$button-focus-text-style` is `bold reverse`, and the reverse
       swaps the label's colours — a filled button by another route, whatever
       the background is set to. `!important` because `flat=True` puts a class
       on the button that outranks a plain two-type selector. */
    RunScreen .field--browse:hover,
    RunScreen .field--browse.-active,
    RunScreen .field--browse:focus,
    RunScreen #stdin-send:hover,
    RunScreen #stdin-send.-active,
    RunScreen #stdin-send:focus,
    RunScreen #terminal-copy:hover,
    RunScreen #terminal-copy.-active,
    RunScreen #terminal-copy:focus,
    RunScreen #terminal-clear:hover,
    RunScreen #terminal-clear.-active,
    RunScreen #terminal-clear:focus {
        background: transparent;
        background-tint: 0%;
        tint: $background 0%;
        text-style: bold !important;
    }

    RunScreen .field--browse:focus,
    RunScreen #stdin-send:focus,
    RunScreen #terminal-copy:focus,
    RunScreen #terminal-clear:focus {
        border: double $accent !important;
    }

    /* Only the box is the control. Textual's checkbox is a mark and its label
       in one widget, so the label takes the click, the hover and the focus
       along with the box — and in a form, a stray click on the text of a
       question answers it. The label is a `Static` beside this instead, so a
       click has to land on the box, and the box is the only thing that ever
       changes: doubled while it is on, and coloured for what is happening to
       it — gold under the keyboard, blue under the pointer, orange when it is on
       and neither. The label never moves. */
    RunScreen .field--toggle {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }

    RunScreen .field--toggle-label {
        width: 1fr;
        height: 3;
        margin-left: 1;
        content-align: left middle;
        color: $foreground;
    }

    /* Wider than the mark needs, because a terminal cell is about twice as tall
       as it is wide: a box three cells across and three rows down is drawn as a
       tall thin slot, not as a box. Five across is the mark with a cell either
       side of it, which is as close to square as an odd number of cells gets
       without the box starting to crowd the label. */
    RunScreen FieldToggle {
        width: 5;
        height: 3;
        padding: 0;
        content-align: center middle;
        border: round $primary-lighten-1;
        background: transparent;
    }

    /* The mark, and only the mark. Textual paints a background behind it —
       one cell of `$panel` inside a box that is otherwise the screen's own
       colour, which reads as a fill and is the one thing this design must not
       have. Every state has to say so: the `.-on` rules carry a class each, so
       a rule without one never reaches them. */
    RunScreen FieldToggle > .toggle--button {
        background: transparent;
        text-style: none;
    }

    RunScreen FieldToggle:hover {
        border: round $secondary;
    }

    RunScreen FieldToggle.-on:hover {
        border: double $secondary;
    }

    RunScreen FieldToggle.-on:hover > .toggle--button {
        background: transparent;
        color: $secondary;
    }

    /* Last, so that a box under the pointer *and* under the keyboard says
       keyboard: that is the one a key press is about to act on. */
    RunScreen FieldToggle:focus {
        border: round $accent;
        background-tint: 0%;
    }

    RunScreen FieldToggle.-on:focus {
        border: double $accent;
    }

    RunScreen FieldToggle.-on:focus > .toggle--button {
        background: transparent;
        color: $accent;
    }

    RunScreen Select {
        width: 100%;
        margin-bottom: 1;
    }

    /* What is still needed, said while there is still time to do something
       about it rather than only after a press that went nowhere. It is
       guidance until the user actually presses Run without it, and only then
       does it become a refusal. */
    /* The row is kept whether or not there is anything in it, so answering the
       last field does not shuffle the whole form up by a line. */
    RunScreen #validation {
        width: 100%;
        height: 2;
        min-height: 2;
        border-bottom: solid $primary-lighten-1;
        color: $warning;
    }

    RunScreen #validation.-refused {
        color: $error;
        text-style: bold;
    }

    /* The one button gets the whole width. Leaving the run is Esc — and the
       footer hint that says so is itself the button for it, so there is no
       second control here to keep in step with the first. */
    RunScreen #run {
        width: 100%;
        height: 3;
        margin-top: 1;
        border: none !important;
        background: $accent;
        color: $background;
        text-style: bold;
        content-align: center middle;
    }

    RunScreen #run:focus {
        text-style: bold;
        background-tint: 0%;
    }

    RunScreen #run:hover,
    RunScreen #run:focus {
        background: $accent-lighten-1;
        color: $background;
    }

    RunScreen.-narrow #panes {
        layout: vertical;
    }

    /* Stacked, the form takes what it needs while it is still being filled in. */
    RunScreen.-narrow #config {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }

    /* Once it starts, the form is a record of what was asked for and the
       terminal is the thing being read, so the room goes the other way — the
       fields scroll instead of pushing the output off the bottom and leaving
       the run with nowhere to say what it is doing. Sized to what has to fit
       rather than to a fraction: whatever else scrolls, the button that stops
       the run cannot be the part that scrolls away. */
    RunScreen.-narrow.-running #config {
        height: 11;
    }

    RunScreen.-narrow #terminal-pane {
        width: 100%;
        height: 1fr;
    }
    """ + f"""
    /* The one colour here that is not a theme token, and the only reason these
       two rules sit apart from the rest: `$toggle-on` cannot be a theme
       variable, because a widget's `DEFAULT_CSS` is parsed before any theme is
       active and the reference would be undefined at that point. Interpolated
       from `branding` so the colour still lives in one place — see `TOGGLE_ON`.

       Both carry one class, so the `:hover` and `:focus` rules above still win
       over them wherever they overlap. */
    RunScreen FieldToggle.-on {{
        border: double {TOGGLE_ON};
    }}

    RunScreen FieldToggle.-on > .toggle--button {{
        background: transparent;
        color: {TOGGLE_ON};
    }}
    """

    # ------------------------------------------------- what the panel reports

    class Chosen(Message):
        """The user picked a different tab."""

        def __init__(self, session: RunSession) -> None:
            self.session = session
            super().__init__()

    class Added(Message):
        """Another run, in the same context as the one on screen."""

    class Closed(Message):
        def __init__(self, session: RunSession) -> None:
            self.session = session
            super().__init__()

    class Renamed(Message):
        def __init__(self, session: RunSession) -> None:
            self.session = session
            super().__init__()

    class Detached(Message):
        """Leave the run going and give the screen back to the menu."""

    def __init__(
        self, session: RunSession, sessions: SessionRegistry | None = None
    ) -> None:
        super().__init__()
        self._session = session
        self._sessions = sessions if sessions is not None else SessionRegistry()
        self._was_finished = session.finished
        self._copied_for: Timer | None = None
        """Ticking while COPY is saying it worked, so a second press restarts
        the message rather than being cut short by the first one's timer."""
        self._refused = False
        """Whether Run has been pressed on this form and turned down.

        Kept here rather than left on the widget, because the panel re-renders
        whenever *any* session reports a change — so a run finishing in another
        tab would have quietly withdrawn the refusal standing in this one."""

    @property
    def session(self) -> RunSession:
        return self._session

    # --------------------------------------------------------------- composing

    def compose(self) -> ComposeResult:
        with AppFrame():
            yield AppHeader()
            with Horizontal(id="panes"):
                with Vertical(id="config") as config:
                    config.border_title = "CONFIGURATION"
                    # Scrolls, but the Run button stays put at the bottom so it
                    # is never something you have to scroll to find.
                    with VerticalScroll(id="fields"):
                        yield from self._form_widgets()
                    yield Static("", id="validation")
                    yield RunActionButton(
                        "Run",
                        action_name=self._session.base,
                        id="run",
                        variant="primary",
                        flat=True,
                    )
                with Vertical(id="terminal-pane") as pane:
                    pane.border_title = "TERMINAL"
                    with Container(id="tabs-stack"):
                        yield Static("", id="tabs-rule")
                        yield SessionTabs(id="tabs")
                    with Horizontal(id="tab-keys"):
                        for key, label, press in TAB_KEYS:
                            yield DisplayKeyHint(
                                key,
                                label,
                                display_key=key.replace("⌃", "Ctrl+"),
                                display_label=f"{label.title()} tab",
                                press=press,
                            )
                    with Container(id="terminal-body"):
                        yield SelectableLog(
                            id="terminal",
                            min_width=1,
                            wrap=True,
                            markup=True,
                            auto_scroll=True,
                        )
                        with Vertical(id="terminal-empty"):
                            yield Static(TERMINAL_ART, id="terminal-art")
                            yield Static(EMPTY_TITLE, id="terminal-title")
                            yield Static(EMPTY_HINT, id="terminal-hint")
                    with Vertical(id="terminal-input"):
                        with Horizontal(id="stdin-row"):
                            with Horizontal(id="stdin-box"):
                                yield Static("›", id="stdin-label")
                                yield Input(
                                    id="stdin", placeholder=STDIN_IDLE, disabled=True
                                )
                            yield Button(
                                "SEND", id="stdin-send", flat=True, disabled=True
                            )
                            # Beside Send rather than up by the tabs: these act
                            # on the terminal, and the terminal ends here.
                            yield Button(
                                COPY_LABEL,
                                id="terminal-copy",
                                flat=True,
                                disabled=True,
                                tooltip=COPY_TOOLTIP,
                            )
                            yield Button(
                                "CLEAR",
                                id="terminal-clear",
                                flat=True,
                                disabled=True,
                                tooltip=CLEAR_TOOLTIP,
                            )
                        with Horizontal(id="stdin-keys"):
                            yield KeyHint("Enter", "Send", dim=True, id="stdin-hint")
                            yield KeyHint(
                                "Ctrl+Enter",
                                "New line",
                                dim=True,
                                id="stdin-newline-hint",
                            )
            yield AppFooter(self.HINTS_READY)

    def _form_widgets(self) -> list[Widget]:
        """The whole config pane for the current session, as a flat list.

        Built rather than yielded through container context managers, because
        the same list has to be mountable into a pane that is already on screen
        when the user switches to another tab.
        """
        widgets: list[Widget] = [
            Static(self._session.title.upper(), classes="section--title")
        ]
        # What the command is for, under its name and above its fields - the
        # subheading the desktop form has always carried. Read from the document,
        # so it cannot drift from the summary the menu showed a moment ago.
        if self._session.subtitle:
            widgets.append(Static(self._session.subtitle, classes="field--help"))
        for option in self._session.options:
            widget_id = self._widget_id(option)

            if option.kind is OptionKind.INFO:
                widgets.append(Static(self._label(option), classes="field--label"))
                widgets.append(
                    Static(
                        option.render(self._session.values),
                        id=widget_id,
                        classes="field--info",
                    )
                )
                continue

            if option.kind is OptionKind.BOOLEAN:
                widgets.append(
                    Horizontal(
                        FieldToggle(value=bool(option.default), id=widget_id),
                        Static(option.label, classes="field--toggle-label"),
                        classes="field--toggle",
                    )
                )
                if option.help:
                    widgets.append(Static(option.help, classes="field--help"))
                continue

            widgets.append(Static(self._label(option), classes="field--label"))
            if option.kind is OptionKind.MULTI and option.choices:
                # One box per value, because the question is how many, not which.
                # The answer is read back off the boxes rather than kept beside
                # them: a value assembled from the widgets cannot disagree with
                # what the user can see is ticked.
                picked = self._picked(option)
                for index, choice in enumerate(option.choices):
                    widgets.append(
                        Horizontal(
                            FieldToggle(
                                value=choice in picked,
                                id=self._multi_id(option, index),
                            ),
                            Static(choice, classes="field--toggle-label"),
                            classes="field--toggle",
                        )
                    )
            elif option.kind is OptionKind.NUMBER:
                widgets.append(
                    Input(
                        value=str(self._session.values.get(option.key, "")),
                        type="number",
                        id=widget_id,
                        classes="field--input",
                    )
                )
            elif option.kind is OptionKind.CHOICE and option.choices:
                # Row zero NAMES the default and binds nothing, which is what
                # makes an untouched form run the command as if no argument had
                # been passed. A dropdown resting on a blank line lists what is
                # possible while saying nothing about what will happen, so the
                # row carries the default's name - as a label, never as a value.
                #
                # A stored value outside the option's own choices would raise
                # InvalidSelectValueError on mount and take the app down, so it
                # falls back to that row here as well as being dropped in
                # `session.load`. Two guards; nothing here is worth crashing over.
                stored = str(self._session.values.get(option.key, ""))
                chooser = Select(
                    [(choice, choice) for choice in option.choices],
                    value=stored if stored in option.choices else Select.NULL,
                    allow_blank=True,
                    prompt=f"(default: {option.default})" if option.default else "",
                    id=widget_id,
                )
                if option.refresh and self._session.refresh_runner is not None:
                    # Only on a list the command FETCHED, which is what carrying a
                    # refresh means. A declared set cannot change while the form is
                    # open, so a button there would never do anything.
                    #
                    # `field--fetched`, not `field--path`: that class shrinks a
                    # `.field--input` to make room for its button, and a Select is not
                    # one - so it kept its full width and pushed the button clean off
                    # the pane. The button was there, laid out, and never visible.
                    widgets.append(
                        Horizontal(
                            chooser,
                            Button(
                                option.refresh.label,
                                id=self._refresh_id(option),
                                classes="field--browse",
                                flat=True,
                            ),
                            classes="field--fetched",
                        )
                    )
                    # Under the row rather than beside the button: a third thing in
                    # that Horizontal is width the dropdown does not get.
                    widgets.append(
                        Static(
                            "", id=self._refresh_status_id(option), classes="field--help"
                        )
                    )
                else:
                    widgets.append(chooser)
            elif option.kind in (OptionKind.PATH, OptionKind.FILE):
                # Still typeable: browsing is the shortcut, not the only way in,
                # and a path pasted from somewhere else should not need a walk
                # through a tree to be accepted.
                widgets.append(
                    Horizontal(
                        Input(
                            value=str(self._session.values.get(option.key, "")),
                            id=widget_id,
                            classes="field--input",
                        ),
                        Button(
                            "Browse",
                            id=self._browse_id(option),
                            classes="field--browse",
                            flat=True,
                        ),
                        classes="field--path",
                    )
                )
            else:
                widgets.append(
                    Input(
                        value=str(self._session.values.get(option.key, "")),
                        id=widget_id,
                        classes="field--input",
                    )
                )
            if option.help:
                widgets.append(Static(option.help, classes="field--help"))

        # What the run will actually be, kept current as the form is filled in.
        # The form and the command line are the same thing, and this is the row
        # that says so: anything picked here once can be typed next time.
        if self._session.preview_runner is not None:
            widgets.append(Static("Will run", classes="field--label"))
            widgets.append(
                Static(
                    self._session.command_preview(),
                    id=PREVIEW_ID,
                    classes="field--info",
                )
            )
        return widgets

    @staticmethod
    def _label(option: Option) -> Content:
        """The field's name, saying up front whether it has to be answered.

        Marked here rather than reported later, so filling the form in is one
        pass down the pane instead of a press, a refusal, and a second pass.
        """
        if not option.required:
            return Content(option.label)
        return Content.assemble(option.label, (REQUIRED_MARK, "$accent"))

    @staticmethod
    def _widget_id(option: Option) -> str:
        return f"field-{option.key}"

    @staticmethod
    def _refresh_id(option: Option) -> str:
        return f"refresh-{option.key}"

    @staticmethod
    def _refresh_status_id(option: Option) -> str:
        return f"refreshed-{option.key}"

    async def _refresh(self, key: str) -> None:
        """Re-fetch one choice's values, asking first if acting would change something.

        The order is the whole point: preview, then confirm, then act. The refresh
        behind this button may delete things - the branch list is brought up to
        date by removing local branches whose remote is gone - and a button that
        did that on a single click would be a button nobody could safely press.
        An empty preview means there is nothing to ask about, so a refresh with
        nothing to remove costs no dialog.
        """
        option = self._option_named(key)
        runner = self._session.refresh_runner
        if option is None or option.refresh is None or runner is None:
            return

        button = self._one(self._refresh_id(option), Button)
        status = self._one(self._refresh_status_id(option), Static)
        idle = str(button.label) if button else option.refresh.label
        if button is not None:
            button.disabled = True
            button.label = "..."
        if status is not None:
            status.update("checking...")

        try:
            await self._ask_and_refresh(option, runner, status)
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            # The worker runs with exit_on_error=False, so an escape from here is
            # silence: the button springs back and nothing says why. That is the
            # same shape as the failure in docs/pitfalls.md 1.1.
            if status is not None:
                status.update(f"failed: {error}")
        finally:
            if button is not None:
                button.disabled = False
                button.label = idle

    async def _ask_and_refresh(self, option: Option, runner, status) -> None:
        """Preview, confirm if there is anything to confirm, then act.

        Everything it does is written into the terminal as well as onto the line
        beside the button. The line has room for four words; the terminal is
        where this run's history is, and a list that was brought up to date - or
        a delete that was declined - belongs in it beside the run it was done
        for.
        """
        asked = await runner(option, True)
        if asked.message:
            # The first line is the question; the rest is what saying yes
            # costs, which ConfirmScreen shows under it.
            head, _, rest = asked.message.partition("\n")
            detail = rest.strip()
            agreed = await self.app.push_screen_wait(
                ConfirmScreen(
                    head,
                    trail=self._session.title,
                    detail=detail,
                    confirm="UPDATE",
                )
            )
            if not agreed:
                if status is not None:
                    status.update("left alone")
                self._session.write(f"-{option.key}: left alone", marker="warn")
                return
        if status is not None:
            status.update("fetching...")
        self._session.write(f"Updating -{option.key}...", marker="step")

        outcome = await runner(option, False)
        self._apply_refresh(option, outcome)

        said = outcome.message or f"{len(outcome.choices)} value(s)"
        if status is not None:
            status.update(said if outcome.ok else outcome.message or "failed")
        self._session.write(said, marker="ok" if outcome.ok else "error")
        if outcome.ok and outcome.choices:
            self._session.write(
                f"-{option.key} now offers: {', '.join(outcome.choices)}",
                marker="output",
            )

    def _apply_refresh(self, option: Option, outcome: RefreshOutcome) -> None:
        """Put the new values on the dropdown, keeping the selection if it survived.

        An empty list is IGNORED. A refresh that failed, or that a network could
        not answer, must not be the thing that empties a field the user had
        already answered.
        """
        if not outcome.choices:
            return
        chooser = self._one(self._widget_id(option), Select)
        if chooser is None:
            return
        was = str(chooser.value) if chooser.value is not Select.NULL else ""
        chooser.set_options((choice, choice) for choice in outcome.choices)
        chooser.value = was if was in outcome.choices else outcome.choices[0]
        self._store(self._widget_id(option), str(chooser.value))

    def _one(self, widget_id: str, kind):
        for widget in self.query(f"#{widget_id}"):
            if isinstance(widget, kind):
                return widget
        return None

    @staticmethod
    def _multi_id(option: Option, index: int) -> str:
        """One box's id. Indexed rather than named after the value it carries -
        a choice read off a disk can hold anything, and a Textual id may not."""
        return f"multi-{option.key}-{index}"

    @staticmethod
    def _multi_key(widget_id: str | None) -> str | None:
        if not widget_id or not widget_id.startswith("multi-"):
            return None
        return widget_id.removeprefix("multi-").rsplit("-", 1)[0]

    def _option_named(self, key: str) -> Option | None:
        return next((o for o in self._session.options if o.key == key), None)

    def _picked(self, option: Option) -> set[str]:
        """What this option's stored answer says is ticked."""
        stored = str(self._session.values.get(option.key, ""))
        return {part.strip() for part in stored.split(",") if part.strip()}

    def _multi_value(self, key: str) -> str:
        """The ticked values, comma-joined, in the order the document declared.

        Comma-joined rather than a list because that is what a command line
        already reads a list in, and what the dispatcher on the other side
        splits back out - one shape crossing the boundary instead of two.
        """
        option = self._option_named(key)
        if option is None:
            return ""
        chosen = []
        for index, choice in enumerate(option.choices):
            for box in self.query(f"#{self._multi_id(option, index)}"):
                if box.value:
                    chosen.append(choice)
        return ",".join(chosen)

    @staticmethod
    def _browse_id(option: Option) -> str:
        return f"browse-{option.key}"

    # ----------------------------------------------------------------- layout

    def on_mount(self) -> None:
        self._apply_density(self.size.width)
        self._session.watch(self._echo, self.render_state)
        self.render_state()
        self._replay_terminal()
        self._focus_first_field()

    @property
    def _composed(self) -> bool:
        """Whether there are widgets here yet to say anything to.

        Deliberately not `is_mounted`: a `Screen` still reports that as `False`
        inside its own `on_mount`, even though its children are already there —
        so guarding on it skipped the whole first render, which is how the tab
        strip came up empty and stayed that way. The other end — a screen being
        taken apart while a run still holds a reference to it — is handled by
        rendering through `query` rather than `query_one`, so a widget that has
        already gone is nothing to say rather than an exception.
        """
        return bool(self.children)

    def on_unmount(self) -> None:
        # Whatever the run writes next belongs in its buffer, not to a screen
        # that is on its way out.
        self._session.watch(None, None)

    def _focus_first_field(self) -> None:
        for widget in self.query(Input):
            if widget.id != "stdin":
                widget.focus()
                return

    def on_resize(self, event: events.Resize) -> None:
        self._apply_density(event.size.width)
        self.call_after_refresh(self._replay_terminal)

    def _apply_density(self, width: int) -> None:
        self.set_class(width < self.NARROW_WIDTH, "-narrow")

    # ---------------------------------------------------------------- the view

    def show(self, session: RunSession) -> None:
        """Render another session here, form, log and all."""
        if session is self._session:
            self.render_state()
            return
        self._session.watch(None, None)
        self._session = session
        self._was_finished = session.finished
        self._refused = False
        session.watch(self._echo, self.render_state)
        if self._composed:
            self._swap_form()

    @work(exclusive=True, group="run-screen-form")
    async def _swap_form(self) -> None:
        # Removal is awaited before the new fields go in: the two sets share
        # widget ids, and mounting over the top of the old ones is a clash.
        fields = self.query_one("#fields", VerticalScroll)
        await fields.remove_children()
        await fields.mount_all(self._form_widgets())
        self.render_state()
        self._replay_terminal()
        self._focus_first_field()

    def render_state(self) -> None:
        """Say what the session is doing, in every part of the panel that shows it."""
        if not self._composed:
            return
        session = self._session
        asking = session.answer is not None and not session.answer.done()
        self.set_class(session.started, "-running")
        self.set_class(asking, "-asking")
        self._set_fields_disabled(session.started)
        self._set_button(*self._button_state())
        self._show_hints(self._hints())
        self._show_stdin(asking)
        self._show_tabs()
        self._show_needed()
        self._show_empty()
        # The moment a run ends, the one thing left to decide is whether to do
        # it again — so that is what the keyboard is already on. Once only:
        # every later line the run prints must not steal the focus back.
        if session.finished and not self._was_finished:
            for button in self.query("#run").results(Button):
                button.focus()
        self._was_finished = session.finished

    def _button_state(self) -> tuple[str, str, bool]:
        session = self._session
        if session.finished:
            return ("Run again", "primary", False)
        if session.stop_requested:
            return ("Stopping", "error", True)
        if session.started:
            return ("Stop", "error", False)
        return ("Run", "primary", False)

    def _missing(self) -> tuple[str, ...]:
        session = self._session
        if session.started:
            # The form is a record of what was asked for now, not something
            # still being filled in, so it has nothing left to ask for.
            return ()
        return missing_required(session.options, session.values)

    def _show_needed(self) -> None:
        """Say what the form is still missing, if anything."""
        missing = self._missing()
        for line in self.query("#validation").results(Static):
            line.update(needed_text(missing))
            line.set_class(self._refused and bool(missing), "-refused")

    def _show_empty(self) -> None:
        """Whether this tab has anything in it but the prompt it opened with."""
        if not self._composed:
            return
        empty = len(self._session.log) <= 1
        self.set_class(empty, "-empty")
        # Nothing to take a copy of and nothing to clear away. Both say so
        # rather than waiting for a press that would go nowhere, which is the
        # same rule the Run button and the validation line already follow.
        for button in self.query("#terminal-copy, #terminal-clear").results(Button):
            button.disabled = empty

    def _hints(self) -> Sequence[tuple[str, str]]:
        if self._session.finished:
            return self.HINTS_DONE
        return self.HINTS_RUNNING if self._session.started else self.HINTS_READY

    def _show_stdin(self, asking: bool) -> None:
        for box in self.query("#stdin").results(Input):
            box.disabled = not asking
            box.placeholder = STDIN_ACTIVE if asking else STDIN_IDLE
            if asking and not box.has_focus:
                box.focus()
            elif not asking:
                box.value = ""
        # Enter only sends while there is a question to answer. Offered the rest
        # of the time it would fire into whatever holds the focus instead.
        for hint in self.query("#stdin-hint").results(KeyHint):
            hint.pressable = asking
        for hint in self.query("#stdin-newline-hint").results(KeyHint):
            hint.pressable = False
        for button in self.query("#stdin-send").results(Button):
            button.disabled = not asking

    def _show_tabs(self) -> None:
        shown = self._sessions.visible(self._session.scope)
        if self._session not in shown:
            # A session on screen before its form has opened is not a tab yet,
            # but it is the one being looked at, so it goes in the strip rather
            # than the strip briefly showing everything except it.
            shown = (*shown, self._session)
        for strip in self.query("#tabs").results(SessionTabs):
            strip.show(shown, self._session)

    def _set_button(self, label: str, variant: str, disabled: bool = False) -> None:
        for button in self.query("#run").results(Button):
            button.label = label
            button.variant = variant
            button.disabled = disabled

    def _show_hints(self, hints: Sequence[tuple[str, str]]) -> None:
        for footer in self.query(AppFooter):
            footer.show_hints(hints)

    def _set_fields_disabled(self, disabled: bool) -> None:
        for widget in self.query(Input):
            if widget.id != "stdin":
                widget.disabled = disabled
        for widget in self.query(Checkbox):
            widget.disabled = disabled
        for widget in self.query(Select):
            widget.disabled = disabled
        for widget in self.query(".field--browse"):
            widget.disabled = disabled

    # ------------------------------------------------------------ form values

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "stdin":
            self._store(event.input.id, event.value)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = self._multi_key(event.checkbox.id)
        if key is not None:
            # Every box of this option, not just the one that moved: the answer
            # is the set, and storing one box's value would store a boolean where
            # a list belongs.
            self._store(f"field-{key}", self._multi_value(key))
            return
        self._store(event.checkbox.id, event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        # The blank row is "leave it out", so it stores nothing rather than the
        # words on it - reading that row back would pass "(default: development)"
        # as a branch name.
        #
        # Select.NULL, NOT Select.BLANK. In this Textual, BLANK is literally
        # `False`, so `is Select.BLANK` never matches an unselected Select and the
        # label would have been stored as the answer. NULL is the sentinel the
        # widget actually holds and the one the constructor accepts.
        blank = event.value is Select.NULL
        self._store(event.select.id, "" if blank else str(event.value))

    def _store(self, widget_id: str | None, value: OptionValue) -> None:
        if not widget_id or not widget_id.startswith("field-"):
            return
        self._session.store(widget_id.removeprefix("field-"), value)
        # Answering the thing that was refused is the end of the refusal; it
        # goes back to being guidance about whatever is still outstanding.
        self._refused = False
        self._show_needed()
        for option in self._session.options:
            if option.kind is OptionKind.INFO and option.template:
                for row in self.query(f"#{self._widget_id(option)}"):
                    row.update(option.render(self._session.values))
        for row in self.query(f"#{PREVIEW_ID}"):
            row.update(self._session.command_preview())

    # -------------------------------------------------------------------- run

    async def wait_for_values(self) -> dict[str, OptionValue] | None:
        return await self._session.wait_for_values()

    async def wait_for_next(self) -> bool:
        return await self._session.wait_for_next()

    def reset(self) -> None:
        self._session.reset()
        self._refused = False
        self.render_state()
        self._focus_first_field()

    def track(self, task: object) -> None:
        """Adopt the running work, so Stop has something to cancel."""
        self._session.work = task  # type: ignore[assignment]

    def untrack(self) -> None:
        self._session.work = None

    @property
    def stop_requested(self) -> bool:
        return self._session.stop_requested

    @property
    def failure(self) -> str:
        """Why the work broke, or `""` if it did not."""
        return self._session.failure

    def report_failure(self, error: BaseException) -> str:
        return self._session.report_failure(error)

    def finish(self, message: str, ok: bool = True) -> None:
        self._session.finish(message, ok)
        self.render_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self.action_primary()
        elif event.button.id == "stdin-send":
            self._submit_stdin()
        elif event.button.id == "terminal-copy":
            self._copy_terminal()
        elif event.button.id == "terminal-clear":
            self._clear_terminal()
        elif event.button.id and event.button.id.startswith("browse-"):
            self._browse(event.button.id.removeprefix("browse-"))
        elif event.button.id and event.button.id.startswith("refresh-"):
            # As a worker, because it asks a question and runs a subprocess: a
            # handler that awaited either would hold the interface while it did.
            self.run_worker(
                self._refresh(event.button.id.removeprefix("refresh-")),
                group="refresh",
                exit_on_error=False,
            )

    # ---------------------------------------------------------- the terminal

    def _copy_terminal(self) -> None:
        """Put the whole transcript on the clipboard.

        The whole of it rather than whatever is selected, and deliberately: a
        press is a click, a click is what ends a drag, and the screen has
        already dropped the selection by the time this runs. Selected text has
        its own answer — Ctrl+C, which the screen answers before the app's own
        binding for that key gets it — so this button is the other question,
        which is "give me all of it".
        """
        transcript = self._session.transcript()
        if not transcript:
            return
        self.app.copy_to_clipboard(transcript)
        self._say_copied()

    def _say_copied(self) -> None:
        self._set_copy_label(COPIED_LABEL)
        if self._copied_for is not None:
            self._copied_for.stop()
        self._copied_for = self.set_timer(COPIED_FOR, self._offer_copy_again)

    def _offer_copy_again(self) -> None:
        self._copied_for = None
        self._set_copy_label(COPY_LABEL)

    def _set_copy_label(self, label: str) -> None:
        for button in self.query("#terminal-copy").results(Button):
            button.label = label

    def _clear_terminal(self) -> None:
        """Empty this tab's log, and the view of it, back to its prompt.

        The session is cleared rather than the widget, because the widget is a
        view: clearing only what is drawn would leave every line still held,
        still written down at the next save, and back on screen the moment the
        user switched tabs and switched back.
        """
        self.clear_selection()
        self._session.clear_log()
        self._replay_terminal()

    def _browse(self, key: str) -> None:
        """Fill a path field from the tree, starting where the field points.

        The chosen path goes back through the field rather than straight into
        the values, so it is stored, echoed, and picked up by the rows that
        restate it exactly as if it had been typed.
        """
        field = self.query_one(f"#field-{key}", Input)
        option = self._option_named(key)
        # A file field browses for a file. Offering a directory tree with the files
        # hidden to somebody looking for a manifest is offering them nothing - which
        # is the difference the desktop form draws with "Choose file..." against
        # "Choose folder...".
        wants_file = option is not None and option.kind is OptionKind.FILE

        def chosen(path: str | None) -> None:
            if path:
                field.value = path
            field.focus()

        self.app.push_screen(
            PathScreen(
                field.value,
                "Choose a file" if wants_file else "Choose a directory",
                files=wants_file,
            ),
            chosen,
        )

    def action_primary(self) -> None:
        """Whatever the one button says right now."""
        if self._session.finished:
            self._session.decide(again=True)
        elif self._session.started:
            self.action_stop()
        else:
            self.action_run()

    def action_run(self) -> None:
        session = self._session
        if session.started:
            return
        if self._missing():
            # The same line that has been offering guidance all along, now
            # saying no — and the cursor put on the first thing it names, so
            # the answer to "what do I do about it" is already under the hands.
            self._refused = True
            self._show_needed()
            self._focus_missing()
            return
        session.start()
        self.render_state()

    def _focus_missing(self) -> None:
        missing = set(self._missing())
        for option in self._session.options:
            if option.label in missing:
                for widget in self.query(f"#{self._widget_id(option)}"):
                    widget.focus()
                return

    def action_stop(self) -> None:
        self._session.request_stop()
        self.render_state()

    def action_back_or_close(self) -> None:
        if self._session.finished:
            self._session.decide(again=False)
        elif self._session.started:
            # The run is the user's, and so is walking away from it. Stop is on
            # the button; Esc leaves the work going and hands the screen back.
            self.post_message(self.Detached())
        else:
            self._session.cancel()

    # --------------------------------------------------------------- the tabs

    def action_new_session(self) -> None:
        self.post_message(self.Added())

    def action_close_session(self) -> None:
        self.post_message(self.Closed(self._session))

    def action_rename_session(self) -> None:
        self.post_message(self.Renamed(self._session))

    def action_previous_session(self) -> None:
        self._step_session(-1)

    def action_next_session(self) -> None:
        self._step_session(1)

    def _step_session(self, delta: int) -> None:
        shown = self._sessions.visible(self._session.scope)
        if len(shown) < 2 or self._session not in shown:
            return
        index = (shown.index(self._session) + delta) % len(shown)
        self.post_message(self.Chosen(shown[index]))

    def on_session_tab_chosen(self, message: SessionTab.Chosen) -> None:
        message.stop()
        if message.session is not self._session:
            self.post_message(self.Chosen(message.session))

    def on_session_tab_closed(self, message: SessionTab.Closed) -> None:
        message.stop()
        self.post_message(self.Closed(message.session))

    def on_new_session_tab_pressed(self, message: NewSessionTab.Pressed) -> None:
        message.stop()
        self.post_message(self.Added())

    # ------------------------------------------------- what the workflow says

    def write(self, message: str, marker: str = "plain") -> None:
        self._session.write(message, marker)

    def _echo(self, content: Content) -> None:
        """A line arriving for the session currently on screen."""
        if self._composed:
            self._write_terminal_content(content)
            self._show_empty()

    def _write_terminal_content(self, content: Content) -> None:
        for terminal in self.query("#terminal").results(RichLog):
            width = max(terminal.scrollable_content_region.width, 2)
            for line in content.wrap(width, overflow="fold"):
                terminal.write(line, width=width)

    def _replay_terminal(self) -> None:
        if not self._composed:
            return
        for terminal in self.query("#terminal").results(RichLog):
            terminal.clear()
        for content in list(self._session.log):
            self._write_terminal_content(content)
        self._show_empty()

    async def prompt(self, question: str) -> str:
        """Ask in the terminal pane; wait for the stdin box, like a real shell."""
        return await self._session.prompt(question)

    def _submit_stdin(self, value: str | None = None) -> None:
        answer = self._session.answer
        if answer is None or answer.done():
            return
        box = self.query_one("#stdin", Input)
        self._session.reply((box.value if value is None else value).strip())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "stdin":
            return
        event.stop()
        self._submit_stdin(event.value)


__all__ = [
    "TRAIL_SEPARATOR",
    "STDIN_ACTIVE",
    "STDIN_IDLE",
    "REQUIRED_MARK",
    "EMPTY_TITLE",
    "needed_text",
    "RunScreen",
]
