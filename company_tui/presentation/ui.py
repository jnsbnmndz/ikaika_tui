"""The protocol both consoles satisfy, so a workflow never knows which it has."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from company_tui.domain.capability import Capability
from company_tui.domain.options import Option, OptionValue, RefreshOutcome
from company_tui.domain.script_config import (
    ScriptAction,
    ScriptCatalogue,
    ScriptSection,
    ScriptUpdate,
)
from company_tui.domain.template_pack import (
    ScaffoldTarget,
    ScaffoldTargetOption,
    TemplatePack,
)

T = TypeVar("T")

Workflow = Callable[[], Awaitable[None]]

RefreshRunner = Callable[[Option, bool], Awaitable[RefreshOutcome]]
"""Runs one option's refresh, previewing when the second argument is True."""

class Ui(Protocol):
    def write(self, message: str = "") -> None: ...

    def error(self, message: str) -> None: ...

    async def start_run(self, workflow: Workflow, label: str) -> None:
        """Run one workflow, and hand the menu back when it lets go of the screen."""
        ...

    async def open_run_panel(
        self,
        title: str,
        options: Sequence[Option],
        trail: Sequence[str] = (),
        refresh: "RefreshRunner | None" = None,
        preview: "Callable[[dict[str, OptionValue]], str] | None" = None,
        subtitle: str = "",
    ) -> dict[str, OptionValue] | None:
        """Collect every flag up front, then stay open while the work runs."""
        ...

    async def install_update(self, installer: str, version: str) -> str:
        """Install `installer` and leave, or say why not."""
        ...

    async def working(self, label: str, work: Awaitable[T]) -> T:
        """Do `work` while saying what is being waited for."""
        ...

    async def run_in_panel(self, work: Awaitable[T]) -> T | None:
        """Do the panel's work, returning `None` if it did not produce a result."""
        ...

    def panel_failure(self) -> str:
        """Why the last run in the panel broke, or `""` if it was stopped."""
        ...

    async def close_run_panel(self, message: str = "", ok: bool = True) -> bool:
        """Report how the run ended, and say whether another one is wanted."""
        ...

    async def ask(self, prompt: str) -> str: ...

    async def confirm(self, prompt: str) -> bool: ...

    async def choose_capability(
        self, capabilities: Sequence[Capability], preselect: str = ""
    ) -> Capability | None:
        """Choose what to do, or take `preselect` as already chosen."""
        ...

    async def choose_scaffold_target(
        self, options: Sequence[ScaffoldTargetOption], notice: str = ""
    ) -> ScaffoldTarget | None: ...

    async def choose_template_pack(
        self, packs: Sequence[TemplatePack], notice: str = ""
    ) -> TemplatePack | None:
        """Ask again, saying why if the last answer led nowhere."""
        ...

    async def choose_folder(self, start: str = "", prompt: str = "") -> str | None:
        """Ask which directory to work in, or `None` if the user backed out."""
        ...

    async def choose_script_section(
        self, sections: Sequence[ScriptSection], notice: str = ""
    ) -> ScriptSection | None:
        """Pick which group of a document's actions to look at."""
        ...

    async def choose_script_action(
        self, actions: Sequence[ScriptAction], notice: str = ""
    ) -> ScriptAction | None:
        """Pick one of the workflows a script repository declares."""
        ...

    async def choose_script_update(
        self, catalogue: ScriptCatalogue
    ) -> ScriptUpdate | None:
        """Ask what to do about a store that has fallen behind its repository."""
        ...

    async def pause(self) -> None: ...
