"""Running the workflows a stack's script repository declares."""

from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.capabilities import script_actions
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort
from company_tui.domain.script_config import workflows
from company_tui.domain.template_pack import TemplatePack
from company_tui.presentation.ui import Ui


class BuildCapability(Capability):
    def __init__(
        self, console: Ui, pack_registry: TemplatePackRegistry, config: ConfigPort
    ) -> None:
        self._console = console
        self._pack_registry = pack_registry
        self._config = config

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="build",
            name="Build",
            description="Run project build and compile workflows",
        )

    async def execute(self) -> int:
        pack: TemplatePack | None = None
        notice = ""

        while True:
            if pack is None:
                pack = await self._console.choose_template_pack(
                    self._pack_registry.all(), notice
                )
                notice = ""
                if pack is None:
                    return CANCELLED

            walk = await script_actions.walk(
                self._console, pack, wanted=workflows, config=self._config
            )

            if walk.ending is script_actions.Ending.NOTHING:
                if walk.notice:
                    self._console.write(walk.notice)
                result = await pack.build()
                self._console.write(result.message)
                return result.exit_code

            if walk.ending is script_actions.Ending.BACK:
                notice = walk.notice
                pack = None
                continue

            return walk.exit_code
