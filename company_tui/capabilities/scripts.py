from company_tui.domain.capability import Capability, CapabilityInfo
from company_tui.presentation.ui import Ui


class ScriptsCapability(Capability):
    def __init__(self, console: Ui) -> None:
        self._console = console

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="scripts",
            name="Scripts",
            description="Browse and run project automation scripts",
        )

    async def execute(self) -> int:
        self._console.write("Project scripts are not configured yet.")
        return 0
