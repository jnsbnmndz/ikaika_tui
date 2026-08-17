"""React web projects.

Not implemented yet. Once there is a structure repository for it, this becomes
the same shape as `templates/react_native/behavior.py`: a `TemplateSource`, a
clone, and the finalizer — plus whichever files besides `ikaika.script.json`
carry the project's name for this stack.
"""

from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ToolRequirement,
)
from company_tui.templates.services import PackServices

STACK_NAME = "React"
PACK_KEY = "react"

REQUIRED_TOOLS: tuple[ToolRequirement, ...] = ()
GENERATORS: tuple[Generator, ...] = ()


async def scaffold_new_project(
    context: ScaffoldContext, services: PackServices
) -> PackActionResult:
    return PackActionResult(
        available=False,
        message=f"{STACK_NAME} scaffolding for new projects is not available yet.",
    )


async def scaffold_controller(
    context: ScaffoldContext, services: PackServices
) -> PackActionResult:
    return PackActionResult(
        available=False,
        message=f"{STACK_NAME} controller scaffolding is not available yet.",
    )


async def build(services: PackServices) -> PackActionResult:
    return PackActionResult(
        available=False,
        message=f"{STACK_NAME} builds are not available yet.",
    )
