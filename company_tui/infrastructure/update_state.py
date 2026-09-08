"""What the last update check found, in one JSON file under the user's home.

Beside `sessions.json` and for the same reasons: it is one person's machine state rather
than a setting a team shares, and every failure is swallowed. A state that cannot be read
is an empty one, which costs one redundant request; a state that cannot be written costs
one redundant request next launch. Neither is worth taking a launch down for, and a
launch-time update check is the last thing in this app that should be able to stop it
starting.

NOT keyed by workspace, unlike the tabs. The tabs of one project are not the tabs of
another, but there is one copy of this toolbox on the machine and one update for it - and
keyed by directory, opening the app in a second checkout would re-download the same
installer under a second key.
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.updates import UpdateState, UpdateStatePort

STATE_PATH = naming.store_dir() / "updates.json"

VERSION = 1
"""Written into the file, checked before anything is read out of it.

A file from a future build is treated as empty rather than guessed at. The cost of that
is one check; the cost of misreading a newer format is a path this build hands to a
detached process and asks Windows to execute.
"""


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
