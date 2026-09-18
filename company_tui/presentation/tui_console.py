"""The interactive Textual front end, and the owner of every run in flight."""

import asyncio
from collections.abc import Awaitable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TypeVar

from textual import events, work
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import RichLog

from company_tui.application.app import Application
from company_tui.application.updates import UpdateWatch
from company_tui.domain import naming
from company_tui.domain.capability import Capability
from company_tui.domain.interactive import Listing, ListView
from company_tui.domain.layout import Layout
from company_tui.domain.options import Option, OptionValue
from company_tui.domain.recent import RecentPathsPort
from company_tui.domain.script_config import (
    ScriptAction,
    ScriptCatalogue,
    ScriptSection,
    ScriptUpdate,
)
from company_tui.domain.session_memory import SessionMemory
from company_tui.domain.template_pack import (
    ScaffoldTarget,
    ScaffoldTargetOption,
    TemplatePack,
)
from company_tui.domain.updates import NOTHING_TO_REPORT, UpdateReport
from company_tui.infrastructure.terminal_window import restore_terminal_interaction
from company_tui.infrastructure.window_shape import (
    AppWindow,
    SizeGuard,
    WindowPlan,
    cramped,
    current_window,
    plan_from,
    window_plan,
)
from company_tui.presentation.branding import (
    APP_NAME,
    APP_TAGLINE,
    APP_VERSION,
    PEAK_ART,
    theme_from,
)
from company_tui.presentation.browser_screen import BrowserScreen
from company_tui.presentation.card import MenuEntry
from company_tui.presentation.chrome import AppFooter, AppFrame, AppHeader, BusyLine
from company_tui.presentation.path_screen import PathScreen
from company_tui.presentation.run_screen import RunScreen
from company_tui.presentation.screens import (
    TRAIL_SEPARATOR,
    CardMenuScreen,
    ConfirmScreen,
    ContinueScreen,
    InputScreen,
    InstallingScreen,
    PickScreen,
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
from company_tui.presentation.ui import RefreshRunner

TRAIL_STEPS = (
    "capability",
    "scaffold_target",
    "template_pack",
    "script_section",
    "script_action",
)
"""Every menu a workflow can walk, in the order it walks them."""

SCRIPT_UPDATE_ANSWERS: tuple[tuple[str, str, str, str], ...] = (
    (
        ScriptUpdate.RECLONE.value,
        "Re-clone",
        "Replace the copy in the store",
        "Deletes the store copy and clones it again — anything edited there goes with it.",
    ),
    (
        ScriptUpdate.KEEP.value,
        "Keep this copy",
        "Carry on with what is installed",
        "Runs the version in the store. Asked again next time you come through here.",
    ),
    (
        ScriptUpdate.SILENCE.value,
        "Stop asking",
        "Keep it, and never check again",
        "Written to your settings, where it can be turned back on. Skips the check entirely.",
    ),
)
"""Key, name, card line and focus line for each way out of a stale store."""

RAW_OUTPUT_PREFIX = "  "
"""Marks a line as verbatim output from a subprocess rather than the toolbox."""

QUIT_CONFIRM = f"Quit {APP_NAME}?"
QUIT_DETAIL = (
    "Are you sure you want to close the toolbox?\nNothing is running right now."
)
QUIT_WITH_RUNS = (
    "Are you sure you want to close the toolbox?\n"
    "{count} still going — every one of them will be stopped."
)
"""What quitting costs, spelled out rather than left to the title."""

QUIT_ANSWER = f"QUIT {APP_NAME}"

CLOSE_TAB_CONFIRM = "Close this tab?"
CLOSE_TAB_DETAIL = "'{name}' is still running.\nClosing the tab stops it."
CLOSE_TAB_ANSWER = "CLOSE TAB"

BUSY_DELAY = 0.25
"""How long a step has to take before the app says it is working on it."""

INSTALL_PAUSE = 1.2
"""How long the installing screen is held before the app actually goes."""

WINDOW_POLL_INTERVAL = 0.2
"""How often the window is measured."""

WINDOW_NOTICE = "▲ window {width}x{height} → {floor_width}x{floor_height}"
"""Said in the header while the window is smaller than the layout wants."""

UPDATE_MARK = "▲"
"""The glyph on the update badge. Geometric Shapes, like every other mark drawn."""

UPDATE_CONFIRM = "Install the update?"
UPDATE_DETAIL = (
    "{version} replaces {installed}.\n"
    "The toolbox will close, update itself, and reopen."
)
UPDATE_ANSWER = "INSTALL AND RESTART"
"""What saying yes costs, spelled out."""

UPDATE_DECLINED = "Left alone - nothing was installed."

UPDATE_RUNS = "\n{count} other run{s} will be stopped."
"""Added to the card's install question, where a run is the one asking."""

UPDATE_RUNS_ALL = "\n{count} run{s} will be stopped."
"""The same for the chord, where nothing is asking and none of them is "other"."""
NO_INSTALLER_AT = "There is no installer at {path} any more."

NOTHING_TO_INSTALL = "Nothing to install - no newer build has been downloaded."
"""Ctrl+U pressed with no badge up."""

UPDATE_FAILED = "The update could not be started: {problem}"
"""Said in the activity log rather than in a dialog."""

T = TypeVar("T")


class TuiConsole(App):
    """The interactive front end, and the owner of every run in flight."""

    TITLE = f"{PEAK_ART}  {APP_NAME} — {APP_TAGLINE}"
    SUB_TITLE = APP_VERSION
    BINDINGS = [
        ("ctrl+q", "leave", "Quit"),
        ("ctrl+c", "leave", "Quit"),
        ("ctrl+b", "resume_runs", "Runs"),
        ("ctrl+u", "install_update", "Update"),
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

    def __init__(
        self,
        workspace_label: str | None = None,
        memory: SessionMemory | None = None,
        workspace: str = "",
        watch: UpdateWatch | None = None,
        recent: RecentPathsPort | None = None,
        layout: Layout | None = None,
    ) -> None:
        super().__init__()
        self.application: Application | None = None
        self.start_capability = ""
        """A capability to open on instead of the menu. See Ui.choose_capability."""
        self.workspace_label = workspace_label
        self._layout = layout if layout is not None else Layout()
        """Colours, window size and how wide the card grid is. Read once, here:
        a floor or a palette that moved under a window somebody had settled would
        be the interface rearranging itself while they were using it."""
        self._memory = memory
        self._recent = recent
        """The directories picked before, or None where there is nothing to remember."""
        self._watch = watch
        """The launch-time update check, or None where there is nothing to check."""
        self._workspace = workspace
        """Which project's tabs these are. One machine holds several, and the."""
        self.result_code = 0
        self._steps: dict[str, str] = {}
        self._sessions = SessionRegistry(on_change=self._session_changed)
        self._panel: RunScreen | None = None
        self._attached: RunSession | None = None
        self._browser: BrowserScreen | None = None
        self._browser_task: asyncio.Future | None = None
        self._browser_stopped = False
        self._foreground_free = asyncio.Event()
        self._foreground_free.set()
        self._attachment = asyncio.Event()
        self._result_acknowledged = False
        self._window: AppWindow | None = None
        self._window_watch: Timer | None = None
        self._window_notice = ""
        self._update_notice = ""
        self._update: UpdateReport = NOTHING_TO_REPORT
        """What the launch check found. Empty until it has answered, and empty."""
        self._plan: WindowPlan = plan_from(self._layout.window)
        self._guard: SizeGuard | None = None
        self._leaving = False
        """Set once the app is on its way out, so the menu loop stops asking."""

    def compose(self) -> ComposeResult:
        with AppFrame():
            yield AppHeader()
            yield BusyLine(id="busy")
            yield RichLog(id="output", wrap=True, markup=True, classes="-quiet")
            yield AppFooter([("Ctrl+Q", "Quit")])

    def on_mount(self) -> None:
        self.register_theme(theme_from(self._layout.palette))
        self.theme = naming.APP_SLUG
        output = self.query_one("#output", RichLog)
        output.border_title = "Activity"
        self._watch_window_shape()
        self._recall()
        self._look_for_update()
        self._start()


    def _recall(self) -> None:
        """Put back the tabs the last run of the app left open."""
        if self._memory is None:
            return
        for remembered in self._memory.remembered(self._workspace):
            self._sessions.restore(remembered, _nothing)

    def _remember(self) -> None:
        """Write the tabs down, at the points where there is something new."""
        if self._memory is None:
            return
        self._memory.remember(self._workspace, self._sessions.remembered())


    def _watch_window_shape(self) -> None:
        """Open the window at its size, then start reporting on it."""
        if self._driver is None or self.is_headless:
            return
        self._window = current_window()
        if self._window is None:
            return
        self._plan = window_plan(plan_from(self._layout.window))
        self._guard = SizeGuard(self._window, self._plan)
        self._guard.open_at_start_size()
        self._check_window_shape()
        self._window_watch = self.set_interval(WINDOW_POLL_INTERVAL, self._check_window_shape)

    def _check_window_shape(self) -> None:
        window = self._window
        if window is None:
            return
        state = window.state()
        if state is None:
            self._window = None
            self._guard = None
            self._stop_watching_window()
            self._say_about_window("")
            return
        if self._guard is not None and self._guard.hold(state):
            return
        if not cramped(state, self._plan):
            self._say_about_window("")
            return
        self._say_about_window(
            WINDOW_NOTICE.format(
                width=state.width,
                height=state.height,
                floor_width=self._plan.min_width,
                floor_height=self._plan.min_height,
            )
        )


    @work
    async def _look_for_update(self) -> None:
        """Ask, once, in the background, and say nothing unless there is an answer."""
        if self._watch is None:
            return
        report = await self._watch.look()
        self._update = report
        self._say_about_update(report.notice(UPDATE_MARK))

    def _say_about_update(self, notice: str) -> None:
        """Put the notice in every header, and only when it has changed."""
        if notice == self._update_notice:
            return
        self._update_notice = notice
        for screen in self.screen_stack:
            for header in screen.query(AppHeader):
                header.show_update(notice)

    @property
    def update_notice(self) -> str:
        """What a header composed after the fact should show. See `AppHeader`."""
        return self._update_notice

    async def install_update(self, installer: str, version: str) -> str:
        """`Ui.install_update`. Ask, then hand over from a worker of this app's own."""
        if self._watch is None:
            return "update installing is not configured"
        target = Path(installer)
        if not target.is_file():
            return NO_INSTALLER_AT.format(path=installer)

        detail = UPDATE_DETAIL.format(version=version, installed=APP_VERSION)
        session = current_session()
        others = [live for live in self._sessions.live() if live is not session]
        if others:
            detail += UPDATE_RUNS.format(
                count=len(others), s="" if len(others) == 1 else "s"
            )

        answer = await self.push_screen_wait(
            ConfirmScreen(
                UPDATE_CONFIRM,
                self.trail_label(),
                detail=detail,
                confirm=UPDATE_ANSWER,
            )
        )
        if not answer:
            return UPDATE_DECLINED

        problem = self._watch.arm(target)
        if problem:
            return problem
        self._leave_for_update(version)
        return ""

    @work
    async def _leave_for_update(self, version: str) -> None:
        await self._leaving_for_update(version)

    async def _leaving_for_update(self, version: str) -> None:
        """Say what is happening, hold it long enough to be read, then go."""
        await self.push_screen(InstallingScreen(version))
        await asyncio.sleep(INSTALL_PAUSE)
        await self._shut_down()
        self.exit()

    def action_install_update(self) -> None:
        self._install_update()

    @work
    async def _install_update(self) -> None:
        """Hand the machine over to the installer, then get out of its way."""
        if self._watch is None:
            return
        if not self._update.waiting:
            report = await self._watch.look()
            self._update = report
            self._say_about_update(report.notice(UPDATE_MARK))
        if not self._update.waiting:
            self.write(NOTHING_TO_INSTALL)
            return
        detail = UPDATE_DETAIL.format(
            version=self._update.available.text or self._update.tag,
            installed=APP_VERSION,
        )
        live = self._sessions.live()
        if live:
            detail += UPDATE_RUNS_ALL.format(count=len(live), s="" if len(live) == 1 else "s")
        answer = await self.push_screen_wait(
            ConfirmScreen(
                UPDATE_CONFIRM,
                self.trail_label(),
                detail=detail,
                confirm=UPDATE_ANSWER,
                key=AppHeader.UPDATE_HINT,
            )
        )
        if not answer:
            return
        problem = self._watch.hand_over(self._update)
        if problem:
            self.write(UPDATE_FAILED.format(problem=problem))
            return
        await self._leaving_for_update(self._update.available.text or self._update.tag)

    def _stop_watching_window(self) -> None:
        if self._window_watch is not None:
            self._window_watch.stop()
            self._window_watch = None

    def _say_about_window(self, notice: str) -> None:
        """Put the notice in every header, and only when it has changed."""
        if notice == self._window_notice:
            return
        self._window_notice = notice
        for screen in self.screen_stack:
            for header in screen.query(AppHeader):
                header.show_window(notice)

    @property
    def window_notice(self) -> str:
        """What a header composed after the fact should show. See `AppHeader`."""
        return self._window_notice

    def _write_to_terminal(self, data: str) -> None:
        """Send an escape sequence the way Textual sends its own."""
        driver = self._driver
        if driver is None:
            return
        driver.write(data)
        driver.flush()

    def _clear_pointer_state(self) -> None:
        """Discard pointer state that a focus change can strand mid-gesture."""
        self.capture_mouse(None)
        self._set_mouse_over(None, None)
        self._end_text_selection()

    def _end_text_selection(self) -> None:
        """Abandon a drag-selection rather than let it outlive the window."""
        for screen in self.screen_stack:
            screen.clear_selection()
            screen._selecting = False
            screen._mouse_down_offset = None

    def on_app_blur(self, event: events.AppBlur) -> None:
        self._clear_pointer_state()

    def on_app_focus(self, event: events.AppFocus) -> None:
        restore_terminal_interaction(self._write_to_terminal)
        self._clear_pointer_state()
        self.call_after_refresh(self._repaint_everything)

    def _repaint_everything(self) -> None:
        for screen in self.screen_stack:
            screen.refresh(repaint=True, layout=True)

    @work
    async def _start(self) -> None:
        await self.push_screen_wait(SplashScreen())
        assert self.application is not None  # noqa: S101 - narrowing; bootstrap sets it
        self.result_code = await self.application.run(self.start_capability)
        await self._shut_down()
        self.exit()


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
        """Nothing to look at again, ready for the next workflow."""
        for log in self.query("#output").results(RichLog):
            log.clear()
            log.add_class("-quiet")

    @staticmethod
    def _marker_for(message: str) -> str:
        """Two conventions, both readable in the plain console too: a line."""
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


    def list_view(self) -> "ListView":
        """A view bound to this console, for a command that speaks the protocol."""
        return _PanelListView(self)

    def browser_view(self) -> "ListView | None":
        """A view over the browser now on screen, or `None` when there is none.

        `None` is what makes the gate one place: a run that did not open a browser
        falls back to the ordinary list protocol without anything here knowing why.
        """
        screen = self._browser
        return None if screen is None else _BrowserListView(self, screen)

    async def browse(
        self,
        title: str,
        work: Awaitable[T],
        trail: Sequence[str] = (),
        subtitle: str = "",
    ) -> T | None:
        """Put the browser up, run `work` behind it, and take it down after.

        No form and no terminal: there is nothing to configure and nothing to
        stream, so the screen is the whole surface and Esc is the only way out of
        it. Esc cancels `work`, which unwinds to the subprocess like every other
        stopped run here.
        """
        session = current_session()
        await self._claim_screen(session)

        steps = tuple(session.steps.values()) if session is not None else ()
        screen = BrowserScreen(title, trail or steps, subtitle)
        self._browser = screen
        self._browser_stopped = False
        await self.push_screen(screen)

        task = asyncio.ensure_future(work)
        self._browser_task = task
        try:
            return await task
        except asyncio.CancelledError:
            task.cancel()
            if not self._browser_stopped:
                raise
            return None
        finally:
            self._browser = None
            self._browser_task = None
            with suppress(Exception):
                while screen in self.screen_stack:
                    self.pop_screen()
            self._refresh_badges()

    def on_browser_screen_stopped(self, message: BrowserScreen.Stopped) -> None:
        """Esc on the browser. What ends is the run, not just the screen."""
        message.stop()
        self._browser_stopped = True
        if self._browser_task is not None:
            self._browser_task.cancel()

    async def ask_text(
        self, prompt: str, value: str = "", multiline: bool = False
    ) -> str:
        """One text field over whatever is up. Empty is a cancel, and says so."""
        return await self.push_screen_wait(
            InputScreen(prompt, self.trail_label(), value, multiline)
        )

    async def show_rows(self, listing: Listing) -> str | None:
        """Put a listing up and wait. The pick is the row's own id, or None for Esc.

        A run is already a worker, which is what `push_screen_wait` needs — the same
        reason `ask` and `confirm` can stop mid-workflow and wait for an answer.
        """
        return await self.push_screen_wait(PickScreen(listing))

    def close_rows(self) -> None:
        """Take a listing off the screen if one is still up.

        Only reached when the command said `@dti:end` or the run ended, and in both
        cases the usual way a listing leaves is somebody answering it.
        """
        screen = self.screen if self.screen_stack else None
        if isinstance(screen, PickScreen):
            with suppress(Exception):
                screen.dismiss(None)

    async def working(self, label: str, work: Awaitable[T]) -> T:
        """Do `work` with the app saying so, for a step that has no panel."""
        task = asyncio.ensure_future(work)
        try:
            done, _pending = await asyncio.wait({task}, timeout=BUSY_DELAY)
            if task in done:
                return task.result()
            self._show_busy(label)
            try:
                return await task
            finally:
                self._show_busy("")
        except asyncio.CancelledError:
            task.cancel()
            raise

    def _show_busy(self, label: str) -> None:
        for line in self.query("#busy").results(BusyLine):
            line.show(label)


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
            CURRENT_SESSION.set(session)
            try:
                await session.workflow()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the run supervisor; it reports
                self._here(session).report_failure(error)
            finally:
                self._retire(self._here(session))

        session.foreground = True
        session.task = self.run_worker(
            run(), name=session.name, group="session", exit_on_error=False
        )
        self._settle()

    @staticmethod
    def _here(started_in: RunSession) -> RunSession:
        """The session a workflow is using now, which is not always the one it."""
        return current_session() or started_in

    def _retire(self, session: RunSession) -> None:
        """The workflow is over. Whether the tab goes with it depends."""
        session.panel_open = False
        session.task = None
        self._remember()
        self._background(session)
        if not session.ran:
            self._sessions.remove(session)
        if self._attached is session:
            self._detach_session()
        else:
            self._settle()
            self._refresh_panel()

    async def open_run_panel(
        self,
        title: str,
        options: Sequence[Option],
        trail: Sequence[str] = (),
        refresh: RefreshRunner | None = None,
        preview: object = None,
        subtitle: str = "",
    ) -> dict[str, OptionValue] | None:
        session = current_session()
        if session is None:
            session = self._sessions.create(title, _nothing, steps=dict(self._steps))
            CURRENT_SESSION.set(session)
        else:
            session = self._relocate(session)
            if session is None:
                return None
        if not session.panel_open:
            session.load(
                title,
                options,
                trail or tuple(session.steps.values()),
                refresh,
                preview,
                subtitle,
            )
        self._attach_session(session)

        values = await session.wait_for_values()
        if values is None:
            session.panel_open = False
            if self._attached is session:
                self._detach_session()
            return None
        return values

    def _relocate(self, session: RunSession) -> RunSession | None:
        """The session for where the workflow is now, which may not be this one."""
        if session.scope == session.place:
            return session

        free = self._free_at(session.place)
        busy = tuple(s for s in self._sessions.visible(session.place) if s.panel_open)
        if free is None and busy:
            self._attach_session(busy[0])
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
        session.foreground = False
        self._teach(session.place, session.workflow)
        moved.task, session.task = session.task, None
        if not session.ran:
            self._sessions.remove(session)
        CURRENT_SESSION.set(moved)
        return moved

    def _teach(self, place: tuple[str, ...], workflow: Workflow) -> None:
        """Hand this context's workflow to every tab in it that is idle."""
        for tab in self._sessions.visible(place):
            if tab.task is None:
                tab.workflow = workflow

    def _free_at(self, place: tuple[str, ...]) -> RunSession | None:
        """A tab in this context with no workflow behind it, if there is one."""
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
            task.cancel()
            if not session.stop_requested:
                raise
            return None
        except Exception as error:  # noqa: BLE001 - the run supervisor; it reports
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
            self._retire(session)
            return False
        if self._attached is session:
            self._detach_session()
        else:
            self._refresh_panel()
        return False


    def _attach_session(self, session: RunSession) -> None:
        previous = self._attached
        if previous is not None and previous is not session:
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

    def _detach_session(self) -> None:
        """Take the panel off the screen, and nothing more."""
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
            self._detach_session()

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


    def on_run_screen_chosen(self, message: RunScreen.Chosen) -> None:
        self._attach_session(message.session)

    def on_run_screen_detached(self, message: RunScreen.Detached) -> None:
        session = self._attached
        self._detach_session()
        if session is None:
            return
        if not any(s.foreground for s in self._sessions.all() if s is not session):
            self._resume_behind(session)
        self._background(session)

    def _resume_behind(self, session: RunSession) -> RunSession | None:
        """Put the menu this run was started from back up, still one step in."""
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
        session = self._sessions.create(
            parent.base,
            parent.workflow,
            steps=dict(parent.steps),
            preset=dict(parent.answers),
        )
        self._spawn(session)
        self._attach_session(session)

    def on_run_screen_closed(self, message: RunScreen.Closed) -> None:
        self._close_session(message.session)

    def on_run_screen_renamed(self, message: RunScreen.Renamed) -> None:
        self._rename_session(message.session)

    @work
    async def _close_session(self, session: RunSession) -> None:
        if session.status.live and not await self.push_screen_wait(
            ConfirmScreen(
                CLOSE_TAB_CONFIRM,
                self.trail_label(),
                detail=CLOSE_TAB_DETAIL.format(name=session.name),
                confirm=CLOSE_TAB_ANSWER,
            )
        ):
            return
        if self._attached is session:
            neighbour = self._neighbour(session)
            if neighbour is not None:
                self._attach_session(neighbour)
        await self._stop_run(session)
        if self._attached is session:
            self._detach_session()
        self._remember()

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
        self._remember()


    def action_resume_runs(self) -> None:
        """Back into whatever is still going, from wherever the user is."""
        if isinstance(self.screen, ModalScreen) or self._attached is not None:
            return
        self._pick_run()

    @work
    async def _pick_run(self) -> None:
        """Show everything in flight and go to whichever one is chosen."""
        waiting = self._resumable()
        if not waiting:
            return
        session = await self.push_screen_wait(RunsScreen(waiting))
        if session is not None and session in self._sessions.all():
            self._attach_session(session)

    def _resumable(self) -> tuple[RunSession, ...]:
        """Runs there is something to go back to, most wanting attention first."""
        order = ("asking", "failed", "done", "running", "idle")
        return tuple(
            sorted(
                (s for s in self._sessions.all() if s.panel_open),
                key=lambda s: order.index(s.status.value),
            )
        )


    def action_leave(self) -> None:
        self._leave()

    @work
    async def _leave(self) -> None:
        if not await self._confirm_quit():
            return
        await self._shut_down()
        self.exit()

    async def _confirm_quit(self, deliberate: bool = True) -> bool:
        """Nothing leaves the app on a keystroke that could have meant something else."""
        live = self._sessions.live()
        if live:
            count = f"{len(live)} run{'s are' if len(live) > 1 else ' is'}"
            return await self._ask_quit(QUIT_WITH_RUNS.format(count=count))
        if deliberate:
            return True
        return await self._ask_quit(QUIT_DETAIL)

    async def _ask_quit(self, detail: str) -> bool:
        return await self.push_screen_wait(
            ConfirmScreen(
                QUIT_CONFIRM,
                self.trail_label(),
                detail=detail,
                confirm=QUIT_ANSWER,
            )
        )

    async def _shut_down(self) -> None:
        """Write the tabs down, then take the runs down — in that order."""
        self._leaving = True
        self._remember()
        await self._stop_every_run()

    async def _stop_every_run(self) -> None:
        """N tasks to unwind and N subprocesses to kill, not one of each."""
        for session in self._sessions.all():
            await self._stop_run(session)

    async def _stop_run(self, session: RunSession) -> None:
        """Take the whole workflow down, not just the slow thing inside it."""
        worker = session.task
        if worker is not None and not worker.is_finished:
            worker.cancel()
            with suppress(Exception):
                await worker.wait()
        self._sessions.remove(session)


    def trail_label(self) -> str:
        return TRAIL_SEPARATOR.join(self._current_steps().values())

    def _current_steps(self) -> dict[str, str]:
        session = current_session()
        return session.steps if session is not None else self._steps

    def _enter_step(self, step: str) -> tuple[str, ...]:
        """Forget this step and everything downstream, then return what precedes it."""
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
        """One card, told what is still going on behind it."""
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
        preselect: str = "",
    ) -> Capability | None:
        chosen = next((c for c in capabilities if c.info.key == preselect), None)
        if chosen is not None:
            self._enter_step("capability")
            self._record("capability", chosen.info.name, chosen)
            return chosen
        if self._leaving:
            return None
        session = current_session()
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
                columns=self._layout.menu.cards_per_row,
            )
        )
        if index is None:
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

    async def choose_folder(self, start: str = "", prompt: str = "") -> str | None:
        await self._claim_screen(current_session())
        chosen = await self.push_screen_wait(
            PathScreen(
                start,
                prompt or "Choose a project",
                recent=self._recent.recent() if self._recent is not None else (),
            )
        )
        if chosen and self._recent is not None:
            self._recent.remember(chosen)
        return chosen

    async def choose_script_section(
        self,
        sections: Sequence[ScriptSection],
        notice: str = "",
    ) -> ScriptSection | None:
        inherited = self._replay("script_section")
        if isinstance(inherited, ScriptSection):
            match = next((s for s in sections if s.key == inherited.key), None)
            if match is not None:
                self._record("script_section", match.name, match)
                return match

        await self._claim_screen(current_session())
        trail = self._enter_step("script_section")
        index = await self.push_screen_wait(
            CardMenuScreen(
                "Choose a group",
                [
                    self._entry(trail, section.key, section.name, section.summary)
                    for section in sections
                ],
                subtitle="Read from this project's own script config.",
                trail=trail,
                notice=notice,
                runs=self._sessions.summary(),
            )
        )
        if index is None:
            return None
        self._record("script_section", sections[index].name, sections[index])
        return sections[index]

    async def choose_script_action(
        self,
        actions: Sequence[ScriptAction],
        notice: str = "",
    ) -> ScriptAction | None:
        inherited = self._replay("script_action")
        if isinstance(inherited, ScriptAction):
            match = next(
                (a for a in actions if a.identifier == inherited.identifier), None
            )
            if match is not None:
                self._record("script_action", match.name, match)
                return match

        await self._claim_screen(current_session())
        trail = self._enter_step("script_action")
        index = await self.push_screen_wait(
            CardMenuScreen(
                "Choose a workflow",
                [
                    MenuEntry(
                        action.reference,
                        action.name,
                        action.summary,
                        self._sessions.running_under((*trail, action.name)),
                        action.detail,
                    )
                    for action in actions
                ],
                subtitle="Read from this stack's script repository.",
                trail=trail,
                notice=notice,
                runs=self._sessions.summary(),
            )
        )
        if index is None:
            return None
        self._record("script_action", actions[index].name, actions[index])
        return actions[index]

    async def choose_script_update(
        self, catalogue: ScriptCatalogue
    ) -> ScriptUpdate | None:
        await self._claim_screen(current_session())
        trail = tuple(self._current_steps().values())
        answers = SCRIPT_UPDATE_ANSWERS
        index = await self.push_screen_wait(
            CardMenuScreen(
                "These scripts are not the published ones",
                [
                    MenuEntry(key, name, description, detail=detail)
                    for key, name, description, detail in answers
                ],
                subtitle=(
                    f"Running {catalogue.installed or 'an unnamed version'}; "
                    f"{catalogue.available} is published."
                ),
                trail=trail,
                notice=f"Store: {catalogue.location}",
                runs=self._sessions.summary(),
            )
        )
        if index is None:
            return None
        return ScriptUpdate(answers[index][0])

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
    return


