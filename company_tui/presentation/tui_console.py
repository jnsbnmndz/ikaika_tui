import asyncio
from collections.abc import Awaitable, Sequence
from contextlib import suppress
from typing import TypeVar

from textual import events, work
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import RichLog

from company_tui.application.app import Application
from company_tui.domain.capability import Capability
from company_tui.domain.options import Option, OptionValue
from company_tui.domain.template_pack import ScaffoldTarget, ScaffoldTargetOption, TemplatePack
from company_tui.infrastructure.terminal_window import restore_terminal_interaction
from company_tui.presentation.branding import APP_NAME, APP_TAGLINE, APP_VERSION, IKAIKA_THEME, PEAK_ART
from company_tui.presentation.card import MenuEntry
from company_tui.presentation.chrome import AppFooter, AppFrame, AppHeader
from company_tui.presentation.run_screen import RunScreen
from company_tui.presentation.screens import (
    TRAIL_SEPARATOR,
    CardMenuScreen,
    ConfirmScreen,
    ContinueScreen,
    InputScreen,
    RunsScreen,
    SplashScreen,
)
from company_tui.presentation.session import (
    CURRENT_SESSION,
    RunSession,
    SessionRegistry,
    Workflow,
    current_session,
)

TRAIL_STEPS = ("capability", "scaffold_target", "template_pack")

RAW_OUTPUT_PREFIX = "  "
"""Marks a line as verbatim output from a subprocess rather than the toolbox
talking. Reads as indentation in the plain console, and as dimmed process output
in the run panel."""

QUIT_WITH_RUNS = "still running. Stop everything and quit?"
QUIT_CONFIRM = f"Leave {APP_NAME}?"

T = TypeVar("T")


