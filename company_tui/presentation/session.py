"""One run and everything it owns.

A session is a workflow's tab: the form it was started from, every line it has
printed, the task doing the work, and whatever that task is waiting on. The run
panel renders whichever session is selected rather than owning the run, so
leaving a session does not end it — come back and the log is still there with
the work still going.

Which session a line belongs to is decided by `CURRENT_SESSION`, a context
variable set when a session's task starts. Async tasks inherit the context they
were created in, so every `write`/`ask`/`confirm` inside a workflow resolves to
the session that workflow belongs to rather than to whatever happens to be on
screen. Routing by "the open panel" is exactly the wrong model once there is
more than one.

A tab outlives the app, but a run does not. What is kept between one launch and
the next is everything the user put in — the name they gave the tab, the stack
it belongs to, the form they filled in and what the last run printed — and none
of what was doing the work. A restored tab is idle, with its output above the
prompt under a line saying it is from a previous session, because a killed
subprocess cannot be resumed and a log restored as if it were live would show a
scaffold that never finished as one that had. See `domain/session_memory.py`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextvars import ContextVar
from datetime import datetime
from enum import Enum
from itertools import count

from textual.content import Content
from textual.worker import Worker

from company_tui.domain.options import (
    Option,
    OptionKind,
    OptionValue,
    defaults_for,
)
from company_tui.domain.session_memory import RememberedSession

TRAIL_SEPARATOR = " › "

HISTORY_OPENED = "── from a previous session{when} ──"
HISTORY_CLOSED = "── end of previous session ──"
"""What a restored log is wrapped in.

Marked rather than merely replayed. Output with nothing above it reads as this
run's output, which for a scaffold that died half way through a clone is a claim
that a directory exists in a state it does not."""

LOG_LIMIT = 500
"""Lines a session keeps before the oldest fall off the top.

`npm install` alone emits tens of thousands, and N sessions each holding every
one of them for the life of the app is a leak with a progress bar on it. A cap
here is a terminal's scrollback; a cap added later is a rewrite of everything
that reads the log. Tabs outlive the runs in them now, so the number of logs
being held is the number of tabs left open rather than the number in flight."""

RUN_STAMP = "%Y-%m-%d %H:%M:%S"
"""A run is something you come back to, so it says when it happened. Absolute
rather than relative: a tab read an hour later should not have to be worked out
backwards from "just now"."""

Workflow = Callable[[], Awaitable[None]]
"""A whole workflow, ready to be run again from the start.

