"""The commands a project declares, as a list somebody can edit.

`script_config.py` reads that document to *run* it; this reads the same document to
*change* it, and writes back only the keys it changed. Everything else on an action -
its `args`, its `template`, its `messages`, whatever a later version of that document
grew - is preserved untouched, because this is somebody else's contract file and the
toolbox only owns the parts it offers to edit (`docs/decisions/0007`).

Telling an action from a group of them is `script_config.ACTION_MARKERS` and nothing
else: two answers to what an action is would be two menus that disagree.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from company_tui.domain import json_document
from company_tui.domain.json_document import Document
from company_tui.domain.script_config import ACTION_MARKERS, AFTER_SUCCESS, actions_from

CONFIG = "config"
DESCRIPTION = "description"
INTERACTIVE = "interactive"
VIEW = "view"

EDITABLE = (DESCRIPTION, AFTER_SUCCESS, INTERACTIVE, VIEW)
"""What the builder writes. Every other key on an action is read and put back."""

KEY_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
"""A section or action key is addressed as `section.key`, so it holds no dot and no
space - one of those is two names, and references would stop resolving."""


@dataclass(frozen=True, slots=True)
class Command:
    """One thing a project declares it can do."""

    section: str
    key: str = ""
    """Empty when the section is itself the action, as `config.build` is."""

    description: str = ""
    commands: tuple[str, ...] = ()
    interactive: bool = False
    view: str = ""

    kept: tuple[str, ...] = ()
    """Keys this carries that the builder preserves and does not offer to edit."""

    was: str = ""
    """Where it was before, so a rename can move what it carries rather than
    building a new one and losing everything the builder does not edit."""

    @property
    def identifier(self) -> str:
        return f"{self.section}.{self.key}" if self.key else self.section

    @property
    def at(self) -> tuple[str, ...]:
        return (CONFIG, self.section, self.key) if self.key else (CONFIG, self.section)


def is_key(value: Any) -> bool:
    """Whether this can name a section or an action."""
    return (
        isinstance(value, str)
        and bool(value)
        and all(letter in KEY_CHARACTERS for letter in value)
    )


def commands_from(document: Mapping[str, Any]) -> tuple[Command, ...]:
    """Every action the document declares, in the order it declares them."""
    config = document.get(CONFIG)
    if not isinstance(config, Mapping):
        return ()

    read: list[Command] = []
    for section, body in config.items():
        if not isinstance(body, Mapping):
            continue
        if any(marker in body for marker in ACTION_MARKERS):
            read.append(_command(section, "", body))
            continue
        for key, entry in body.items():
            if isinstance(entry, Mapping):
                read.append(_command(section, key, entry))
    return tuple(read)


def _command(section: str, key: str, body: Mapping[str, Any]) -> Command:
    lines = body.get(AFTER_SUCCESS)
    return Command(
        section=str(section),
        key=str(key),
        description=_text(body, DESCRIPTION),
        commands=tuple(str(one) for one in lines) if isinstance(lines, list) else (),
        interactive=body.get(INTERACTIVE) is True,
        view=_text(body, VIEW),
        kept=tuple(name for name in body if name not in EDITABLE),
        was=f"{section}.{key}" if key else str(section),
    )


def _text(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    return value if isinstance(value, str) else ""


def write_commands(
    document: Document, wanted: Sequence[Command]
) -> tuple[str, ...]:
    """Put `wanted` into `document` in place, and say what could not be done.

    Renames move what was there rather than replacing it, so an action keeps its
    arguments and its template when it is called something else. Anything the
    builder does not edit is never touched, and an action that is gone from
    `wanted` is gone from the document.
    """
    problems: list[str] = []
    held = {command.identifier: command.at for command in commands_from(document)}
    bodies = {name: json_document.read(document, at) for name, at in held.items()}

    keep: set[str] = set()
    for command in wanted:
        if not is_key(command.section) or (command.key and not is_key(command.key)):
            problems.append(
                f"'{command.identifier}' is not a usable name, so it was left out"
            )
            continue
        if command.identifier in keep:
            problems.append(f"'{command.identifier}' was named twice, so one was dropped")
            continue
        keep.add(command.identifier)

    for name, at in held.items():
        if name not in keep or _moved(name, wanted):
            json_document.discard(document, at)

    for command in wanted:
        if command.identifier not in keep:
            continue
        body = bodies.get(command.was) if command.was else None
        body = dict(body) if isinstance(body, dict) else {}
        problems.extend(_renamed(command, body))
        _place(document, command, body)

    stayed = {one.identifier for one in commands_from(document)}
    for name in keep - stayed:
        problems.append(f"'{name}' could not be written, so it was left out")
    return tuple(problems)


def _renamed(command: Command, body: Mapping[str, Any]) -> list[str]:
    """What a rename breaks, said rather than left to fail three menus later.

    An action's arguments are written `${<reference>.args.<flag>}`, and its
    reference is its own key. Renaming it leaves every one of those pointing at a
    name nothing answers - and an unanswered reference is left in place rather
    than blanked, so what fails is the run, with the text still in it.
    """
    before = command.was.split(".")[-1]
    after = command.key or command.section
    if not before or before == after:
        return []
    mentioned = "${" + before + "."
    if mentioned not in json.dumps(body, ensure_ascii=False):
        return []
    said = (
        f"'{command.identifier}' still writes {mentioned}...}} from when it was "
        f"'{before}'. Those have to become ${{{after}....}} by hand, or the run "
        "fails with the text still in it."
    )
    return [said]


def _moved(name: str, wanted: Sequence[Command]) -> bool:
    """Whether what was at `name` has been renamed and belongs somewhere else now."""
    return any(one.was == name and one.identifier != name for one in wanted)


def _place(document: Document, command: Command, body: dict[str, Any]) -> None:
    """Put one action where it belongs, making the group for it if there is none."""
    body[DESCRIPTION] = command.description
    body[AFTER_SUCCESS] = list(command.commands)
    if command.interactive:
        body[INTERACTIVE] = True
    else:
        body.pop(INTERACTIVE, None)
    if command.view:
        body[VIEW] = command.view
    else:
        body.pop(VIEW, None)
    if not command.description:
        body.pop(DESCRIPTION, None)

    config = document.setdefault(CONFIG, {})
    if not isinstance(config, dict):
        return
    if not command.key:
        config[command.section] = body
        return
    group = config.get(command.section)
    if not isinstance(group, dict) or any(marker in group for marker in ACTION_MARKERS):
        group = {}
        config[command.section] = group
    group[command.key] = body


def still_reads(document: Mapping[str, Any]) -> bool:
    """Whether the runner can still find actions in what was written.

    The same reader the menus are built from, asked about the result: a manifest
    this wrote and that one cannot read is the failure worth catching here rather
    than three menus later.
    """
    return bool(actions_from(document)) or not commands_from(document)
