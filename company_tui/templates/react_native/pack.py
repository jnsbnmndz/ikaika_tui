from company_tui.domain.config import TemplateSource
from company_tui.domain.options import Option, OptionValues
from company_tui.domain.script_config import ScriptAction, ScriptCatalogue, ScriptUpdate
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
            description="React Native app from the shared structure repo",
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

    def script_source(self) -> TemplateSource:
        return behavior.script_source(self._services)

    def preflight(self) -> tuple[ToolRequirement, ...]:
        return behavior.DECLARED_TOOLS

    async def scaffold(self, context: ScaffoldContext) -> PackActionResult:
        if context.target is ScaffoldTarget.NEW_PROJECT:
            return await behavior.scaffold_new_project(context, self._services)
        if context.target is ScaffoldTarget.CONTROLLER:
            return await behavior.scaffold_controller(context, self._services)
        return PackActionResult(available=False, message="Unsupported scaffold target.")

    async def script_actions(self) -> ScriptCatalogue:
        return await behavior.script_actions(self._services)

    async def run_script(
        self, action: ScriptAction, values: OptionValues
    ) -> PackActionResult:
        return await behavior.run_script(action, values, self._services)

    async def script_status(self, *, compare: bool = False) -> ScriptCatalogue:
        return await behavior.script_status(self._services, compare=compare)

    async def install_scripts(self, *, replace: bool = False) -> PackActionResult:
        return await behavior.install_scripts(self._services, replace=replace)

    async def apply_script_update(self, choice: ScriptUpdate) -> PackActionResult:
        return await behavior.apply_script_update(choice, self._services)

    async def build(self) -> PackActionResult:
        return await behavior.build(self._services)