Kept as a callable rather than a coroutine so a second tab in the same context
is one more call — the session strip's "+" is "another one of these", not a menu
walk repeated from memory."""


# Glyph, glyph style, body style — per line kind, as theme tokens. Assembled
# rather than marked up, because process output legitimately contains brackets
# and must never be parsed as markup.
#
# Only tokens that resolve to a literal color may be used here. The `$text-*`
# tokens are `auto` colors, which pick themselves from the background they are
# painted on; assembled content has no such background to read, so they come out
# pure black and the line is invisible.
#
# Every glyph is from the geometric or dingbat blocks. A clock face, a stopwatch
# or a media-control arrow all live in the block terminals render from an emoji
# font rather than a text one, which comes out double width and in a colour that
# ignores the theme. The timestamp goes without one instead: dimmed is enough to
# separate it from the run under it, and nothing legible was available.
MARKERS: dict[str, tuple[str, str, str]] = {
    "step": ("◆ ", "$accent", ""),
    "ok": ("✓ ", "$success", ""),
    "warn": ("▲ ", "$warning", ""),
    "error": ("✗ ", "$error", ""),
    "prompt": ("$ ", "$accent", ""),
    "reply": ("› ", "$accent", ""),
    "time": ("", "", "$foreground-darken-3"),
    "output": ("  ", "", "$foreground-darken-3"),
    "plain": ("", "", ""),
}


def render_line(message: str, marker: str = "plain") -> Content:
    glyph, glyph_style, body_style = MARKERS.get(marker, MARKERS["plain"])
    parts: list = []
    if glyph:
        parts.append((glyph, glyph_style) if glyph_style else glyph)
    parts.append((message, body_style) if body_style else message)
    return Content.assemble(*parts)


def _without_history(lines: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """The log with any previous session's markers taken back out.

    Restored lines are written down again — history is meant to survive more
    than one restart — but the pair of lines wrapping them is not, or every
    launch would wrap the last launch's wrapping and the log would end up more
    divider than output.
    """
    opening = HISTORY_OPENED.split("{", 1)[0]
    return [
        (message, marker)
        for message, marker in lines
        if not (message == HISTORY_CLOSED or message.startswith(opening))
    ]


class SessionStatus(Enum):
    """What a tab has to say for itself when it is not the one on screen."""

    IDLE = "idle"
    RUNNING = "running"
    ASKING = "asking"
    DONE = "done"
    FAILED = "failed"

    @property
    def glyph(self) -> str:
        return _GLYPHS[self]

    @property
    def live(self) -> bool:
        """Working, as opposed to waiting to be read."""
        return self in (SessionStatus.RUNNING, SessionStatus.ASKING)


_GLYPHS = {
    SessionStatus.IDLE: "○",
    SessionStatus.RUNNING: "●",
    SessionStatus.ASKING: "?",
    SessionStatus.DONE: "✓",
    SessionStatus.FAILED: "✗",
}


class RunSession:
    """One run: its form, its log, its task, and whatever it is waiting on.

    Every field the run panel used to hold lives here instead, so the panel can
    be thrown away and rebuilt around whichever session the user picked without
    the run noticing.
    """

    def __init__(
        self,
        identifier: int,
        name: str,
        workflow: Workflow,
        steps: dict[str, str] | None = None,
        preset: dict[str, object] | None = None,
        notify: Callable[[RunSession], None] | None = None,
    ) -> None:
        self.id = identifier
        self.name = name
        self.base = name
        """The label before it was numbered, so siblings are named after the
        same thing rather than after each other."""
        self.workflow = workflow
        self.refresh_runner: object = None
        """How to re-fetch a fetched choice on this session's form, if the
        workflow that opened it supplied a way. Set by `load`."""

        # Choice made at each step of this session's own navigation, and the
        # breadcrumb the panel and the dialogs are titled with. It keeps
        # changing as the workflow walks; `scope` does not.
        self.steps: dict[str, str] = dict(steps or {})
        self.scope: tuple[str, ...] = tuple(self.steps.values())
        """Where this run belongs, settled when it was made.

        A snapshot rather than a reading of `steps`, because a tab that
        re-homed itself every time the user chose differently would follow them
        out of the context it is holding a directory and a log for — which is
        how one terminal came to carry two stacks' runs. A workflow that walks
        somewhere else gets a session there instead (`TuiConsole._relocate`)."""
        self.answers: dict[str, object] = {}
        """What each step actually chose, so a sibling can repeat it."""
        self.preset: dict[str, object] = dict(preset or {})
        """Answers inherited from the session this one was opened beside."""

        self.task: Worker | None = None
        """The whole workflow. A Textual worker rather than a bare task, so a
        run started from a keypress can still push a screen of its own."""
        self.work: asyncio.Task | None = None
        """The one slow thing inside it that Stop cancels."""
        self.foreground = True
        """Whether this session still needs the screen to itself. Cleared once
        it is left running in the background, which is what frees the menu."""
        self.result_acknowledged = False

        self.log: deque[Content] = deque(maxlen=LOG_LIMIT)
        self.lines: deque[tuple[str, str]] = deque(maxlen=LOG_LIMIT)
        """The same log, unrendered, for the one reader that outlives the theme.

        A `Content` carries the colours of the theme it was assembled under, so
        it is what to draw and not what was said. Kept alongside rather than
        parsed back out of, and capped by the same limit, so the pair cannot
        drift."""

        self.stamp = ""
        """When this tab last ran, in the words the log says it in."""

        self.title = ""
        self.options: tuple[Option, ...] = ()
        self.trail: tuple[str, ...] = ()
        self.values: dict[str, OptionValue] = {}
        self.panel_open = False

        self.opened = False
        """Whether a form was ever put up here — which is what makes this a tab
        rather than a workflow's placeholder.

        Every workflow owns a session from the moment it starts, long before it
        knows which context it is for: it is what carries the breadcrumb and the
        answers while the user is still walking menus. Counting those as tabs is
        how a strip grew an entry nothing had ever been in, and how the chrome
        came to report a run waiting that was really a menu."""

        self.ran = False
        """Whether anything was ever run here. It is what keeps the tab once
        its workflow is over: a finished run is a result to read and a form to
        send again, and dropping it the moment the panel closed left doing the
        whole thing over as the only way back to it."""

        self.started = False
        self.finished = False
        self.ok = True
        self.cancelled = False
        self.stop_requested = False
        self.run_again = False
        self.failure = ""
        self.question = ""

        self.submitted: asyncio.Event = asyncio.Event()
        self.next_decided: asyncio.Event = asyncio.Event()
        self.answer: asyncio.Future[str] | None = None

        self._notify = notify or (lambda _session: None)
        self._echo: Callable[[Content], None] | None = None
        self._on_view: Callable[[], None] | None = None

    # ------------------------------------------------------------------ scope

    @property
    def place(self) -> tuple[str, ...]:
        """Where the workflow using this session has got to, which may not be
        where the session belongs any more."""
        return tuple(self.steps.values())

    @property
    def status(self) -> SessionStatus:
        if self.answer is not None and not self.answer.done():
            return SessionStatus.ASKING
        if self.finished:
            return SessionStatus.DONE if self.ok else SessionStatus.FAILED
        if self.started:
            return SessionStatus.RUNNING
        return SessionStatus.IDLE

    @property
    def label(self) -> str:
        return TRAIL_SEPARATOR.join(self.trail or (self.title,))

    # ----------------------------------------------------------- the watchers

    def watch(
        self,
        echo: Callable[[Content], None] | None = None,
        on_view: Callable[[], None] | None = None,
    ) -> None:
        """Mirror this session to the panel showing it, or to nothing at all."""
        self._echo = echo
        self._on_view = on_view

    def changed(self) -> None:
        if self._on_view is not None:
            self._on_view()
        self._notify(self)

    # ------------------------------------------------------------------- form

    def load(
        self,
        title: str,
        options: Sequence[Option],
        trail: Sequence[str] = (),
        refresh: object = None,
    ) -> None:
        """Set the form up for a run of this session.

        `refresh` is kept on the session rather than on the screen because the
        screen renders whichever tab is selected: two tabs can hold forms from
        different workflows, and an Update button has to run the refresh
        belonging to the form it is drawn on."""
        self.refresh_runner = refresh
        answered = self.values
        self.title = title
        self.options = tuple(options)
        self.trail = tuple(trail)
        self.values = defaults_for(self.options)
        for option in self.options:
            # A choice with no default still has a value: whatever the list
            # opens on. Settled here so it is true before any widget exists.
            if option.kind is OptionKind.CHOICE and option.choices:
                self.values[option.key] = str(option.default) or option.choices[0]
        # What this tab was answered with last time. Coming back to a run that
        # failed on one field should not mean typing the other five again, and
        # the form is the record of what was asked for either way.
        #
        # An answer to a CHOICE is dropped when it is no longer one of the
        # choices. A fetched list changes between runs - the branch answered
        # last time is exactly the one somebody has since deleted - and a Select
        # built with a value outside its own options raises
        # InvalidSelectValueError on mount, which takes the app down rather than
        # the field. A MULTI keeps whichever of its answers survived.
        self.values.update(
            {
                key: self._surviving(key, value)
                for key, value in answered.items()
                if key in self.values and self._surviving(key, value) != ""
            }
        )
        self.panel_open = True
        self.opened = True
        # A form is opened, not resumed. Whatever the last attempt decided is
        # over, and a session that backed out of one carries `cancelled` until
        # something clears it — which made choosing the same stack again answer
        # the new form with the old refusal before it was ever on screen, and
        # sent the workflow back to the menu it had just come from.
        self._rearm()
        self._open_prompt()

    def _surviving(self, key: str, value: OptionValue) -> OptionValue:
        """`value` with anything the option no longer offers taken out.

        Returns it unchanged for a field with no vocabulary, `''` for a choice
        whose answer is gone, and the remaining members for a multi-select.
        """
        option = next((o for o in self.options if o.key == key), None)
        if option is None or not option.choices:
            return value
        if option.kind is OptionKind.MULTI:
            kept = [
                part.strip()
                for part in str(value).split(",")
                if part.strip() in option.choices
            ]
            return ",".join(kept)
        return value if str(value) in option.choices else ""

    def _open_prompt(self) -> None:
        """Start this run's transcript, unless the last prompt is still unused.

        Backing out of a form and opening it again is nothing happening, and a
        prompt per attempt stacks up a transcript of no runs. Backing out to a
        different stack does get its own — but by landing in that stack's own
        session, which opens on an empty log, rather than by adding a line here.
        """
        prompt = render_line(self.label, marker="prompt")
        if self.log and self.log[-1].plain == prompt.plain:
            return
        if self.log:
            self.write("")
        self.write(self.label, marker="prompt")

    def store(self, key: str, value: OptionValue) -> None:
        self.values[key] = value

    # -------------------------------------------------------------- lifecycle

    async def wait_for_values(self) -> dict[str, OptionValue] | None:
        """Resolve when the user runs, or `None` if they backed out first."""
        await self.submitted.wait()
        return None if self.cancelled else dict(self.values)

    async def wait_for_next(self) -> bool:
        """After a run: `True` to set up another one here, `False` to leave.

        Making a second project should not mean walking back out through the
        menu and picking the same three things again, so a finished panel offers
        the form back rather than only the door.
        """
        await self.next_decided.wait()
        return self.run_again

    def start(self) -> None:
        self.started = True
        self.ran = True
        self.stamp = datetime.now().strftime(RUN_STAMP)
        self.write(self.stamp, marker="time")
        self.submitted.set()
        self.changed()

    def cancel(self) -> None:
        self.cancelled = True
        self.submitted.set()
        self.changed()

    def decide(self, again: bool) -> None:
        if not self.finished:
            return
        self.run_again = again
        self.next_decided.set()

    def finish(self, message: str, ok: bool = True) -> None:
        self.finished = True
        self.ok = ok
        self.write("")
        # A failure has already been reported where it happened; closing with
        # the same words again would just make it look like it went wrong twice.
        if message and message != self.failure:
            self.write(message, marker="ok" if ok else "error")
        self.write("Run again to make another, or Esc to return to the menu.")
        self.changed()

    def _rearm(self) -> None:
        """Ready to be run, whatever the attempt before it decided."""
        self.started = False
        self.finished = False
        self.ok = True
        self.cancelled = False
        self.stop_requested = False
        self.run_again = False
        self.failure = ""
        self.submitted = asyncio.Event()
        self.next_decided = asyncio.Event()

    def reset(self) -> None:
        """Back to the form, with the finished run left above it as history."""
        self._rearm()

        # Reads as a shell: the last run stays above, and this one starts with a
        # fresh prompt rather than pretending nothing came before it.
        self._open_prompt()
        self.changed()

    def request_stop(self) -> None:
        if not self.started or self.finished or self.stop_requested:
            return
        self.stop_requested = True
        self.write("Stopping...", marker="warn")
        if self.work is not None:
            self.work.cancel()
        self.changed()

    def report_failure(self, error: BaseException) -> str:
        """Show a workflow's unhandled error here instead of losing the app.

        A capability that raises is a bug, but taking the whole interface down
        and printing a traceback over the terminal tells the user less than the
        message does, and loses everything the run had already reported.
        """
        self.failure = f"{type(error).__name__}: {error}"
        self.write(self.failure, marker="error")
        self.changed()
        return self.failure

    # --------------------------------------------------------------- the log

    def write(self, message: str, marker: str = "plain") -> None:
        content = render_line(message, marker)
        self.log.append(content)
        self.lines.append((message, marker))
        if self._echo is not None:
            self._echo(content)

    def transcript(self) -> str:
        """Everything this tab has printed, as one block of text.

        Read off the log rather than off the widget showing it: the panel wraps
        each line to whatever width the terminal pane happens to be, and a
        transcript broken at the column the window was that afternoon is not
        what anyone pasting it wants. The rendered text, though — glyphs and
        all — because those are what the user is looking at, and a copy that
        quietly drops the `$` off the prompts is a copy of something else.
        """
        return "\n".join(content.plain for content in self.log)

    def clear_log(self) -> None:
        """Empty the terminal, leaving the prompt this run started under.

        The prompt goes back because a cleared terminal is still this tab's
        terminal, and that line is the only place the panel says which stack
        and which workflow it belongs to. Clearing to nothing at all would take
        the tab's name off its own output.
        """
        self.log.clear()
        self.lines.clear()
        self._open_prompt()
        self.changed()

    # ------------------------------------------------------------- remembering

    def to_memory(self) -> RememberedSession:
        """This tab as it deserves to come back: answers, not work.

        `scope` is written down in its own right rather than left to be read
        back out of `steps`. The two part company the moment a workflow walks
        back to re-ask a step — `_enter_step` trims `steps` so the breadcrumb
        corrects itself, while the scope the tab was created under stays where
        it is. Read back from a trimmed `steps`, a React Native tab comes back
        belonging to `("Scaffold",)` and appears in no strip at all.
        """
        return RememberedSession(
            name=self.name,
            base=self.base,
            scope=self.scope,
            steps=dict(self.steps),
            title=self.title,
            trail=tuple(self.trail),
            values=dict(self.values),
            log=tuple(_without_history(self.lines)),
            stamp=self.stamp,
        )

    def replay(self, remembered: RememberedSession) -> None:
        """Take up what a previous run of the app left here.

        The form comes back filled and the output comes back marked as over.
        Nothing about the run itself does: a restored tab is idle, and the next
        thing written under this is the prompt of a run that has not happened
        yet.
        """
        self.scope = tuple(remembered.scope) or self.scope
        self.title = remembered.title
        self.trail = tuple(remembered.trail)
        self.values = dict(remembered.values)
        self.stamp = remembered.stamp
        self.opened = True
        self.ran = True
        if not remembered.log:
            return
        when = f" · {remembered.stamp}" if remembered.stamp else ""
        self.write(HISTORY_OPENED.format(when=when), marker="time")
        for message, marker in remembered.log:
            self.write(message, marker)
        self.write(HISTORY_CLOSED, marker="time")

    # ----------------------------------------------------------- the question

    async def prompt(self, question: str) -> str:
        """Ask in this session's terminal, and block only this session."""
        self.write(question, marker="warn")
        self.question = question
        self.answer = asyncio.get_running_loop().create_future()
        self.changed()
        try:
            answer = await self.answer
        finally:
            self.answer = None
            self.question = ""
            self.changed()
        self.write(answer or "(empty)", marker="reply")
        return answer

    def reply(self, answer: str) -> bool:
        if self.answer is None or self.answer.done():
            return False
        self.answer.set_result(answer)
        return True


