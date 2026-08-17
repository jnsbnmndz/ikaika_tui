from collections.abc import Iterable

from company_tui.domain.capability import Capability


class CapabilityRegistry:
    def __init__(self, capabilities: Iterable[Capability]) -> None:
        self._capabilities = {item.info.key: item for item in capabilities}

    def all(self) -> tuple[Capability, ...]:
        return tuple(self._capabilities.values())

    def get(self, key: str) -> Capability | None:
        return self._capabilities.get(key)

