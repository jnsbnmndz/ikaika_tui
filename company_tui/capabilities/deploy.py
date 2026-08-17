from company_tui.domain.capability import Capability, CapabilityInfo
from company_tui.presentation.ui import Ui


class DeployCapability(Capability):
    def __init__(self, console: Ui) -> None:
        self._console = console

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="deploy",
            name="Deploy",
            description="Ship the current project to an environment",
        )

    async def execute(self) -> int:
        self._console.write("Deploy workflows are not configured yet.")
        return 0
