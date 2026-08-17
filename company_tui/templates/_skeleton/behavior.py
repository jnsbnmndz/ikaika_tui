"""Copy this folder to add a stack: rename it, change STACK_NAME, fill each function in.

The signatures below are the ones the real packs use, so a copy of this file
starts out compatible with `pack.py` rather than needing to be reshaped first.
`templates/python/behavior.py` writes a tree file by file and
`templates/react_native/behavior.py` clones one — model whichever is closer.

Two things are not optional whichever way the tree arrives:

* the project must end up carrying `ikaika.script.json`, stamped with the
  identity the user asked for — hand the finished directory to
  `services.finalizer.finalize()` and it does that;
* anything the pack half-created has to be cleaned up if the run is stopped.
"""

from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ToolRequirement,
)
from company_tui.templates.services import PackServices

STACK_NAME = "Skeleton"

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
