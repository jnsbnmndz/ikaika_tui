"""Arranging the interface and every setting in a browser, and saving the answer."""

import asyncio
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from company_tui.application.registry import CapabilityRegistry
from company_tui.domain import json_document, naming
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.commands import Command, commands_from, write_commands
from company_tui.domain.config import ConfigPort, ConfigScope
from company_tui.domain.json_document import MalformedJson
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.ports import FileSystemPort
from company_tui.infrastructure.builder import BuilderServer
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

SCOPE_KEY = "scope"
OPENING = "Opening the builder in your browser..."
BY_HAND = "If it did not open, go to: {url}"
WAITING = "Arrange it there, then press Save and close."
NEXT_TIME = "Settings apply now; how the interface looks, the next time it starts."


class BuilderCapability(Capability):
    """The one capability whose surface is a browser rather than this interface.

    Dragging a grid into shape with a mouse is something a browser does well and a
    terminal does badly, and this runs while somebody is deciding rather than while
    they are working - so the context switch buys something. The server is open only
    for that, and nothing about it survives the run.

    What it edits is the settings document App Setup already exports and imports, so
    this is a second editor and never a second answer to what a setting is: the same
    reader validates it and the same `ConfigPort` writes it (`docs/decisions/0007`).
    """

    def __init__(
        self, console: Ui, config: ConfigPort, file_system: FileSystemPort
    ) -> None:
        self._console = console
        self._config = config
        self._files = file_system
        self._registry: CapabilityRegistry | None = None

    def knows(self, registry: CapabilityRegistry) -> None:
        """The menu this arranges is the one it is in, which is only built after it."""
        self._registry = registry

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="builder",
            name="Builder",
            description="Design the interface and edit any setting, in your browser",
        )

    async def execute(self) -> int:
        while True:
            values = await self._console.open_run_panel("Builder", self._options())
            if values is None:
                return CANCELLED

            outcome = await self._console.run_in_panel(self._arrange(values))
            if outcome is None:
                failure = self._console.panel_failure()
                if await self._console.close_run_panel(
                    failure or STOPPED_MESSAGE, ok=False
                ):
                    continue
                return FAILED if failure else CANCELLED

            message, ok = outcome
            if await self._console.close_run_panel(message, ok=ok):
                continue
            return 0 if ok else FAILED

    def _options(self) -> tuple[Option, ...]:
        return (
            Option(
                key=SCOPE_KEY,
                label="Save to",
                kind=OptionKind.CHOICE,
                choices=tuple(scope.value for scope in self._config.scopes()),
                default=ConfigScope.USER.value,
                help=(
                    "Everything the page edits is written to this one file. user is "
                    "usually right for how the interface looks; project is where a "
                    "team's template and script sources belong."
                ),
            ),
            Option(
                key="where",
                label="Opens in",
                kind=OptionKind.INFO,
                default="a page served to this machine only, while this run lasts",
            ),
        )

    def _cards(self) -> Sequence[tuple[str, str, str]]:
        """Every capability there is, including the ones currently left off.

        Off the menu is not gone: a card somebody hid has to be draggable back.
        """
        if self._registry is None:
            return ()
        return tuple(
            (item.info.key, item.info.name, item.info.description)
            for item in self._registry.every()
        )

    def _manifest(self) -> tuple[Path | None, dict, tuple[Command, ...]]:
        """The project's own command document, if it has one.

        Never created here: what makes a directory one of these projects is
        `ProjectFinalizer`, and a builder that wrote a manifest into a directory
        nobody scaffolded would be deciding that it is one.
        """
        found = naming.manifest_in(naming.project_root())
        if found is None:
            return (None, {}, ())
        try:
            document = json_document.load(self._files.read_text(found))
        except (MalformedJson, OSError) as error:
            self._console.write(f"{found}: {error}")
            return (None, {}, ())
        return (found, document, commands_from(document))

    def _write_commands(self, found: Path, document: dict, wanted) -> None:
        """Put the edited commands back, keeping everything this does not edit."""
        for problem in write_commands(document, wanted):
            self._console.write(f"Commands: {problem}")
        source = self._files.read_text(found)
        self._files.write_text(
            found, json_document.dump(document, json_document.detect_indent(source))
        )
        self._console.write(f"Wrote {found}")

    async def _arrange(self, values: OptionValues) -> tuple[str, bool]:
        """Hand the layout to a browser, take back what it made of it, and save it.

        The port closes with the run either way - finished, or stopped from the
        panel, which cancels this and unwinds through the same `finally`.
        """
        current = self._config.settings()
        scope = self._scope(values)
        found, document, declared = self._manifest()
        server = BuilderServer(
            current,
            self._cards(),
            asyncio.get_running_loop(),
            where=f"Settings here are written to {self._config.location(scope)}.",
            commands=declared,
            manifest=str(found) if found is not None else "",
        )
        url = server.start()
        try:
            self._console.write(OPENING)
            self._console.write(BY_HAND.format(url=url))
            self._console.write(WAITING)
            await asyncio.to_thread(webbrowser.open, url)
            await server.finished.wait()
        finally:
            server.stop()

        for problem in server.problems:
            self._console.write(f"Not taken: {problem}")

        self._console.write(f"Writing {self._config.location(scope)}...")
        path = self._config.save(server.settings, scope)
        if found is not None and server.commands != declared:
            self._write_commands(found, document, server.commands)
        self._console.write(NEXT_TIME)
        return (f"Saved to {path}", True)

    @staticmethod
    def _scope(values: OptionValues) -> ConfigScope:
        chosen = str(values.get(SCOPE_KEY, "")).strip()
        return next(
            (scope for scope in ConfigScope if scope.value == chosen), ConfigScope.USER
        )
