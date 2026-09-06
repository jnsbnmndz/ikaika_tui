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

import asyncio
import os
from dataclasses import replace
from pathlib import Path

from company_tui.domain import json_document
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.identity import SCRIPT_MANIFEST
from company_tui.domain.json_document import MalformedJson
from company_tui.domain.options import Option, RefreshOutcome
from company_tui.domain.script_config import (
    ROOT,
    ScriptAction,
    ScriptSection,
    action_options,
    actions_from,
    command_preview,
    expand,
    sections_from,
    split_command,
)

FETCHING = "Reading what {name} can be given..."
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

            filled = await self._console.working(
                FETCHING.format(name=action.name), self._with_choices(root, action)
            )
            values = await self._console.open_run_panel(
                filled.name,
                action_options(filled, str(root)),
                refresh=lambda option, preview: self._refresh(root, option, preview),
                preview=lambda values, chosen=filled: command_preview(chosen, values),
                subtitle=filled.summary,
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

    async def _refresh(
        self, root: Path, option: Option, preview: bool
    ) -> RefreshOutcome:
        """Run one option's declared refresh, and read the choices back.

        Two commands, and the caller decides which: `preview` reports what acting
        would do and changes nothing, so the panel can ask before something is
        deleted. Its output IS the question - empty means there is nothing to ask
        about.

        Acting is followed by re-reading the document, because that is where the
        new values are. Whatever wrote the manifest is what re-computes it, so the
        list the field ends up with is the one the next run would have been offered
        anyway - there is no second answer to what the choices are.
        """
        if option.refresh is None:
            return RefreshOutcome(ok=False)

        if preview and not option.refresh.asks_first:
            # Nothing this one does is worth a dialog, so there is nothing to ask.
            return RefreshOutcome()

        if option.refresh.lists_values and not preview:
            # Its output IS the list, so there is no document to re-read.
            values = await self._ask_for_choices(root, option.refresh.command)
            if not values:
                return RefreshOutcome(message="nothing came back", ok=False)
            return RefreshOutcome(message=f"{len(values)} value(s)", choices=values)

        raw = option.refresh.preview if preview else option.refresh.command
        command = tuple(
            expand(token, {ROOT: str(root)}) for token in split_command(raw)
        )
        if not command:
            return RefreshOutcome(message="that refresh is not a command", ok=False)

        result = await self._services.process_runner.capture(command, root)
        said = (result.stdout or "").strip() or (result.stderr or "").strip()

        # Exit 2 is the dispatcher saying the command declares no refresh for this
        # parameter, which is not a failure - it is a button with nothing behind it.
        if result.exit_code not in (0, 2):
            return RefreshOutcome(message=said or "the refresh failed", ok=False)
        if preview:
            return RefreshOutcome(message=said)

        sections, problem = self._read(root)
        if problem:
            return RefreshOutcome(message=said or problem, ok=False)
        return RefreshOutcome(message=said, choices=self._choices(sections, option))

    @staticmethod
    def _choices(
        sections: tuple[ScriptSection, ...], option: Option
    ) -> tuple[str, ...]:
        """The values the freshly-read document now offers for this option.

        Matched by flag across every action, because the document was re-read from
        scratch and holds equal objects rather than the same ones.
        """
        for section in sections:
            for action in section.actions:
                for argument in action.arguments:
                    if argument.flag == option.key and argument.allowed_values:
                        return argument.allowed_values
        return ()

    async def _with_choices(self, root: Path, action: ScriptAction) -> ScriptAction:
        """`action` with every fetched argument's real values filled in.

        Asked when the form opens rather than read out of the document, because a
        fetched list is local state and the document is committed. This is also
        when the WPF dialog asks - it calls the provider as it builds the row - so
        the two front ends offer the same values at the same moment.

        Every argument is asked at once: each is a separate interpreter start, and
        a form with five of them would otherwise open a second later than it needs
        to. A fetch that answers nothing leaves the argument without a list, which
        is a plain text box - exactly what the desktop form falls back to.
        """
        wanted = [a for a in action.arguments if a.choices_command and not a.allowed_values]
        if not wanted:
            return action

        fetched = await asyncio.gather(
            *(self._ask_for_choices(root, a.choices_command) for a in wanted)
        )
        answers = dict(zip((a.flag for a in wanted), fetched))
        return replace(
            action,
            arguments=tuple(
                replace(a, allowed_values=answers[a.flag])
                if answers.get(a.flag)
                else a
                for a in action.arguments
            ),
        )

    async def _ask_for_choices(self, root: Path, raw: str) -> tuple[str, ...]:
        """One argument's values, or `()` if the command could not offer any.

        Silence rather than an error: a list that cannot be fetched is a field
        somebody types into, and a workflow that refused to open its own form over
        an offline `git` would be worse than one that asks for the value.
        """
        command = tuple(expand(token, {ROOT: str(root)}) for token in split_command(raw))
        if not command:
            return ()
        try:
            result = await self._services.process_runner.capture(command, root)
        except OSError:
            return ()
        if result.exit_code != 0:
            return ()
        return tuple(
            line.strip() for line in (result.stdout or "").splitlines() if line.strip()
        )

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
