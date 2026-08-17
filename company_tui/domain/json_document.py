"""Editing a JSON file without reformatting the parts nobody asked about.

Scaffolding changes a handful of keys in files a person maintains afterwards.
Writing them back in this module's preferred style would turn a four-key edit
into a whole-file diff, so the indent the template chose is measured and reused,
and keys that are not ours are left in place and in order.
"""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

Document = dict[str, Any]
Path = Sequence[str]

DEFAULT_INDENT = "  "

_FIRST_INDENT = re.compile(r"^([ \t]+)\S", re.MULTILINE)


class MalformedJson(ValueError):
    """The file is not the JSON object it was expected to be."""


def load(source: str) -> Document:
    try:
        document = json.loads(source)
    except json.JSONDecodeError as error:
        raise MalformedJson(str(error)) from error
    if not isinstance(document, dict):
        raise MalformedJson("Expected a JSON object.")
    return document


def detect_indent(source: str) -> str:
    match = _FIRST_INDENT.search(source)
    return match.group(1) if match else DEFAULT_INDENT


def dump(document: Mapping[str, Any], indent: str = DEFAULT_INDENT) -> str:
    return json.dumps(document, indent=indent, ensure_ascii=False) + "\n"


def read(document: Document, path: Path) -> Any:
    cursor: Any = document
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def put(document: Document, path: Path, value: Any) -> bool:
    """Set `path`, but only where the template already has somewhere to put it.

    Absent sections are left absent rather than invented: a stack that ships no
    `ios` block did not forget one, and adding a bundle id to a platform the
    template does not target would be this toolbox making that decision.
    """
    parent = _parent(document, path)
    if parent is None:
        return False
    parent[path[-1]] = value
    return True


def discard(document: Document, path: Path) -> bool:
    """Drop `path`, and any section it leaves empty behind it."""
    parent = _parent(document, path)
    if parent is None or path[-1] not in parent:
        return False
    del parent[path[-1]]
    for depth in range(len(path) - 1, 0, -1):
        branch = _parent(document, path[:depth])
        if branch is None or branch.get(path[depth - 1]):
            break
        del branch[path[depth - 1]]
    return True


def _parent(document: Document, path: Path) -> Document | None:
    if not path:
        return None
    cursor: Any = document
    for key in path[:-1]:
        if not isinstance(cursor, dict) or not isinstance(cursor.get(key), dict):
            return None
        cursor = cursor[key]
    return cursor if isinstance(cursor, dict) else None