class _PanelListView(ListView):
    """`ListView` over a `TuiConsole`.

    A thin object rather than the console itself, so `ProcessRunner` is handed the
    one thing it needs and nothing about screens, sessions or Textual travels into
    the domain with it.
    """

    def __init__(self, console: "TuiConsole") -> None:
        self._console = console

    async def show(self, listing: Listing) -> str | None:
        return await self._console.show_rows(listing)

    def close(self) -> None:
        self._console.close_rows()


class _BrowserListView(_PanelListView):
    """`ListView` over a `BrowserScreen`, and a `PickScreen` over the top of it.

    A question the command asks mid-browse is still an ordinary listing and still
    an ordinary pick - it comes up as a modal over the browser and answers with
    `@dti:pick`. Nothing here invents one: what a dangerous action costs is the
    command's to say, in its own words.
    """

    def __init__(self, console: "TuiConsole", screen: BrowserScreen) -> None:
        super().__init__(console)
        self._screen = screen

    @property
    def browsing(self) -> bool:
        return True

    def describe(self, spec) -> None:
        self._screen.describe(spec)

    async def browse(self, listing: Listing):
        return await self._screen.browse(listing)

    def say(self, status) -> None:
        self._screen.say(status)

    async def ask(self, question) -> str | None:
        return await self._console.ask_text(
            question.prompt, question.value, question.multiline
        )
