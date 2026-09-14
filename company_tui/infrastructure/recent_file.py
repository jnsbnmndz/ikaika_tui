"""The recently-picked directories, in one JSON file under the user's home."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.recent import LIMIT, RecentPathsPort, remember

RECENT_PATH = naming.store_dir() / "recent.json"

VERSION = 1
"""Written into the file, checked before anything is read out of it. A file from a."""

class FileRecentPaths(RecentPathsPort):
    """`RecentPathsPort` over a JSON file."""

    def __init__(self, path: Path | None = None, limit: int = LIMIT) -> None:
        self._path = path if path is not None else RECENT_PATH
        self._limit = limit

    def recent(self) -> tuple[str, ...]:
        """The list, newest first, dropping anything that is no longer a directory."""
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