class SessionRegistry:
    """Every session there is, in one place, whatever context made it.

    Each context gets its own strip, but not its own registry: a session that
    only existed inside its own context would be reachable only by walking the
    menus back to it from memory — still holding a directory, possibly waiting
    on a question. Kept together, every run can be counted from anywhere, which
    is what lets the chrome say how many are going, `Ctrl+B` reach the one that
    needs an answer, and each menu card say what is happening behind it.
    """

    def __init__(self, on_change: Callable[[RunSession | None], None] | None = None) -> None:
        self._sessions: list[RunSession] = []
        self._ids = count(1)
        self._on_change = on_change or (lambda _session: None)

    def create(
        self,
        name: str,
        workflow: Workflow,
        steps: dict[str, str] | None = None,
        preset: dict[str, object] | None = None,
    ) -> RunSession:
        session = RunSession(
            identifier=next(self._ids),
            name=self._unique(name, tuple((steps or {}).values())),
            workflow=workflow,
            steps=steps,
            preset=preset,
            notify=self._on_change,
        )
        session.base = name
        self._sessions.append(session)
        self._on_change(session)
        return session

    def restore(
        self, remembered: RememberedSession, workflow: Workflow
    ) -> RunSession:
        """Put a tab back as the app found it written down.

        With no workflow of its own: nothing is driving a restored tab, which is
        exactly what lets the next workflow to walk into that context pick it up
        (`TuiConsole._relocate`) instead of opening a second one beside it. That
        is the whole of "restore in place" — no menu is skipped and no run is
        resumed; the tab is simply already there when the user arrives.
        """
        session = self.create(
            remembered.base or remembered.name,
            workflow,
            steps=dict(remembered.steps),
        )
        # Replayed before it is named, because the name has to be free in the
        # strip this tab actually belongs to, and until the scope is back that
        # is not known.
        session.replay(remembered)
        session.name = self._unique(remembered.name, session.scope, except_for=session)
        # And not holding the screen either. A session is born wanting the
        # foreground because a session is normally born to run something, and
        # what clears it is being left running in the background — which never
        # happens to a tab that was never started. Left set, every restored tab
        # counts as one more thing the menu loop is waiting on, and the loop
        # stops coming back: the app draws its own empty frame and the only key
        # that still does anything is the one that quits.
        session.foreground = False
        self._on_change(session)
        return session

    def remembered(self) -> tuple[RememberedSession, ...]:
        """Every tab worth writing down, in the order they are shown.

        Tabs, not sessions: a workflow between two menus owns a session too, and
        restoring one would put an entry in a strip that nothing was ever in.
        """
        return tuple(s.to_memory() for s in self._sessions if s.opened)

    def remove(self, session: RunSession) -> None:
        if session in self._sessions:
            self._sessions.remove(session)
        self._on_change(None)

    def rename(self, session: RunSession, name: str) -> None:
        cleaned = name.strip()
        if not cleaned or cleaned == session.name:
            return
        session.name = self._unique(cleaned, session.scope, except_for=session)
        self._on_change(session)

    def all(self) -> tuple[RunSession, ...]:
        return tuple(self._sessions)

    def live(self) -> tuple[RunSession, ...]:
        return tuple(s for s in self._sessions if s.status.live)

    def visible(self, scope: tuple[str, ...]) -> tuple[RunSession, ...]:
        """This context's tabs, and only this context's.

        Flutter shows Flutter. A run from anywhere else is not here at all —
        a tail of foreign tabs is the thing a strip per context exists to be
        rid of, and it would grow with every stack the user ever opened. What
        keeps such a run from being forgotten is `running_under`, which puts
        the count on the menu card that leads back to it, the running total in
        the chrome, and `Ctrl+B` to step straight into whichever run needs
        something.

        Tabs, not sessions: a workflow still walking the menus owns a session
        too, and it is nothing you could open, close, rename or run in.
        """
        return tuple(s for s in self._sessions if s.opened and s.scope == scope)

    def running_under(self, place: tuple[str, ...]) -> int:
        """How many runs are going at or below a point in the menus.

        By prefix rather than by exact context, so a stack's card counts that
        stack's runs and `Scaffold`'s card counts all of them — every menu says
        what is happening behind each door before the user opens it.
        """
        return sum(
            1
            for session in self._sessions
            if session.status.live and session.scope[: len(place)] == place
        )

    def summary(self) -> str:
        """What the chrome says about runs the user cannot currently see.

        Counted over tabs rather than sessions. A workflow between two menus is
        not a run waiting to be read, and a header that said so sent the user
        looking for something that was never there.
        """
        tabs = [s for s in self._sessions if s.opened]
        if not tabs:
            return ""
        running = sum(1 for s in tabs if s.status.live)
        waiting = len(tabs) - running
        parts = []
        if running:
            parts.append(f"{running} running")
        if waiting:
            parts.append(f"{waiting} waiting")
        return " · ".join(parts)

    def _unique(
        self,
        base: str,
        scope: tuple[str, ...],
        except_for: RunSession | None = None,
    ) -> str:
        """A name free in the one strip it will be seen in.

        Numbered against that strip rather than against every session there is,
        so each context starts at one: the second stack you scaffold opens on
        its own first tab instead of inheriting a number from the first.

        `except_for` is the session being named. Without it a tab restored under
        the name it already has collides with itself and comes back as "… 2".
        """
        taken = {
            s.name
            for s in self._sessions
            if s.scope == scope and s is not except_for
        }
        if base not in taken:
            return base
        return next(f"{base} {n}" for n in count(2) if f"{base} {n}" not in taken)


CURRENT_SESSION: ContextVar[RunSession | None] = ContextVar(
    "current_session", default=None
)


def current_session() -> RunSession | None:
    """The session whichever workflow is asking belongs to, if any."""
    return CURRENT_SESSION.get()
