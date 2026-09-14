"""What the last update check found, in one JSON file under the user's home."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.updates import (
    BUILD_DEBUG,
    BUILD_UNKNOWN,
    UpdateState,
    UpdateStatePort,
)

STATE_PATH = naming.store_dir() / "updates.json"
DEBUG_STATE_PATH = naming.store_dir() / "updates-debug.json"


def state_path(build: str = BUILD_UNKNOWN) -> Path:
    """Where this build's record lives. See the header."""
    return DEBUG_STATE_PATH if build == BUILD_DEBUG else STATE_PATH

VERSION = 1
"""Written into the file, checked before anything is read out of it."""

class FileUpdateState(UpdateStatePort):
    """`UpdateStatePort` over a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else STATE_PATH

    def load(self) -> UpdateState:
        document = self._read()
        if document.get("version") != VERSION:
            return UpdateState()
        return UpdateState(
            checked_at=str(document.get("checked_at", "")),
            tag=str(document.get("tag", "")),
            installer=str(document.get("installer", "")),
        )

    def save(self, state: UpdateState) -> None:
        self._write(
            {
                "version": VERSION,
                "checked_at": state.checked_at,
                "tag": state.tag,
                "installer": state.installer,
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
