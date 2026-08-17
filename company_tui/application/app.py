from company_tui.application.registry import CapabilityRegistry
from company_tui.domain.capability import CANCELLED, Capability
from company_tui.presentation.ui import Ui


class Application:
    def __init__(self, console: Ui, registry: CapabilityRegistry) -> None:
        self._console = console
        self._registry = registry

    async def run(self) -> int:
        while True:
            capability = await self._console.choose_capability(self._registry.all())
            if capability is None:
                self._console.write("Goodbye.")
                return 0
            # Handed over rather than awaited: a presentation that can show more
            # than one run at a time needs a task per run, and needs to be able
            # to start this same workflow again for a second one. This returns
            # when the workflow stops needing the screen, which is not the same
            # as when it finishes.
            await self._console.start_run(
                lambda item=capability: self._work(item), capability.info.name
            )

    async def _work(self, capability: Capability) -> None:
        if await capability.execute() != CANCELLED:
            await self._console.pause()

    async def run_capability(self, key: str) -> int:
        capability = self._registry.get(key)
        if capability is None:
            self._console.error(f"Unknown capability: {key}")
            return 2
        exit_code = await capability.execute()
        return 0 if exit_code == CANCELLED else exit_code

    def print_capabilities(self) -> None:
        for capability in self._registry.all():
            info = capability.info
            self._console.write(f"{info.key:<12} {info.description}")
