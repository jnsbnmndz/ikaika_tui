"""Tabs kept in one JSON file under the user's home.

Beside `ikaika.toml`'s user copy rather than in the project, because these are
one person's open tabs and not a setting a team shares — nobody wants a
colleague's half-filled form arriving in a pull request. Keyed by workspace all
the same, so two projects on one machine keep their own.

Every failure here is swallowed on purpose. A store that cannot be read is an
empty one and the app opens on a clean strip; a store that cannot be written
costs the user retyping a form next time, which is exactly what they were
losing before this existed. Neither is worth taking a workflow down for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from company_tui.domain.session_memory import RememberedSession

MEMORY_PATH = Path.home() / ".ikaika" / "sessions.json"

VERSION = 1
"""Written into the file, read back before anything else.

A file from a future version is left alone rather than guessed at: losing the
tabs of one session is a bad hour, and overwriting them with a misread of a
newer format is a worse one.
"""

MAX_LOG_LINES = 500
"""As many lines as a session keeps in memory (`session.LOG_LIMIT`).

Written out at the same cap it is held at, so a build that printed forty
thousand lines does not become a forty-thousand-line file on disk.
"""


class FileSessionMemory:
    """`SessionMemory` over a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else MEMORY_PATH

    # ------------------------------------------------------------------ read

    def remembered(self, workspace: str) -> tuple[RememberedSession, ...]:
        document = self._read()
        if document.get("version") != VERSION:
            return ()
        stored = document.get("workspaces", {}).get(workspace, {})
        sessions = stored.get("sessions", []) if isinstance(stored, dict) else []
        return tuple(
            remembered
            for entry in sessions
            if (remembered := _session_from(entry)) is not None
        )

    # ----------------------------------------------------------------- write

    def remember(
        self, workspace: str, sessions: Sequence[RememberedSession]
    ) -> None:
        document = self._read()
        if document.get("version") != VERSION:
            document = {"version": VERSION, "workspaces": {}}
        workspaces = document.setdefault("workspaces", {})

        # A workspace with nothing open is dropped rather than left as an empty
        # entry, so closing every tab in a project actually forgets it.
        if sessions:
            workspaces[workspace] = {
                "sessions": [_entry_from(session) for session in sessions]
            }
        else:
            workspaces.pop(workspace, None)

        self._write(document)

    # ------------------------------------------------------------------ disk

    def _read(self) -> dict:
        try:
            with self._path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, ValueError):
            return {}
        return document if isinstance(document, dict) else {}

    def _write(self, document: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside and moved into place: the app is closing when this
            # usually runs, and a half-written file is a file that reads as no
            # tabs at all next time.
            scratch = self._path.with_suffix(".json.tmp")
            with scratch.open("w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, ensure_ascii=False)
            scratch.replace(self._path)
        except (OSError, ValueError, TypeError):
            return


def _entry_from(session: RememberedSession) -> dict:
    return {
        "name": session.name,
        "base": session.base,
        "scope": list(session.scope),
        "steps": dict(session.steps),
        "title": session.title,
        "trail": list(session.trail),
        "values": dict(session.values),
        "log": [[message, marker] for message, marker in session.log[-MAX_LOG_LINES:]],
        "stamp": session.stamp,
    }


def _session_from(entry: object) -> RememberedSession | None:
    """One tab out of the file, or `None` if it is not one.

    Anything malformed is dropped rather than repaired: a tab is a convenience,
    and a convenience that raises on the way in is worse than a missing one.
    """
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return None
    steps = entry.get("steps")
    if not isinstance(steps, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in steps.items()
    ):
        return None
    scope = tuple(
        part for part in entry.get("scope", []) if isinstance(part, str)
    )
    trail = tuple(part for part in entry.get("trail", []) if isinstance(part, str))
    return RememberedSession(
        name=name,
        base=_text(entry.get("base")) or name,
        # A file written before `scope` was a field of its own falls back to the
        # trail, and only then to the steps. The trail is what the panel showed
        # over that tab, which is the scope in all but name; the steps may have
        # been trimmed by a workflow walking back to re-ask something, which is
        # exactly the reading that put a React Native tab in no strip at all.
        scope=scope or trail or tuple(steps.values()),
        steps=dict(steps),
        title=_text(entry.get("title")),
        trail=trail,
        values={
            key: value
            for key, value in (entry.get("values") or {}).items()
            if isinstance(key, str) and isinstance(value, (str, bool))
        },
        log=tuple(
            (line[0], line[1])
            for line in entry.get("log", [])
            if isinstance(line, list)
            and len(line) == 2
            and all(isinstance(part, str) for part in line)
        ),
        stamp=_text(entry.get("stamp")),
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
