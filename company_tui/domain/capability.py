"""What a capability is: a key, a name, a description and an async `execute`."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

CANCELLED = -1
"""`execute()` returned because the user backed out before anything ran."""

@dataclass(frozen=True, slots=True)
class CapabilityInfo:
    key: str
    name: str
    description: str


class Capability(ABC):
    @property
    @abstractmethod
    def info(self) -> CapabilityInfo:
        raise NotImplementedError

    @abstractmethod
    async def execute(self) -> int:
        raise NotImplementedError

