"""Reports what this machine has against what the packs and their scripts need."""

import platform
import sys

from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.domain.capability import Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort
from company_tui.domain.ports import ProcessRunner
from company_tui.presentation.ui import Ui

FOUND = "found"
MISSING = "missing"


def _want(
    tools: dict[str, tuple[list[str], bool]],
    executable: str,
    wanted_by: str,
    required: bool,
) -> None:
    """Record that something wants `executable`, keeping the strongest claim."""
    names, optional = tools.setdefault(executable, ([], True))
    if wanted_by not in names:
        names.append(wanted_by)
    tools[executable] = (names, optional and not required)


class DoctorCapability(Capability):
    def __init__(
        self,
        console: Ui,
        pack_registry: TemplatePackRegistry,
        process_runner: ProcessRunner,
        config: ConfigPort,
    ) -> None:
        self._console = console
        self._pack_registry = pack_registry
        self._process_runner = process_runner
        self._config = config

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="doctor",
            name="Doctor",
            description="Inspect the local development environment",
        )

    async def execute(self) -> int:
        self._console.write(f"Python: {platform.python_version()}")
        self._console.write(f"Executable: {sys.executable}")
        self._console.write(f"Platform: {platform.platform()}")
        self._console.write(f"Bundle prefix: {self._config.bundle_prefix()}")
        self._console.write(f"Workspace root: {self._config.workspace_root()}")
        self._console.write()

        for executable, (wanted_by, optional) in (await self._tools()).items():
            location = self._process_runner.locate(executable)
            note = f"{', '.join(wanted_by)}{', optional' if optional else ''}"
            self._console.write(f"{executable}: {location or MISSING}  ({note})")

        self._console.write()
        self._console.write("Status: ready")
        return 0

    async def _tools(self) -> dict[str, tuple[list[str], bool]]:
        """Every program this machine is expected to hold, and who expects it."""
        tools: dict[str, tuple[list[str], bool]] = {}
        for pack in self._pack_registry.all():
            for requirement in pack.preflight():
                _want(tools, requirement.executable, pack.info.name, requirement.required)

            catalogue = await pack.script_status()
            for executable in catalogue.executables:
                _want(tools, executable, f"{pack.info.name} scripts", True)
        return tools
