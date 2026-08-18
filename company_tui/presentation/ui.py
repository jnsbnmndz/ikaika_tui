from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from company_tui.domain.capability import Capability
from company_tui.domain.options import Option, OptionValue
from company_tui.domain.script_config import ScriptAction, ScriptCatalogue, ScriptUpdate
from company_tui.domain.template_pack import ScaffoldTarget, ScaffoldTargetOption, TemplatePack

T = TypeVar("T")

Workflow = Callable[[], Awaitable[None]]


class Ui(Protocol):
    def write(self, message: str = "") -> None: ...

    def error(self, message: str) -> None: ...

    async def start_run(self, workflow: Workflow, label: str) -> None:
        """Run one workflow, and hand the menu back when it lets go of the screen.

        Handed over as a callable rather than awaited by the caller, because a
        presentation that runs several at once needs its own task per run and
        needs to be able to start the same workflow again for a second tab.
        Returning does not mean the workflow finished — only that it is no
        longer the thing on screen.
        """
        ...

    async def open_run_panel(
        self, title: str, options: Sequence[Option], trail: Sequence[str] = ()
    ) -> dict[str, OptionValue] | None:
        """Collect every flag up front, then stay open while the work runs.

        Returns the filled-in values, or `None` if the user backed out. Until
        `close_run_panel`, `write`/`ask`/`confirm` report into the same panel, so
        a workflow narrates itself without knowing where the output lands.
        """
        ...

    async def working(self, label: str, work: Awaitable[T]) -> T:
        """Do `work` while saying what is being waited for.

        `run_in_panel`'s counterpart for a step with no panel: a workflow
        between two menus has been popped off one screen and cannot build the
        next until this answers, so nothing on screen is about it. Fine for a
        step that takes no time, and indistinguishable from a hang for one that
        goes to the network.

        The result is the work's own, and a presentation with nowhere to put a
        label is free to ignore it and simply await.
        """
        ...

    async def run_in_panel(self, work: Awaitable[T]) -> T | None:
        """Do the panel's work, returning `None` if it did not produce a result.

        The console owns the running task so the panel's Stop can cancel it —
        and only it. Everything the work is waiting on, a subprocess included,
        unwinds through the usual cancellation path.

        An unhandled error is reported rather than raised: it is shown where the
        run was being narrated, and `panel_failure` then says what it was, so a
        broken workflow costs the user a message instead of the whole session.
        """
        ...

    def panel_failure(self) -> str:
        """Why the last run in the panel broke, or `""` if it was stopped."""
        ...

    async def close_run_panel(self, message: str = "", ok: bool = True) -> bool:
        """Report how the run ended, and say whether another one is wanted.

        `True` means the panel is back at its form with the finished run above
        it, ready to be filled in again — doing the same thing twice should not
        mean walking back out through the menu to get here.
        """
        ...

    async def ask(self, prompt: str) -> str: ...

    async def confirm(self, prompt: str) -> bool: ...

    async def choose_capability(
        self, capabilities: Sequence[Capability]
    ) -> Capability | None: ...

    async def choose_scaffold_target(
        self, options: Sequence[ScaffoldTargetOption], notice: str = ""
    ) -> ScaffoldTarget | None: ...

    async def choose_template_pack(
        self, packs: Sequence[TemplatePack], notice: str = ""
    ) -> TemplatePack | None:
        """Ask again, saying why if the last answer led nowhere.

        A workflow that sends the user back has something to tell them, and the
        place to tell them is the menu they land on. Writing it to the console
        instead would put it behind whatever screen comes next.
        """
        ...

    async def choose_script_action(
        self, actions: Sequence[ScriptAction], notice: str = ""
    ) -> ScriptAction | None:
        """Pick one of the workflows a script repository declares.

        A menu rather than a field on the form, because this is the choice of
        which workflow to run and the form is what that workflow asks for. It
        is also the only menu here whose entries are read off a disk, so its
        cards carry their own one-line detail instead of looking one up.
        """
        ...

    async def choose_script_update(
        self, catalogue: ScriptCatalogue
    ) -> ScriptUpdate | None:
        """Ask what to do about a store that has fallen behind its repository.

        Three answers, so a menu rather than a dialog: `ConfirmScreen` asks
        about one irreversible thing and offers exactly two, and "stop asking"
        is neither of them. Backing out is a fourth answer that costs nothing —
        Esc puts the stack menu back with nothing decided.
        """
        ...

    async def pause(self) -> None: ...
