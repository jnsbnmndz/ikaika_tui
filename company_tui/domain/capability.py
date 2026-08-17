from abc import ABC, abstractmethod
from dataclasses import dataclass

CANCELLED = -1
"""`execute()` returned because the user backed out before anything ran.

Out of band for a process exit code (those are 0-255), so a caller can tell
"nothing happened" apart from "ran and succeeded" — and skip reporting a result
that does not exist.
"""


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

