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
Close — so there is always something to press and never a state the user is
stuck in. Esc is the way out rather than the way to stop: while work is running
it detaches, leaving the run going.

Both halves say what they want before being asked: a required field is marked on
its label, a line under the form names whatever is still missing, and an empty
terminal says it is empty rather than merely being blank. All three are knowable
without pressing anything, so none of them waits for a press that goes nowhere.
"""

from collections.abc import Sequence

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, RichLog, Select, Static

from company_tui.domain.options import (
    Option,
    OptionKind,
    OptionValue,
    missing_required,
)
from company_tui.presentation.chrome import AppFooter, AppFrame, AppHeader, KeyHint
from company_tui.presentation.icons import TERMINAL_ART
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

STDIN_IDLE = "Waiting — nothing is asking for input yet"
STDIN_ACTIVE = "Type a response, then Enter"

REQUIRED_MARK = " *"

EMPTY_TITLE = "Nothing has run here yet"
EMPTY_HINT = "Fill in the form, then press Ctrl+R."

NEEDED_MARK = "▲ "
"""A triangle rather than a warning sign, a stopwatch or a media-control glyph:
those all live in the block terminals render from an emoji font instead of a
text one, which comes out double width and in a colour of its own. Everything
drawn here is from the geometric and dingbat blocks, the same as the line art."""


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

    RunScreen #terminal-art {
        width: auto;
        height: auto;
        margin-bottom: 1;
        color: $primary-lighten-2;
    }

    RunScreen #terminal-title {
        width: auto;
        height: 1;
        color: $text-muted;
        text-style: bold;
    }

    RunScreen #terminal-hint {
        width: auto;
        height: 1;
        color: $text-disabled;
    }

    RunScreen #stdin-row {
        width: 100%;
        height: 2;
        border-top: solid $primary-lighten-1;
        padding: 0 1;
    }

    /* A run is actually waiting on an answer, so the row stops reading as
       furniture. Nothing else on the panel is asking the user for anything,
       and a question nobody notices is a run that has silently stopped. */
    RunScreen.-asking #stdin-row {
        border-top: solid $accent;
    }

    RunScreen #stdin-label {
        width: auto;
        height: 1;
        margin-right: 1;
        color: $text-disabled;
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

    RunScreen #stdin-hint {
        margin-left: 1;
        margin-right: 0;
    }

    /* The keys that act on the tab strip, kept off it: anything sharing that
       row is width the tabs do not get, and the tabs are the part with no
       fixed size. */
    RunScreen #tab-keys {
        width: 100%;
        height: 1;
        padding: 0 1;
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
        border: round $accent;
    }

    /* The field keeps the row's width and the button takes what it needs, so a
       long path is still readable in the box that holds it. */
    RunScreen .field--path {
        width: 100%;
        height: auto;
    }

    RunScreen .field--path .field--input {
        width: 1fr;
    }

    RunScreen .field--browse {
        width: auto;
        min-width: 10;
        margin-left: 1;
    }

    /* A checkbox ships with a "block cursor" label — reversed text on a solid
       block — which in a form reads as accidentally selected text rather than
       as focus. Focus is said the same way everything else here says it. */
    RunScreen Checkbox {
        width: 100%;
        margin-bottom: 1;
        border: none;
        padding: 0;
        background: transparent;
    }

    RunScreen Checkbox:focus {
        border: none;
        background: transparent;
        background-tint: 0%;
    }

    RunScreen Checkbox > .toggle--label,
    RunScreen Checkbox:blur:hover > .toggle--label {
        background: transparent;
        color: $foreground;
        text-style: none;
    }

    RunScreen Checkbox:focus > .toggle--label {
        background: transparent;
        color: $accent;
        text-style: bold;
    }

    RunScreen Checkbox > .toggle--button {
        background: transparent;
        color: $primary-lighten-2;
    }

    RunScreen Checkbox.-on > .toggle--button {
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
        height: auto;
        min-height: 1;
        color: $warning;
    }

    RunScreen #validation.-refused {
        color: $error;
        text-style: bold;
    }

    RunScreen #actions {
        width: 100%;
        height: 3;
        margin-top: 1;
    }

    RunScreen #run {
        width: 1fr;
        height: 3;
        border: none !important;
        content-align: center middle;
    }

    RunScreen #run:focus,
    RunScreen #close:focus {
        text-style: bold;
        background-tint: 0%;
    }

    /* Only worth offering once there is a finished run to walk away from. */
    RunScreen #close {
        display: none;
        width: 12;
        height: 3;
        margin-left: 1;
        border: none !important;
        content-align: center middle;
    }

    RunScreen.-done #close {
        display: block;
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
                    with Horizontal(id="actions"):
                        yield Button("Run", id="run", variant="primary", flat=True)
                        yield Button("Close", id="close", flat=True)
                with Vertical(id="terminal-pane") as pane:
                    pane.border_title = "TERMINAL"
                    yield SessionTabs(id="tabs")
                    with Container(id="terminal-body"):
                        yield RichLog(
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
                    with Horizontal(id="stdin-row"):
                        yield Static("stdin ›", id="stdin-label")
                        yield Input(id="stdin", placeholder=STDIN_IDLE, disabled=True)
                        yield KeyHint("Enter", "Send", dim=True, id="stdin-hint")
                    with Horizontal(id="tab-keys"):
                        for key, label, press in TAB_KEYS:
                            yield KeyHint(key, label, press=press, dim=True)
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
                    Checkbox(option.label, value=bool(option.default), id=widget_id)
                )
                if option.help:
                    widgets.append(Static(option.help, classes="field--help"))
                continue

            widgets.append(Static(self._label(option), classes="field--label"))
            if option.kind is OptionKind.CHOICE and option.choices:
                widgets.append(
                    Select(
                        [(choice, choice) for choice in option.choices],
                        value=str(self._session.values.get(option.key, ""))
                        or option.choices[0],
                        allow_blank=False,
                        id=widget_id,
                    )
                )
            elif option.kind is OptionKind.PATH:
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
        self.set_class(session.finished, "-done")
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
        if self._composed:
            self.set_class(len(self._session.log) <= 1, "-empty")

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
        self._store(event.checkbox.id, event.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        self._store(event.select.id, str(event.value))

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
        if event.button.id == "close":
            self._session.decide(again=False)
        elif event.button.id == "run":
            self.action_primary()
        elif event.button.id and event.button.id.startswith("browse-"):
            self._browse(event.button.id.removeprefix("browse-"))

    def _browse(self, key: str) -> None:
        """Fill a path field from the tree, starting where the field points.

        The chosen path goes back through the field rather than straight into
        the values, so it is stored, echoed, and picked up by the rows that
        restate it exactly as if it had been typed.
        """
        field = self.query_one(f"#field-{key}", Input)

        def chosen(path: str | None) -> None:
            if path:
                field.value = path
            field.focus()

        self.app.push_screen(PathScreen(field.value, self._session.label), chosen)

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "stdin":
            return
        event.stop()
        self._session.reply(event.value.strip())


__all__ = [
    "TRAIL_SEPARATOR",
    "STDIN_ACTIVE",
    "STDIN_IDLE",
    "REQUIRED_MARK",
    "EMPTY_TITLE",
    "needed_text",
    "RunScreen",
]
