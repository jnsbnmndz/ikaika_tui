"""One run at a time per directory."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class DestinationBusy(Exception):
    """Another run is already writing to that directory."""

class DestinationLocks:
    """Which directories are being written to right now, and by how many."""

    def __init__(self) -> None:
        self._held: set[str] = set()

    def claim(self, destination: Path) -> None:
        """Take the directory, or say who has it."""
        key = self.key(destination)
        if key in self._held:
            raise DestinationBusy(
                f"{destination.as_posix()} is already being written by another run."
            )
        self._held.add(key)

    def release(self, destination: Path) -> None:
        self._held.discard(self.key(destination))

    @contextmanager
    def hold(self, destination: Path) -> Iterator[None]:
        self.claim(destination)
        try:
            yield
        finally:
            self.release(destination)

    def holds(self, destination: Path) -> bool:
        return self.key(destination) in self._held

    @staticmethod
    def key(destination: Path) -> str:
        """One name per directory, whichever way it was spelled."""
        return os.path.normpath(str(destination.expanduser())).casefold()
