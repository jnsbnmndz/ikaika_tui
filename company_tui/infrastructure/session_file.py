"""Tabs kept in one JSON file under the user's home."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.session_memory import RememberedSession

MEMORY_PATH = naming.store_dir() / "sessions.json"

VERSION = 1
"""Written into the file, read back before anything else."""

MAX_LOG_LINES = 500
"""As many lines as a session keeps in memory (`session.LOG_LIMIT`)."""

class FileSessionMemory:
    """`SessionMemory` over a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else MEMORY_PATH


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


    def remember(
        self, workspace: str, sessions: Sequence[RememberedSession]
    ) -> None:
        document = self._read()
        if document.get("version") != VERSION:
            document = {"version": VERSION, "workspaces": {}}
        workspaces = document.setdefault("workspaces", {})

        if sessions:
            workspaces[workspace] = {
                "sessions": [_entry_from(session) for session in sessions]
            }
        else:
            workspaces.pop(workspace, None)

        self._write(document)


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
    """One tab out of the file, or `None` if it is not one."""
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
