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
    """Record that something wants `executable`, keeping the strongest claim.

    Optional only while everything asking for it can do without it: a tool one
    stack treats as a nicety and another cannot run without is not optional on
    this machine.
    """
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

        # Reported per tool rather than per pack: `git` being absent is one fact
        # about this machine, not one fact per stack that happens to need it.
        for executable, (wanted_by, optional) in (await self._tools()).items():
            location = self._process_runner.locate(executable)
            note = f"{', '.join(wanted_by)}{', optional' if optional else ''}"
            self._console.write(f"{executable}: {location or MISSING}  ({note})")

        self._console.write()
        self._console.write("Status: ready")
        return 0

    async def _tools(self) -> dict[str, tuple[list[str], bool]]:
        """Every program this machine is expected to hold, and who expects it.

        Two sources, because they are two different claims. A pack declares
        what its own code shells out to, which is knowable without a disk. A
        script repository *calls* things, and what it calls is read out of the
        store — derived from the commands themselves rather than from a list
        beside them, so a repository that starts calling `pnpm` is reported as
        needing `pnpm` without anyone remembering to say so.
        """
        tools: dict[str, tuple[list[str], bool]] = {}
        for pack in self._pack_registry.all():
            for requirement in pack.preflight():
                _want(tools, requirement.executable, pack.info.name, requirement.required)

            # Never a fetch. Doctor reports on the machine as it is, and a
            # report that cloned a repository to write itself would be a
            # different act than the one the user asked for.
            catalogue = await pack.script_status()
            for executable in catalogue.executables:
                _want(tools, executable, f"{pack.info.name} scripts", True)
        return tools
