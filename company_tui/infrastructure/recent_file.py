"""The recently-picked directories, in one JSON file under the user's home.

Beside `sessions.json` and `updates.json`, and for the same three reasons: it is one
person's machine state rather than a setting a team shares, an installer update cannot
reach it there, and every failure is swallowed. A history that cannot be read is an empty
one and the picker simply opens on a tree; a history that cannot be written costs the
next glance, not the workflow.
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.recent import LIMIT, RecentPathsPort, remember

RECENT_PATH = naming.store_dir() / "recent.json"

VERSION = 1
"""Written into the file, checked before anything is read out of it. A file from a
future build is treated as empty rather than guessed at."""


class FileRecentPaths(RecentPathsPort):
    """`RecentPathsPort` over a JSON file."""

    def __init__(self, path: Path | None = None, limit: int = LIMIT) -> None:
        self._path = path if path is not None else RECENT_PATH
        self._limit = limit

    def recent(self) -> tuple[str, ...]:
        """The list, newest first, dropping anything that is no longer a directory.

        Filtered on the way OUT rather than pruned on the way in: a project on a drive
        that is not mounted this morning should come back when it is, and a history that
        forgot it the first time somebody unplugged the disk would be a history that
        quietly empties itself.
        """
        document = self._read()
        if document.get("version") != VERSION:
            return ()
        stored = document.get("paths")
        if not isinstance(stored, list):
            return ()
        found = []
        for entry in stored:
            if not isinstance(entry, str) or not entry.strip():
                continue
            with suppress(OSError):
                if Path(entry).is_dir():
                    found.append(entry)
        return tuple(found[: self._limit])

    def remember(self, chosen: str) -> None:
        # Read RAW rather than through `recent()`: that filters out what is not mounted
        # today, and writing the filtered list back is how an unplugged drive loses its
        # projects permanently.
        document = self._read()
        stored = document.get("paths") if document.get("version") == VERSION else []
        existing = tuple(entry for entry in stored if isinstance(entry, str)) if isinstance(stored, list) else ()
        self._write(
            {
                "version": VERSION,
                "paths": list(remember(existing, chosen, self._limit)),
            }
        )

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return document if isinstance(document, dict) else {}

    def _write(self, document: dict) -> None:
        with suppress(OSError, TypeError, ValueError):
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8"
            )
