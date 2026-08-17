from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.presentation.ui import Ui


class BuildCapability(Capability):
    def __init__(self, console: Ui, pack_registry: TemplatePackRegistry) -> None:
        self._console = console
        self._pack_registry = pack_registry

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="build",
            name="Build",
            description="Run project build and compile workflows",
        )

    async def execute(self) -> int:
        pack = await self._console.choose_template_pack(self._pack_registry.all())
        if pack is None:
            return CANCELLED

        result = await pack.build()
        self._console.write(result.message)
        return result.exit_code
