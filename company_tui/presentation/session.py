"""One run and everything it owns."""

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
"""What a restored log is wrapped in."""

LOG_LIMIT = 500
"""Lines a session keeps before the oldest fall off the top."""

RUN_STAMP = "%Y-%m-%d %H:%M:%S"
"""A run is something you come back to, so it says when it happened. Absolute."""

Workflow = Callable[[], Awaitable[None]]
"""A whole workflow, ready to be run again from the start."""

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
    """The log with any previous session's markers taken back out."""
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
    """One run: its form, its log, its task, and whatever it is waiting on."""

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
        """The label before it was numbered, so siblings are named after the."""
        self.workflow = workflow
        self.refresh_runner: object = None
        """How to re-fetch a fetched choice on this session's form, if the."""

        self.subtitle = ""
        """One line saying what the command is for, shown above its fields."""

        self.preview_runner: object = None
        """What the current answers add up to, as a command line. Supplied by."""

        self.steps: dict[str, str] = dict(steps or {})
        self.scope: tuple[str, ...] = tuple(self.steps.values())
        """Where this run belongs, settled when it was made."""
        self.answers: dict[str, object] = {}
        """What each step actually chose, so a sibling can repeat it."""
        self.preset: dict[str, object] = dict(preset or {})
        """Answers inherited from the session this one was opened beside."""

        self.task: Worker | None = None
        """The whole workflow. A Textual worker rather than a bare task, so a."""
        self.work: asyncio.Task | None = None
        """The one slow thing inside it that Stop cancels."""
        self.foreground = True
        """Whether this session still needs the screen to itself. Cleared once."""
        self.result_acknowledged = False

        self.log: deque[Content] = deque(maxlen=LOG_LIMIT)
        self.lines: deque[tuple[str, str]] = deque(maxlen=LOG_LIMIT)
        """The same log, unrendered, for the one reader that outlives the theme."""

        self.stamp = ""
        """When this tab last ran, in the words the log says it in."""

        self.title = ""
        self.options: tuple[Option, ...] = ()
        self.trail: tuple[str, ...] = ()
        self.values: dict[str, OptionValue] = {}
        self.panel_open = False

        self.opened = False
        """Whether a form was ever put up here — which is what makes this a tab."""

        self.ran = False
        """Whether anything was ever run here. It is what keeps the tab once."""

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


    @property
    def place(self) -> tuple[str, ...]:
        """Where the workflow using this session has got to, which may not be."""
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


    def load(
        self,
        title: str,
        options: Sequence[Option],
        trail: Sequence[str] = (),
        refresh: object = None,
        preview: object = None,
        subtitle: str = "",
    ) -> None:
        """Set the form up for a run of this session."""
        self.refresh_runner = refresh
        self.preview_runner = preview
        self.subtitle = subtitle
        answered = self.values
        self.title = title
        self.options = tuple(options)
        self.trail = tuple(trail)
        self.values = defaults_for(self.options)
        for option in self.options:
            if option.kind in (OptionKind.CHOICE, OptionKind.MULTI) and option.choices:
                self.values[option.key] = ""
        self.values.update(
            {
                key: self._surviving(key, value)
                for key, value in answered.items()
                if key in self.values and self._surviving(key, value) != ""
            }
        )
        self.panel_open = True
        self.opened = True
        self._rearm()
        self._open_prompt()

    def command_preview(self) -> str:
        """The command line these answers add up to, or `''` if nobody said how."""
        if self.preview_runner is None:
            return ""
        return str(self.preview_runner(dict(self.values)))

    def _surviving(self, key: str, value: OptionValue) -> OptionValue:
        """`value` with anything the option no longer offers taken out."""
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
        """Start this run's transcript, unless the last prompt is still unused."""
        prompt = render_line(self.label, marker="prompt")
        if self.log and self.log[-1].plain == prompt.plain:
            return
        if self.log:
            self.write("")
        self.write(self.label, marker="prompt")

    def store(self, key: str, value: OptionValue) -> None:
        self.values[key] = value


    async def wait_for_values(self) -> dict[str, OptionValue] | None:
        """Resolve when the user runs, or `None` if they backed out first."""
        await self.submitted.wait()
        return None if self.cancelled else dict(self.values)

    async def wait_for_next(self) -> bool:
        """After a run: `True` to set up another one here, `False` to leave."""
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
        """Show a workflow's unhandled error here instead of losing the app."""
        self.failure = f"{type(error).__name__}: {error}"
        self.write(self.failure, marker="error")
        self.changed()
        return self.failure


    def write(self, message: str, marker: str = "plain") -> None:
        content = render_line(message, marker)
        self.log.append(content)
        self.lines.append((message, marker))
        if self._echo is not None:
            self._echo(content)

    def transcript(self) -> str:
        """Everything this tab has printed, as one block of text."""
        return "\n".join(content.plain for content in self.log)

    def clear_log(self) -> None:
        """Empty the terminal, leaving the prompt this run started under."""
        self.log.clear()
        self.lines.clear()
        self._open_prompt()
        self.changed()


    def to_memory(self) -> RememberedSession:
        """This tab as it deserves to come back: answers, not work."""
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
        """Take up what a previous run of the app left here."""
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
    """Every session there is, in one place, whatever context made it."""

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
        """Put a tab back as the app found it written down."""
        session = self.create(
            remembered.base or remembered.name,
            workflow,
            steps=dict(remembered.steps),
        )
        session.replay(remembered)
        session.name = self._unique(remembered.name, session.scope, except_for=session)
        session.foreground = False
        self._on_change(session)
        return session

    def remembered(self) -> tuple[RememberedSession, ...]:
        """Every tab worth writing down, in the order they are shown."""
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
        """This context's tabs, and only this context's."""
        return tuple(s for s in self._sessions if s.opened and s.scope == scope)

    def running_under(self, place: tuple[str, ...]) -> int:
        """How many runs are going at or below a point in the menus."""
        return sum(
            1
            for session in self._sessions
            if session.status.live and session.scope[: len(place)] == place
        )

    def summary(self) -> str:
        """What the chrome says about runs the user cannot currently see."""
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
        """A name free in the one strip it will be seen in."""
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
