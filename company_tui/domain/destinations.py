"""One run at a time per directory.

Scaffolding deletes and recreates the tree it is aimed at. Two runs aimed at the
same place is not a race either of them can win: one removes the directory the
other is halfway through cloning into, and what is left belongs to neither. Once
runs can happen side by side, this stops being theoretical.

Refused rather than queued. A second run silently waiting looks exactly like a
second run that has hung, and the honest answer — that something else is already
writing there — is one the user can act on.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class DestinationBusy(Exception):
    """Another run is already writing to that directory."""


class DestinationLocks:
    """Which directories are being written to right now, and by how many.

    Held in memory for the life of the app, because that is exactly as long as
    the runs it is protecting live.
    """

    def __init__(self) -> None:
        self._held: set[str] = set()

    def claim(self, destination: Path) -> None:
        """Take the directory, or say who has it.

        Separate from releasing it because the two genuinely straddle a task
        boundary: the claim has to happen before the work is handed over, or two
        runs both find the directory free and both start writing.
        """
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
        """One name per directory, whichever way it was spelled.

        Case-folded on purpose: on Windows `./Demo` and `./demo` are the same
        directory, and a lock that lets both through is not a lock. Elsewhere it
        only makes the lock more cautious than it needs to be, which is the side
        to be wrong on.
        """
        return os.path.normpath(str(destination.expanduser())).casefold()
