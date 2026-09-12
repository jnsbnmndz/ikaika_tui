"""The directories somebody has picked before, newest first.

A folder picker that always opens on a tree and nothing else asks the same question every
time: where is that project again. The answer is almost always one of the last few
directories chosen, and this is the list of them.


IT LIVES WHERE AN UPDATE CANNOT REACH IT

Under the user's home, beside the remembered tabs and the update state - not in the
install directory. `scripts/installer.nsi` upgrades by running the old uninstaller and
then `RMDir /r` over the install folder, so anything kept there is gone on the next
update; and the uninstaller deliberately leaves the home store alone, because it holds
work rather than program files. That makes the home store the only place a history can
survive both.


ORDER IS THE WHOLE DATA STRUCTURE

Newest first, no duplicates, capped. `remember` is the only way in and it does all three,
so nothing else has to know the rules - and a path already in the list MOVES rather than
being appended, which is what makes the most recent thing the first thing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

LIMIT = 12
"""How many directories are kept.

Enough that a week of moving between a handful of projects stays covered, few enough that
the list is a glance rather than a scroll. A history nobody can read at a glance is a
tree with extra steps.
"""


def remember(paths: Sequence[str], chosen: str, limit: int = LIMIT) -> tuple[str, ...]:
    """`paths` with `chosen` at the front, deduplicated and capped.

    Pure, so the ordering rules are testable without a filesystem: the store's whole job
    is then reading and writing a list.

    Comparison is on the string as given. Two spellings of one directory - a trailing
    slash, a different case on Windows - would both be kept, and normalising here would
    mean this module deciding what a path IS, which belongs to whoever produced it. The
    picker hands over `Path.as_posix()` of a resolved path, so the spellings match.
    """
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
        """Put `chosen` at the front. Never raises: a history that cannot be
        written costs one convenience, not a workflow."""
        raise NotImplementedError
