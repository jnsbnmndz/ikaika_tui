"""Creating a project, and adding to one that already exists.

The two are one capability because they are one question asked twice — which
stack, and then what of it — but they are not the same work. New Project hands
a name and a destination to the pack. Components hands a form to whatever the
stack's script repository declares it can add, because those generators are
maintained where the templates they write are, and a toolbox release is the
wrong unit for "React Native grew a widget generator".

A stack with no script repository, or one whose repository declares nothing
that writes a file, falls back to the generators the pack itself ships. That is
what keeps Components meaningful for a stack that has never had scripts.
"""

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
                # NOTHING falls through to whatever the pack ships with, which
                # for a stack that has never had a script repository is the only
                # thing Components could mean.

            options = pack.options(target)
            if not options:
                # A form with nothing on it cannot be filled in, so the pack is
                # asked again — with the reason carried onto that menu, where the
                # user actually is, rather than written behind it.
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
                # Caught before any pack sees it: the name becomes a directory
                # that gets deleted and recreated, and a name that is really a
                # path would aim that at somewhere the user did not choose.
                if await self._console.close_run_panel(str(error), ok=False):
                    continue
                return FAILED

            try:
                # Claimed here rather than inside a pack, so every stack is
                # covered by the same rule and none of them has to remember it —
                # and claimed before the work is handed over, or two runs both
                # find the directory free and both start writing to it.
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
                # No result means either the user stopped it or it broke; the
                # console knows which, and they do not end the same way — a
                # break has to report a failing exit code to whatever ran us.
                failure = self._console.panel_failure()
                if await self._console.close_run_panel(
                    failure or STOPPED_MESSAGE, ok=False
                ):
                    continue
                return FAILED if failure else CANCELLED

            # Scaffolding one project is usually scaffolding several, so the
            # panel offers itself back and the loop picks that up here rather
            # than making the user walk out to the menu and in again.
            if await self._console.close_run_panel(
                result.message, ok=result.exit_code == 0
            ):
                continue
            return result.exit_code
