"""Creating a project, and adding to one that already exists."""

from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.capabilities import script_actions
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.destinations import DestinationBusy, DestinationLocks
from company_tui.domain.project_name import InvalidProjectName
from company_tui.domain.script_config import components
from company_tui.domain.template_pack import (
    SCAFFOLD_TARGET_OPTIONS,
    ScaffoldTarget,
    TemplatePack,
    context_from,
)
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1


class ScaffoldCapability(Capability):
    def __init__(
        self,
        console: Ui,
        pack_registry: TemplatePackRegistry,
        locks: DestinationLocks | None = None,
    ) -> None:
        self._console = console
        self._pack_registry = pack_registry
        self._locks = locks if locks is not None else DestinationLocks()

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="scaffold",
            name="Scaffold",
            description="Create projects and project files",
        )

    async def execute(self) -> int:
        target: ScaffoldTarget | None = None
        pack: TemplatePack | None = None
        notice = ""

        while True:
            if target is None:
                target = await self._console.choose_scaffold_target(
                    SCAFFOLD_TARGET_OPTIONS
                )
                if target is None:
                    return CANCELLED
                continue

            if pack is None:
                pack = await self._console.choose_template_pack(
                    self._pack_registry.all(), notice
                )
                notice = ""
                if pack is None:
                    target = None
                continue

            if target is ScaffoldTarget.CONTROLLER:
                walk = await script_actions.walk(
                    self._console, pack, wanted=components
                )
                if walk.ending is script_actions.Ending.BACK:
                    notice = walk.notice
                    pack = None
                    continue
                if walk.ending is script_actions.Ending.DONE:
                    return walk.exit_code
                if walk.notice:
                    self._console.write(walk.notice)

            options = pack.options(target)
            if not options:
                notice = (
                    f"{pack.info.name} has nothing to generate for "
                    f"{target.value.replace('_', ' ')} yet."
                )
                pack = None
                continue

            values = await self._console.open_run_panel(
                f"{target.value.replace('_', ' ').title()}", options
            )
            if values is None:
                pack = None
                continue

            try:
                context = context_from(target, values)
            except InvalidProjectName as error:
                if await self._console.close_run_panel(str(error), ok=False):
                    continue
                return FAILED

            try:
                self._locks.claim(context.destination)
            except DestinationBusy as error:
                if await self._console.close_run_panel(str(error), ok=False):
                    continue
                return FAILED

            try:
                result = await self._console.run_in_panel(pack.scaffold(context))
            finally:
                self._locks.release(context.destination)

            if result is None:
                failure = self._console.panel_failure()
                if await self._console.close_run_panel(
                    failure or STOPPED_MESSAGE, ok=False
                ):
                    continue
                return FAILED if failure else CANCELLED

            if await self._console.close_run_panel(
                result.message, ok=result.exit_code == 0
            ):
                continue
            return result.exit_code
