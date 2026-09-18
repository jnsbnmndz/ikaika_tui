"""Arranging the interface in a browser, and writing the answer to the settings file."""

import asyncio
import webbrowser
from collections.abc import Sequence
from dataclasses import replace

from company_tui.application.registry import CapabilityRegistry
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort, ConfigScope
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.infrastructure.builder import BuilderServer
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

SCOPE_KEY = "scope"
OPENING = "Opening the layout in your browser..."
BY_HAND = "If it did not open, go to: {url}"
WAITING = "Arrange it there, then press Save and close."
NEXT_TIME = "The interface takes it up the next time it starts."


class LayoutCapability(Capability):
    """The one capability whose surface is a browser rather than this interface.

    Dragging a grid into shape with a mouse is something a browser does well and a
    terminal does badly, and this runs once while somebody is deciding rather than
    while they are working - so the context switch buys something. The server is
    open only for that, and nothing about it survives the run (`docs/decisions/0007`).
    """

    def __init__(self, console: Ui, config: ConfigPort) -> None:
        self._console = console
        self._config = config
        self._registry: CapabilityRegistry | None = None

    def knows(self, registry: CapabilityRegistry) -> None:
        """The menu this arranges is the one it is in, which is only built after it."""
        self._registry = registry

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="layout",
            name="Layout",
            description="Arrange the colours, the window and this menu",
        )

    async def execute(self) -> int:
        while True:
            values = await self._console.open_run_panel("Layout", self._options())
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
                choices=tuple(scope.value for scope in ConfigScope),
                default=ConfigScope.USER.value,
                help=(
                    "user is usually right: how the interface looks is a property "
                    "of this machine rather than of the repository."
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

    async def _arrange(self, values: OptionValues) -> tuple[str, bool]:
        """Hand the layout to a browser, take back what it made of it, and save it.

        The port closes with the run either way - finished, or stopped from the
        panel, which cancels this and unwinds through the same `finally`.
        """
        current = self._config.settings()
        server = BuilderServer(
            current.layout, self._cards(), asyncio.get_running_loop()
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

        scope = self._scope(values)
        self._console.write(f"Writing {self._config.location(scope)}...")
        path = self._config.save(replace(current, layout=server.layout), scope)
        self._console.write(NEXT_TIME)
        return (f"Saved the layout to {path}", True)

    @staticmethod
    def _scope(values: OptionValues) -> ConfigScope:
        chosen = str(values.get(SCOPE_KEY, "")).strip()
        return next(
            (scope for scope in ConfigScope if scope.value == chosen), ConfigScope.USER
        )
