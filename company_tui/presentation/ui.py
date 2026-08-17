from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from company_tui.domain.capability import Capability
from company_tui.domain.options import Option, OptionValue
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

    async def pause(self) -> None: ...
