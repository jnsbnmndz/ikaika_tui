"""Running the workflows a stack's script repository declares.

Build is a menu of whatever that repository says it can run rather than a list
kept in this file: a stack adds a workflow by editing its own
`ikaika.script.json`, not by a release of the toolbox. Which is why the actions
are asked for between the stack menu and the panel — that is the first moment
there is a stack to ask, and the last one before the user is looking at a form.

What it does *not* offer is the same repository's generators. An action that
carries a template and a filename puts a file into a project that already
exists, which is Scaffold's Components and not a build; listing it in both
would be the same action reachable two ways, each with its own breadcrumb and
its own tab. `capabilities/script_actions.py` is the walk they share.

A stack with no declared workflow still has whatever build it ships with. There
is nothing to choose between there, so it simply runs.
"""

from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.capabilities import script_actions
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.script_config import workflows
from company_tui.domain.template_pack import TemplatePack
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

            walk = await script_actions.walk(self._console, pack, wanted=workflows)

            if walk.ending is script_actions.Ending.NOTHING:
                result = await pack.build()
                self._console.write(result.message)
                return result.exit_code

            if walk.ending is script_actions.Ending.BACK:
                # Fetching the scripts is the one step with no panel behind it,
                # so what went wrong is carried onto the menu the user lands on
                # rather than written where the next screen covers it.
                notice = walk.notice
                pack = None
                continue

            return walk.exit_code
