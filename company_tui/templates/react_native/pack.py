from company_tui.domain.config import TemplateSource
from company_tui.domain.options import Option
from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ScaffoldTarget,
    TemplatePack,
    TemplatePackInfo,
    ToolRequirement,
)
from company_tui.templates.react_native import behavior
from company_tui.templates.services import PackServices


class ReactNativeTemplatePack(TemplatePack):
    def __init__(self, services: PackServices) -> None:
        self._services = services

    @property
    def info(self) -> TemplatePackInfo:
        return TemplatePackInfo(
            key=behavior.PACK_KEY,
            name="React Native",
            version="0.2.0",
            description="React Native app from the IKAIKA structure repo",
        )

    def options(self, target: ScaffoldTarget) -> tuple[Option, ...]:
        if target is ScaffoldTarget.NEW_PROJECT:
            config = self._services.config
            return behavior.new_project_options(
                config.template_source(behavior.PACK_KEY, behavior.TEMPLATE),
                str(config.workspace_root()),
            )
        return super().options(target)

    def generators(self) -> tuple[Generator, ...]:
        return behavior.GENERATORS

    def template_source(self) -> TemplateSource:
        return self._services.config.template_source(
            behavior.PACK_KEY, behavior.TEMPLATE
        )

    def preflight(self) -> tuple[ToolRequirement, ...]:
        return behavior.DECLARED_TOOLS

    async def scaffold(self, context: ScaffoldContext) -> PackActionResult:
        if context.target is ScaffoldTarget.NEW_PROJECT:
            return await behavior.scaffold_new_project(context, self._services)
        if context.target is ScaffoldTarget.CONTROLLER:
            return await behavior.scaffold_controller(context, self._services)
        return PackActionResult(available=False, message="Unsupported scaffold target.")

    async def build(self) -> PackActionResult:
        return await behavior.build(self._services)
