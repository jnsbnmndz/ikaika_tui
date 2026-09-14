"""The directories somebody has picked before, newest first."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

LIMIT = 12
"""How many directories are kept."""

def remember(paths: Sequence[str], chosen: str, limit: int = LIMIT) -> tuple[str, ...]:
    """`paths` with `chosen` at the front, deduplicated and capped."""
    candidate = chosen.strip()
    if not candidate:
        return tuple(paths)
    kept = [path for path in paths if path != candidate]
    return tuple([candidate, *kept][:limit])


class RecentPathsPort(ABC):
    """Where the list is kept between launches."""

    @abstractmethod
    def recent(self) -> tuple[str, ...]:
        """The list, newest first. Never raises: unreadable is empty."""
        raise NotImplementedError

    @abstractmethod
    def remember(self, chosen: str) -> None:
        """Put `chosen` at the front. Never raises: a history that cannot be."""
        raise NotImplementedError
