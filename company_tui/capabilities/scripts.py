"""Running the automation a project declares about itself."""

import asyncio
from dataclasses import replace
from pathlib import Path

from company_tui.capabilities.script_actions import answers
from company_tui.domain import json_document, naming
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
from company_tui.presentation.ui import Ui
from company_tui.templates.scripts import browses, run_action
from company_tui.templates.services import PackServices

FETCHING = "Reading what {name} can be given..."

PROJECT_ROOT = naming.PROJECT_ROOT_VAR
"""How a launcher says which project this session is being run for."""

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1


def project_root() -> Path:
    return naming.project_root()


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
        """Walk this project's own commands, and read its settings while doing it.

        `follow` is what lets a repository pin its own theme, sources and flags for
        anyone who drives it. Not new trust: driving a project already means running
        the commands it declares (`docs/decisions/0007`).
        """
        root = project_root()
        if not naming.project_root_from_env():
            root = await self._ask_where(root, "Which project's commands?")
            if root is None:
                return CANCELLED

        sections: tuple[ScriptSection, ...] = ()
        while True:
            sections, problem = self._read(root)
            if not problem:
                break
            root = await self._ask_where(root, problem)
            if root is None:
                return CANCELLED

        self._services.config.follow(root)

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
            options = action_options(filled, str(root))
            if browses(filled, self._services.config):
                await self._console.browse(
                    filled.name,
                    run_action(filled, answers(options), root, self._services),
                    subtitle=filled.summary,
                )
                action = None
                continue

            values = await self._console.open_run_panel(
                filled.name,
                options,
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

            if await self._console.close_run_panel(
                result.message, ok=result.exit_code == 0
            ):
                continue
            return result.exit_code

    async def _refresh(
        self, root: Path, option: Option, preview: bool
    ) -> RefreshOutcome:
        """Run one option's declared refresh, and read the choices back."""
        if option.refresh is None:
            return RefreshOutcome(ok=False)

        if preview and not option.refresh.asks_first:
            return RefreshOutcome()

        if option.refresh.lists_values and not preview:
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

        if result.exit_code not in (0, 2):
            return RefreshOutcome(message=said or "the refresh failed", ok=False)
        if preview:
            return RefreshOutcome(message=said)

        if option.refresh.values_command:
            return RefreshOutcome(
                message=said,
                choices=await self._ask_for_choices(root, option.refresh.values_command),
            )

        sections, problem = self._read(root)
        if problem:
            return RefreshOutcome(message=said or problem, ok=False)
        return RefreshOutcome(message=said, choices=self._choices(sections, option))

    @staticmethod
    def _choices(
        sections: tuple[ScriptSection, ...], option: Option
    ) -> tuple[str, ...]:
        """The values the freshly-read document now offers for this option."""
        for section in sections:
            for action in section.actions:
                for argument in action.arguments:
                    if argument.flag == option.key and argument.allowed_values:
                        return argument.allowed_values
        return ()

    async def _with_choices(self, root: Path, action: ScriptAction) -> ScriptAction:
        """`action` with every fetched argument's real values filled in."""
        wanted = [a for a in action.arguments if a.choices_command and not a.allowed_values]
        if not wanted:
            return action

        fetched = await asyncio.gather(
            *(self._ask_for_choices(root, a.choices_command) for a in wanted)
        )
        answers = dict(zip((a.flag for a in wanted), fetched, strict=True))
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
        """One argument's values, or `()` if the command could not offer any."""
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

    async def _ask_where(self, start: "Path | None", why: str) -> "Path | None":
        """Which project to read commands from, or `None` if the user backed out."""
        chosen = await self._console.choose_folder(str(start or Path.cwd()), why)
        if not chosen:
            return None
        return Path(chosen).expanduser().resolve()

    def _read(self, root: Path) -> tuple[tuple[ScriptSection, ...], str]:
        """This project's declared actions, or why there are none."""
        manifest = naming.manifest_path(root)
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
            return (), (
                f"{root.name} carries a {SCRIPT_MANIFEST}, but it declares no commands."
            )
        return sections_from(actions), ""
