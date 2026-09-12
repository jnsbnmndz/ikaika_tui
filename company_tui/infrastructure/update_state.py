"""What the last update check found, in one JSON file under the user's home.

Beside `sessions.json` and for the same reasons: it is one person's machine state rather
than a setting a team shares, and every failure is swallowed. A state that cannot be read
is an empty one, which costs one redundant request; a state that cannot be written costs
one redundant request next launch. Neither is worth taking a launch down for, and a
launch-time update check is the last thing in this app that should be able to stop it
starting.

NOT keyed by workspace, unlike the tabs. The tabs of one project are not the tabs of
another, but one update is one update - and keyed by directory, opening the app in a
second checkout would re-download the same installer under a second key.

KEYED BY LINE, THOUGH, BECAUSE "ONE COPY ON THE MACHINE" IS NOT TRUE

That was the original reasoning and it was wrong: a debug build and a release build are
two separate installs by design, and somebody testing a prerelease has BOTH. Sharing one
file, they fought over it. The debug build recorded the installer it had fetched; the
release build started, found a newer version recorded and offered it - which installs a
second app and leaves the release build exactly where it was (`docs/pitfalls.md` 6.6,
reached past the guard in `choose` that was meant to close it). And going the other way,
the release build's own check overwrote the record, so the debug build re-downloaded
thirty megabytes it already had.

So the debug build gets `updates-debug.json` and everything else keeps `updates.json`.
The release build's existing file is therefore still its own, which is why the split
needs no migration.
"""

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
    """Where this build's record lives. See the header.

    The source checkout shares the release build's file, and harmlessly: it can
    install nothing, so the worst it does is record an answer the release build
    would have got anyway.
    """
    return DEBUG_STATE_PATH if build == BUILD_DEBUG else STATE_PATH

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
