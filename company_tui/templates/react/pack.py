from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ScaffoldTarget,
    TemplatePack,
    TemplatePackInfo,
    ToolRequirement,
)
from company_tui.templates.react import behavior
from company_tui.templates.services import PackServices


class ReactTemplatePack(TemplatePack):
    def __init__(self, services: PackServices) -> None:
        self._services = services

    @property
    def info(self) -> TemplatePackInfo:
        return TemplatePackInfo(
            key=behavior.PACK_KEY,
            name="React",
            version="0.1.0",
            description="React web application template pack",
        )

    def generators(self) -> tuple[Generator, ...]:
        return behavior.GENERATORS

    def preflight(self) -> tuple[ToolRequirement, ...]:
        return behavior.REQUIRED_TOOLS

    async def scaffold(self, context: ScaffoldContext) -> PackActionResult:
        if context.target is ScaffoldTarget.NEW_PROJECT:
            return await behavior.scaffold_new_project(context, self._services)
        if context.target is ScaffoldTarget.CONTROLLER:
            return await behavior.scaffold_controller(context, self._services)
        return PackActionResult(available=False, message="Unsupported scaffold target.")

    async def build(self) -> PackActionResult:
        return await behavior.build(self._services)