class TuiConsole(App):
    """The interactive front end, and the owner of every run in flight.

    One workflow used to own one screen and one console. Sessions turn that
    around: the console holds every run, each with its own log, task and form,
    and the run panel becomes a view onto whichever one is selected. Output
    finds its way home through `CURRENT_SESSION` rather than through "the panel
    that happens to be open", which is the only routing rule that survives there
    being more than one.
    """

    TITLE = f"{PEAK_ART}  {APP_NAME} — {APP_TAGLINE}"
    SUB_TITLE = APP_VERSION
    BINDINGS = [
        ("ctrl+q", "leave", "Quit"),
        # The key everyone reaches for out of habit, so it means what they
        # expect rather than nothing. It is checked after the screen's own copy
        # binding, which yields when there is no selection to copy.
        ("ctrl+c", "leave", "Quit"),
        ("ctrl+b", "resume_runs", "Runs"),
    ]

    CSS = """
    Screen {
        align: center middle;
    }

    #output {
        width: 100%;
        height: 1fr;
        margin: 1 2;
        border: round $primary-lighten-1;
        border-title-color: $accent;
        padding: 0 1;
        background: $surface;
        scrollbar-size-vertical: 1;
    }

    /* Every workflow step pops one screen before pushing the next, and this is
       what shows in between. Hidden rather than removed so the header and footer
       stay exactly where they are: an empty frame for a frame reads as the same
       surface, an empty bordered box reads as somewhere else. */
    #output.-quiet {
        visibility: hidden;
    }
    """

    def __init__(self, workspace_label: str | None = None) -> None:
        super().__init__()
        self.application: Application | None = None
        self.workspace_label = workspace_label
        self.result_code = 0
        # Choice already made at each step, for navigation that has not become a
        # session yet. Once it has, the session carries its own.
        self._steps: dict[str, str] = {}
        self._sessions = SessionRegistry(on_change=self._session_changed)
        self._panel: RunScreen | None = None
        self._attached: RunSession | None = None
        # Set while nothing is claiming the screen, which is what lets the menu
        # loop come back round.
        self._foreground_free = asyncio.Event()
        self._foreground_free.set()
        self._attachment = asyncio.Event()
        self._result_acknowledged = False

    def compose(self) -> ComposeResult:
        with AppFrame():
            yield AppHeader()
            yield RichLog(id="output", wrap=True, markup=True, classes="-quiet")
            yield AppFooter([("Ctrl+Q", "Quit")])

    def on_mount(self) -> None:
        self.register_theme(IKAIKA_THEME)
        self.theme = "ikaika"
        output = self.query_one("#output", RichLog)
        output.border_title = "Activity"
        # Nothing here resizes the terminal. Asking it to leaves its cell grid
        # and ours disagreeing, and from then on the pointer lands somewhere
        # other than where it points.
        self._start()

    def _write_to_terminal(self, data: str) -> None:
        """Send an escape sequence the way Textual sends its own.

        Never `sys.stdout`. The driver owns the output stream and on Windows
        writes it from a background thread, so anything written straight to
        stdout can land in the middle of a frame and splice itself into another
        escape sequence — which is how a working screen turns into one whose
        contents no longer sit where it thinks they do.
        """
        driver = self._driver
        if driver is None:
            return
        driver.write(data)
        driver.flush()

    def _clear_pointer_state(self) -> None:
        """Discard pointer state that a focus change can strand mid-gesture."""
        self.capture_mouse(None)
        # Textual otherwise keeps the old hover target until another mouse event.
        # Clearing it makes the first movement after returning emit Enter again.
        self._set_mouse_over(None, None)
        self._end_text_selection()

    def _end_text_selection(self) -> None:
        """Abandon a drag-selection rather than let it outlive the window.

        A press with no matching release — the window went away between them —
        leaves the screen convinced a drag is still in progress. It then treats
        every later movement as extending that selection: the highlight follows
        the pointer, scrollable content auto-scrolls under it, and the press
        that should have chosen something goes into ending the drag instead.
        `clear_selection` alone is not enough; it forgets the selection but
        leaves the drag itself armed.
        """
        for screen in self.screen_stack:
            screen.clear_selection()
            screen._selecting = False
            screen._mouse_down_offset = None

    def on_app_blur(self, event: events.AppBlur) -> None:
        self._clear_pointer_state()

    def on_app_focus(self, event: events.AppFocus) -> None:
        # Some Windows terminals stop forwarding mouse movement/clicks while the
        # window is inactive and don't reliably restore those modes themselves.
        restore_terminal_interaction(self._write_to_terminal)
        self._clear_pointer_state()
        # Repaint rather than re-layout: the terminal may have been redrawn from
        # under us, so every cell is suspect, not just the geometry.
        self.call_after_refresh(self._repaint_everything)

    def _repaint_everything(self) -> None:
        for screen in self.screen_stack:
            screen.refresh(repaint=True, layout=True)

    @work
    async def _start(self) -> None:
        await self.push_screen_wait(SplashScreen())
        assert self.application is not None
        self.result_code = await self.application.run()
        await self._stop_every_run()
        self.exit()

    # ------------------------------------------------------------- the output

    def write(self, message: str = "") -> None:
        session = current_session()
        if session is not None and session.panel_open:
            session.write(message, marker=self._marker_for(message))
            return
        self._output().write(message)

    def _output(self) -> RichLog:
        """The activity log, shown from the first thing written into it."""
        log = self.query_one("#output", RichLog)
        log.remove_class("-quiet")
        return log

    def _quiet_output(self) -> None:
        """Nothing to look at again, ready for the next workflow.

        The activity log is where a workflow with no panel of its own reports,
        and the user reads it at the pause that follows. After that it is a line
        from a run that is over — and left standing it rides along behind every
        later transition, which is the one thing the gap between screens exists
        not to do.
        """
        for log in self.query("#output").results(RichLog):
            log.clear()
            log.add_class("-quiet")

    @staticmethod
    def _marker_for(message: str) -> str:
        """Two conventions, both readable in the plain console too: a line
        indented by `RAW_OUTPUT_PREFIX` is verbatim process output, and a line
        ending in an ellipsis is a step about to happen."""
        if message.startswith(RAW_OUTPUT_PREFIX):
            return "output"
        return "step" if message.endswith("...") else "plain"

    def error(self, message: str) -> None:
        session = current_session()
        if session is not None and session.panel_open:
            session.write(message, marker="error")
            return
        self._output().write(f"[bold red]Error: {message}[/bold red]")

    async def ask(self, prompt: str) -> str:
        session = current_session()
        if session is not None and session.panel_open:
            # Blocks this session and nothing else: a hidden run waiting on an
            # answer badges its own tab rather than stopping the app.
            return await session.prompt(prompt)
        await self._claim_screen(session)
        return await self.push_screen_wait(InputScreen(prompt, self.trail_label()))

    async def confirm(self, prompt: str) -> bool:
        session = current_session()
        if session is not None and session.panel_open:
            answer = await session.prompt(f"{prompt} (y/N)")
            return answer.strip().lower() in ("y", "yes")
        await self._claim_screen(session)
        return await self.push_screen_wait(ConfirmScreen(prompt, self.trail_label()))

    # ------------------------------------------------------------- the panel

    @property
    def sessions(self) -> SessionRegistry:
        """Every run there is, whichever context made it."""
        return self._sessions

    async def start_run(self, workflow: Workflow, label: str) -> None:
        session = self._sessions.create(label, workflow, steps=dict(self._steps))
        self._foreground_free.clear()
        self._spawn(session)
        await self._foreground_free.wait()

    def _spawn(self, session: RunSession) -> None:
        async def run() -> None:
            # Set inside the task, so it belongs to this task's context and to
            # every task created from it — which is every `write`, `ask` and
            # subprocess the workflow goes on to make.
            CURRENT_SESSION.set(session)
            try:
                await session.workflow()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._here(session).report_failure(error)
            finally:
                self._retire(self._here(session))

        session.foreground = True
        # A worker, not a bare task: a session started from the tab strip has no
        # worker above it to inherit, and a workflow that cannot push a screen
        # is one that cannot ask a question or show a menu.
        session.task = self.run_worker(
            run(), name=session.name, group="session", exit_on_error=False
        )
        self._settle()

    @staticmethod
    def _here(started_in: RunSession) -> RunSession:
        """The session a workflow is using now, which is not always the one it
        started in — walking to another context moves it to that context's."""
        return current_session() or started_in

    def _retire(self, session: RunSession) -> None:
        """The workflow is over. Whether the tab goes with it depends.

        A tab something was run in stays, freed rather than removed: it holds
        the output, the time it happened and the form it was sent, and walking
        back into the stack is how you get to it. One that only ever showed a
        menu or a form nobody sent has nothing to come back for.
        """
        session.panel_open = False
        # Nothing is driving it any more, which is what lets a workflow that
        # walks back in here pick it up instead of opening a tab beside it.
        session.task = None
        self._background(session)
        if not session.ran:
            self._sessions.remove(session)
        if self._attached is session:
            self._detach()
        else:
            self._settle()
            self._refresh_panel()

    async def open_run_panel(
        self,
        title: str,
        options: Sequence[Option],
        trail: Sequence[str] = (),
    ) -> dict[str, OptionValue] | None:
        session = current_session()
        if session is None:
            # No session means no task of our making — a capability driven
            # straight from the CLI rather than off the menu. It still gets a
            # form; having no worker behind it is what `_retire` reads to know
            # nothing will ever come along and clear its tab.
            session = self._sessions.create(title, _nothing, steps=dict(self._steps))
            CURRENT_SESSION.set(session)
        else:
            session = self._relocate(session)
            if session is None:
                # The context is busy and the user is now watching it. Reads
                # to the workflow as a step backwards, which puts its own menu
                # up once the screen comes free.
                return None
        # A panel already open is one the user asked to keep for another run, so
        # it collects the next set of values rather than being replaced.
        if not session.panel_open:
            session.load(title, options, trail or tuple(session.steps.values()))
        self._attach(session)

        values = await session.wait_for_values()
        if values is None:
            session.panel_open = False
            if self._attached is session:
                self._detach()
            return None
        return values

    def _relocate(self, session: RunSession) -> RunSession | None:
        """The session for where the workflow is now, which may not be this one.

        A session belongs to one context for the whole of its life, so a
        workflow that has walked to another stack carries on in a session
        there rather than dragging this one along. Dragging it along is what
        put two stacks' runs in one terminal, and it is why the tab a user left
        going in React Native was the same tab that greeted them in Flutter.

        The context is only fully known here, at the panel — a menu deeper than
        the last one answered has not been asked yet — so this is where the
        move happens rather than at each step. What is left behind is dropped:
        nothing ever ran in it, and a tab nobody can reach from the strip they
        walked to is litter.

        Walking into a stack that already has a tab nothing is driving picks
        that tab up rather than opening one beside it. That is what makes going
        back into React Native mean going back to the React Native run — its
        output still above, the time it happened still in it, and the form
        still holding what it was sent.
        """
        if session.scope == session.place:
            return session

        free = self._free_at(session.place)
        busy = tuple(s for s in self._sessions.visible(session.place) if s.panel_open)
        if free is None and busy:
            # Every tab here is mid-run. There is nothing to fill in, so the
            # user is put on the run that is already going rather than handed a
            # second tab beside it, and this workflow waits for the screen —
            # which it gets back as the menu it came from when they leave.
            #
            # Only a tab with a form on it counts: one whose own workflow has
            # walked off to a menu has nothing to show, and attaching it put up
            # a run panel with an empty configuration pane.
            self._attach(busy[0])
            return None

        moved = free or self._sessions.create(
            session.base,
            session.workflow,
            steps=dict(session.steps),
            preset=dict(session.preset),
        )
        moved.steps = dict(session.steps)
        moved.answers = dict(session.answers)
        moved.preset = dict(session.preset)
        moved.foreground = session.foreground
        # The worker follows the workflow. Left on the tab behind, Stop and
        # quit would reach for this run through a session it has walked out of.
        moved.task, session.task = session.task, None
        if not session.ran:
            self._sessions.remove(session)
        CURRENT_SESSION.set(moved)
        return moved

    def _free_at(self, place: tuple[str, ...]) -> RunSession | None:
        """A tab in this context with no workflow behind it, if there is one.

        Oldest first, so coming back twice lands on the same tab rather than
        wandering through them.
        """
        return next(
            (s for s in self._sessions.visible(place) if s.task is None), None
        )

    async def run_in_panel(self, work: Awaitable[T]) -> T | None:
        session = current_session()
        if session is None or not session.panel_open:
            return await work

        task = asyncio.ensure_future(work)
        session.work = task
        session.changed()
        try:
            return await task
        except asyncio.CancelledError:
            # Stop cancels this task and nothing else. Anything else cancelling
            # it is the app shutting down, which has to keep unwinding — and
            # take the work down with it.
            task.cancel()
            if not session.stop_requested:
                raise
            return None
        except Exception as error:
            # The panel reports it and the user reads it there. Letting it out
            # would kill the worker running the workflow, take its output with
            # it, and lose everything that led up to the failure.
            session.report_failure(error)
            return None
        finally:
            session.work = None
            session.changed()

    def panel_failure(self) -> str:
        session = current_session()
        return session.failure if session is not None else ""

    async def close_run_panel(self, message: str = "", ok: bool = True) -> bool:
        session = current_session()
        if session is None or not session.panel_open:
            return False

        session.finish(message, ok)
        if await session.wait_for_next():
            session.reset()
            self._refresh_panel()
            return True

        session.panel_open = False
        session.result_acknowledged = True
        if session.task is None:
            # Nothing is going to run out and retire this one, so closing its
            # panel is the end of it — otherwise it sits in the strip forever
            # as a run that never finishes.
            self._retire(session)
            return False
        if self._attached is session:
            self._detach()
        else:
            self._refresh_panel()
        return False

    # ---------------------------------------------------------- attach/detach

    def _attach(self, session: RunSession) -> None:
        previous = self._attached
        if previous is not None and previous is not session:
            # Whatever it was doing carries on; it just stops being the thing
            # holding the screen.
            self._background(previous)
        self._attached = session
        session.foreground = True

        panel = self._panel
        if panel is not None and panel in self.screen_stack:
            panel.show(session)
        else:
            self._panel = RunScreen(session, self._sessions)
            self.push_screen(self._panel)

        self._signal_attachment()
        self._settle()
        self._refresh_badges()

    def _detach(self) -> None:
        """Take the panel off the screen, and nothing more.

        Deliberately not the same thing as backgrounding the session. A run
        whose panel closes because the user backed out of the form is still
        mid-workflow and about to put a menu of its own up; freeing the menu
        loop here would push a second one over the top of it, which is two
        owners of one screen stack.
        """
        self._attached = None
        panel = self._panel
        if panel is not None and self.screen is panel:
            self.pop_screen()
            self._panel = None
        self._signal_attachment()
        self._settle()
        self._refresh_badges()

    def _background(self, session: RunSession) -> None:
        """This run no longer wants the screen, which is what frees the menu."""
        session.foreground = False
        self._settle()

    def _signal_attachment(self) -> None:
        self._attachment.set()
        self._attachment = asyncio.Event()

    def _settle(self) -> None:
        busy = self._attached is not None or any(
            session.foreground for session in self._sessions.all()
        )
        if busy:
            self._foreground_free.clear()
        else:
            self._foreground_free.set()

    async def _claim_screen(self, session: RunSession | None) -> None:
        """Hold until a screen pushed from here would land on top."""
        while self._attached is not None and self._attached is not session:
            await self._attachment.wait()
        if self._attached is session and session is not None:
            self._detach()

    def _refresh_panel(self) -> None:
        if self._panel is not None and self._attached is not None:
            self._panel.render_state()
        self._refresh_badges()

    def _session_changed(self, session: RunSession | None) -> None:
        self._refresh_panel()

    @property
    def runs_summary(self) -> str:
        return self._sessions.summary()

    def _refresh_badges(self) -> None:
        summary = self._sessions.summary()
        for screen in self.screen_stack:
            for header in screen.query(AppHeader):
                header.show_runs(summary)
            if isinstance(screen, CardMenuScreen):
                screen.show_runs(summary)
                screen.show_counts(self._sessions.running_under)

    # ------------------------------------------------- what the panel reports

    def on_run_screen_chosen(self, message: RunScreen.Chosen) -> None:
        self._attach(message.session)

    def on_run_screen_detached(self, message: RunScreen.Detached) -> None:
        # The one gesture that means "leave it running": the run gives up the
        # screen, and the menu it came from comes back.
        session = self._attached
        self._detach()
        if session is None:
            return
        # Before backgrounding, not after: freeing the foreground with nothing
        # else holding it releases the menu loop, and the top menu it puts up
        # would land under whatever is opened here a moment later. And only
        # when nothing else is already waiting for the screen — a workflow that
        # walked in on this run is holding its own menu ready, and a second one
        # would land on top of it.
        if not any(s.foreground for s in self._sessions.all() if s is not session):
            self._resume_behind(session)
        self._background(session)

    def _resume_behind(self, session: RunSession) -> RunSession | None:
        """Put the menu this run was started from back up, still one step in.

        Esc means one step back, not "out to the top" — the run carries on in
        its own tab, and what the user lands on is the menu that chose it, so
        starting another is picking a different stack rather than walking in
        from the front again. A workflow with no menu behind its panel has no
        step to go back to, and leaving is the whole of what Esc can mean there.
        """
        steps = dict(session.steps)
        if len(steps) < 2:
            return None
        answers = dict(session.answers)
        last = next(reversed(steps))
        steps.pop(last)
        answers.pop(last, None)
        resumed = self._sessions.create(
            session.base, session.workflow, steps=steps, preset=answers
        )
        self._spawn(resumed)
        return resumed

    def on_run_screen_added(self, message: RunScreen.Added) -> None:
        parent = self._attached
        if parent is None:
            return
        # Another one of these, not another walk through the same three menus:
        # the sibling inherits what every step already answered.
        session = self._sessions.create(
            parent.base,
            parent.workflow,
            steps=dict(parent.steps),
            preset=dict(parent.answers),
        )
        self._spawn(session)
        self._attach(session)

    def on_run_screen_closed(self, message: RunScreen.Closed) -> None:
        self._close_session(message.session)

    def on_run_screen_renamed(self, message: RunScreen.Renamed) -> None:
        self._rename_session(message.session)

    @work
    async def _close_session(self, session: RunSession) -> None:
        if session.status.live and not await self.push_screen_wait(
            ConfirmScreen(
                f"'{session.name}' is still running. Stop it and close the tab?",
                self.trail_label(),
            )
        ):
            return
        # The neighbour takes the screen first, so the panel is handed over
        # rather than torn down and rebuilt — and so unwinding the closed run
        # cannot find itself still attached and pop the panel out from under it.
        if self._attached is session:
            neighbour = self._neighbour(session)
            if neighbour is not None:
                self._attach(neighbour)
        await self._stop_run(session)
        if self._attached is session:
            self._detach()

    def _neighbour(self, session: RunSession) -> RunSession | None:
        shown = self._sessions.visible(session.scope)
        rest = [other for other in shown if other is not session]
        return rest[0] if rest else None

    @work
    async def _rename_session(self, session: RunSession) -> None:
        name = await self.push_screen_wait(
            InputScreen(f"Rename '{session.name}' to", self.trail_label())
        )
        self._sessions.rename(session, name)
        self._refresh_panel()

    # ------------------------------------------------------- coming back to it

    def action_resume_runs(self) -> None:
        """Back into whatever is still going, from wherever the user is."""
        if isinstance(self.screen, ModalScreen) or self._attached is not None:
            return
        self._pick_run()

    @work
    async def _pick_run(self) -> None:
        """Show everything in flight and go to whichever one is chosen.

        Each context keeps its own strip, so no strip can list them all — and
        going straight to whichever run seemed most urgent was a guess made on
        the user's behalf about which one they meant.
        """
        waiting = self._resumable()
        if not waiting:
            return
        session = await self.push_screen_wait(RunsScreen(waiting))
        if session is not None and session in self._sessions.all():
            self._attach(session)

    def _resumable(self) -> tuple[RunSession, ...]:
        """Runs there is something to go back to, most wanting attention first.

        Only sessions with a form on them. A workflow part-way through its
        menus owns a session too, and it has nothing to show — going to one
        puts up a run panel with an empty configuration pane.
        """
        order = ("asking", "failed", "done", "running", "idle")
        return tuple(
            sorted(
                (s for s in self._sessions.all() if s.panel_open),
                key=lambda s: order.index(s.status.value),
            )
        )

    # -------------------------------------------------------------- shutdown

    def action_leave(self) -> None:
        self._leave()

    @work
    async def _leave(self) -> None:
        if not await self._confirm_quit():
            return
        await self._stop_every_run()
        self.exit()

    async def _confirm_quit(self, deliberate: bool = True) -> bool:
        """Nothing leaves the app on a keystroke that could have meant something else.

        Quitting on top of live runs is N directories abandoned rather than one,
        so that is always named before anything is thrown away. With nothing
        going, only the quit chords go straight out: Esc is a navigation key, and
        the press that walks out of the last menu is one further than the user
        was aiming — mash it and the app should still be there.
        """
        live = self._sessions.live()
        if live:
            return await self._ask_quit(f"{len(live)} {QUIT_WITH_RUNS}")
        if deliberate:
            return True
        return await self._ask_quit(QUIT_CONFIRM)

    async def _ask_quit(self, prompt: str) -> bool:
        return await self.push_screen_wait(ConfirmScreen(prompt, self.trail_label()))

    async def _stop_every_run(self) -> None:
        """N tasks to unwind and N subprocesses to kill, not one of each.

        The single-run path already did this correctly; it only had to fan out.
        """
        for session in self._sessions.all():
            await self._stop_run(session)

    async def _stop_run(self, session: RunSession) -> None:
        """Take the whole workflow down, not just the slow thing inside it.

        Deliberately not `request_stop`: that is the user saying "stop this run"
        and the workflow is meant to survive it and report the stop. Here the
        workflow itself is going away, so the cancellation has to travel all the
        way out rather than being caught and recovered from.
        """
        worker = session.task
        if worker is not None and not worker.is_finished:
            worker.cancel()
            with suppress(Exception):
                await worker.wait()
        self._sessions.remove(session)

    # ---------------------------------------------------------------- menus

    def trail_label(self) -> str:
        return TRAIL_SEPARATOR.join(self._current_steps().values())

    def _current_steps(self) -> dict[str, str]:
        session = current_session()
        return session.steps if session is not None else self._steps

    def _enter_step(self, step: str) -> tuple[str, ...]:
        """Forget this step and everything downstream, then return what precedes it.

        Re-asking a step means its old answer is being replaced, so the trail
        corrects itself without the caller having to say it went backwards.
        """
        steps = self._current_steps()
        for later in TRAIL_STEPS[TRAIL_STEPS.index(step) :]:
            steps.pop(later, None)
        return tuple(steps.values())

    def _record(self, step: str, name: str, chosen: object) -> None:
        steps = self._current_steps()
        steps[step] = name
        session = current_session()
        if session is not None:
            session.answers[step] = chosen

    def _entry(
        self, trail: tuple[str, ...], key: str, name: str, description: str
    ) -> MenuEntry:
        """One card, told what is still going on behind it.

        Where the card leads is where the menu stands plus the card's own name,
        which is exactly the context a run started there would belong to. With
        a strip per context that is the only thing telling the user a run they
        left is down this way — the strip they are looking at will not.
        """
        return MenuEntry(key, name, description, self._sessions.running_under((*trail, name)))

    def _replay(self, step: str) -> object | None:
        """The answer a sibling session inherited for this step, if it has one."""
        session = current_session()
        if session is None:
            return None
        return session.preset.pop(step, None)

    async def choose_capability(
        self,
        capabilities: Sequence[Capability],
    ) -> Capability | None:
        session = current_session()
        # A workflow that was stopped never reached its pause, so the flag it
        # left behind is cleared here rather than swallowing the next one.
        self._result_acknowledged = False
        self._quiet_output()
        if session is not None:
            session.result_acknowledged = False
        await self._claim_screen(session)
        trail = self._enter_step("capability")
        index = await self.push_screen_wait(
            CardMenuScreen(
                "What would you like to do?",
                [
                    self._entry(
                        trail, item.info.key, item.info.name, item.info.description
                    )
                    for item in capabilities
                ],
                subtitle="Choose a workflow to get started.",
                back_label="Quit",
                trail=trail,
                runs=self._sessions.summary(),
            )
        )
        if index is None:
            # Leaving here is leaving for good, so anything still going gets
            # named before it is thrown away rather than after — and so does
            # leaving at all, because Esc got here by walking rather than by
            # being aimed.
            if await self._confirm_quit(deliberate=False):
                return None
            return await self.choose_capability(capabilities)
        self._record("capability", capabilities[index].info.name, capabilities[index])
        return capabilities[index]

    async def choose_scaffold_target(
        self,
        options: Sequence[ScaffoldTargetOption],
        notice: str = "",
    ) -> ScaffoldTarget | None:
        inherited = self._replay("scaffold_target")
        match = next((o for o in options if o.target is inherited), None)
        if match is not None:
            self._record("scaffold_target", match.name, match.target)
            return match.target

        await self._claim_screen(current_session())
        trail = self._enter_step("scaffold_target")
        index = await self.push_screen_wait(
            CardMenuScreen(
                "What do you want to scaffold?",
                [
                    self._entry(
                        trail, option.target.value, option.name, option.description
                    )
                    for option in options
                ],
                subtitle="Pick what the template pack should generate.",
                trail=trail,
                notice=notice,
                runs=self._sessions.summary(),
            )
        )
        if index is None:
            return None
        self._record(
            "scaffold_target", options[index].name, options[index].target
        )
        return options[index].target

    async def choose_template_pack(
        self,
        packs: Sequence[TemplatePack],
        notice: str = "",
    ) -> TemplatePack | None:
        inherited = self._replay("template_pack")
        if inherited in packs:
            pack = next(p for p in packs if p is inherited)
            self._record("template_pack", pack.info.name, pack)
            return pack

        await self._claim_screen(current_session())
        trail = self._enter_step("template_pack")
        index = await self.push_screen_wait(
            CardMenuScreen(
                "Choose a stack",
                [
                    self._entry(
                        trail, pack.info.key, pack.info.name, pack.info.description
                    )
                    for pack in packs
                ],
                subtitle="Every stack ships as a versioned template pack.",
                trail=trail,
                notice=notice,
                runs=self._sessions.summary(),
            )
        )
        if index is None:
            return None
        self._record("template_pack", packs[index].info.name, packs[index])
        return packs[index]

    async def pause(self) -> None:
        session = current_session()
        if session is not None:
            if session.result_acknowledged:
                session.result_acknowledged = False
                return
        elif self._result_acknowledged:
            self._result_acknowledged = False
            return
        await self._claim_screen(session)
        await self.push_screen_wait(ContinueScreen())


async def _nothing() -> None:
    """A session with no workflow of its own behind it."""
    return None
