"""Running the automation a project declares about itself.

Build runs the workflows a *stack's* script repository declares, cloned into the
toolbox's own store and shared by every project on the machine. This runs the
ones the project in front of you declares, out of the `ikaika.script.json` in its
own root — the case `templates/scripts.py` already allows for when it says a
command runs where its config lives, so a project carrying a `config` of its own
runs in the project.

Nothing here knows what wrote that file. The IKAIKA PowerShell toolkit emits one
describing every command it can dispatch, which is what this was built for and is
deliberately not what it depends on: a project whose commands are npm scripts, or
a Makefile, or a shell script per task, declares them the same way and arrives
here with the same menus. The document is the contract; the program that produced
it is not.

`config` is read as sections rather than flattened, because a repository that
declares fifty actions has already said how it groups them, and fifty cards in one
grid is a list to scroll rather than a choice to make.


WHERE THE PROJECT COMES FROM

`IKAIKA_PROJECT_ROOT` when it is set, and the working directory otherwise. The
variable is how a launcher says "you are being run FOR this project" — the toolbox
may be started from its own checkout while driving another tree, and the directory
it happens to be in is then the wrong answer. A variable rather than an argument so
it survives whatever the app does with its own command line.


WHY THE RUN IS templates/scripts.py's

`run_action` is the same function Build and Components go through, and it is reused
rather than reimplemented because the parts of it that matter here are the parts
that are easy to miss: the answers are checked against the rules the document
declared, the tools its commands need are looked for on the machine *before*
anything runs, `${...}` is expanded against one map, and a stopped run unwinds to
the subprocess rather than orphaning it. An action with no template and no path —
which every action here is — skips the staging half and simply runs what the config
named.
"""

import os
from pathlib import Path

from company_tui.domain import json_document
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.identity import SCRIPT_MANIFEST
from company_tui.domain.json_document import MalformedJson
from company_tui.domain.script_config import (
    ScriptAction,
    ScriptSection,
    action_options,
    actions_from,
    sections_from,
)
from company_tui.presentation.ui import Ui
from company_tui.templates.scripts import run_action
from company_tui.templates.services import PackServices

PROJECT_ROOT = "IKAIKA_PROJECT_ROOT"
"""How a launcher says which project this session is being run for."""

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1


def project_root() -> Path:
    declared = os.environ.get(PROJECT_ROOT, "").strip()
    return Path(declared).expanduser().resolve() if declared else Path.cwd().resolve()


class ScriptsCapability(Capability):
    def __init__(self, console: Ui, services: PackServices) -> None:
        self._console = console
        self._services = services

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="scripts",
            name="Scripts",
            description="Browse and run this project's own commands",
        )

    async def execute(self) -> int:
        root = project_root()
        sections, problem = self._read(root)
        if problem:
            self._console.error(problem)
            return FAILED

        section: ScriptSection | None = None
        action: ScriptAction | None = None
        notice = ""

        while True:
            if section is None:
                section = await self._console.choose_script_section(sections, notice)
                notice = ""
                if section is None:
                    return CANCELLED

            if action is None:
                action = await self._console.choose_script_action(section.actions)
                if action is None:
                    section = None
                    continue

            values = await self._console.open_run_panel(
                action.name, action_options(action, str(root))
            )
            if values is None:
                action = None
                continue

            result = await self._console.run_in_panel(
                run_action(action, values, root, self._services)
            )
            if result is None:
                failure = self._console.panel_failure()
                if await self._console.close_run_panel(
                    failure or STOPPED_MESSAGE, ok=False
                ):
                    continue
                return FAILED if failure else CANCELLED

            # The panel offers itself back with the form still filled in: running a
            # command twice should not mean walking out through two menus to get here.
            if await self._console.close_run_panel(
                result.message, ok=result.exit_code == 0
            ):
                continue
            return result.exit_code

    def _read(self, root: Path) -> tuple[tuple[ScriptSection, ...], str]:
        """This project's declared actions, or why there are none.

        Read through the filesystem port rather than with `open`, so the capability
        stays testable without a directory on disk — the same rule every other
        workflow here follows.
        """
        manifest = root / SCRIPT_MANIFEST
        if not self._services.file_system.exists(manifest):
            return (), (
                f"{root.name} does not declare any commands: there is no "
                f"{SCRIPT_MANIFEST} in {root}."
            )
        try:
            document = json_document.load(
                self._services.file_system.read_text(manifest)
            )
        except (MalformedJson, OSError) as error:
            return (), f"{manifest} could not be read: {error}"

        actions = actions_from(document)
        if not actions:
            # Told apart from a missing file on purpose. A manifest carrying the four
            # identity keys and no `config` is a perfectly good project marker written
            # by something with no commands to declare, and reporting it as unreadable
            # would send somebody looking for a syntax error that is not there.
            return (), (
                f"{root.name} carries a {SCRIPT_MANIFEST}, but it declares no commands."
            )
        return sections_from(actions), ""
