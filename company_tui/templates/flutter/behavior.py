"""Flutter projects.

Not implemented yet. When it is, `pubspec.yaml` is this stack's equivalent of
Expo's `app.json` — the file besides `ikaika.script.json` that also carries the
project's name — so it becomes an `IdentityRewrite` passed to the finalizer.
"""

from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ToolRequirement,
)
from company_tui.templates.services import PackServices

STACK_NAME = "Flutter"
PACK_KEY = "flutter"

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
