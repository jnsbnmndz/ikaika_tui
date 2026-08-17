"""A project name the toolbox is willing to build a project out of.

One string becomes a directory, a package identifier, a URL scheme and a bundle
id, and every stack spells those differently. Parsing the name once puts that
spelling in a single place — and refusing the strings that are not names keeps
`..`, `.` and absolute paths away from the code that deletes directories.
"""

import re
from dataclasses import dataclass

MAX_LENGTH = 64

_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*$")
_WORD_BREAK = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")

_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in "123456789"}
    | {f"lpt{digit}" for digit in "123456789"}
)


class InvalidProjectName(ValueError):
    """The string cannot become a directory and an identifier at the same time."""


@dataclass(frozen=True, slots=True)
class ProjectName:
    raw: str

    @classmethod
    def parse(cls, value: str) -> "ProjectName":
        name = value.strip()
        if not name:
            raise InvalidProjectName("Give the project a name.")
        if len(name) > MAX_LENGTH:
            raise InvalidProjectName(f"Keep the name under {MAX_LENGTH} characters.")
        if any(character in name for character in "/\\:"):
            raise InvalidProjectName(
                "A name is not a path — it cannot contain '/', '\\' or ':'."
            )
        if ".." in name or name.strip(".") == "":
            raise InvalidProjectName("A name cannot be made of dots.")
        if not _SHAPE.match(name):
            raise InvalidProjectName(
                "Start with a letter, then letters, digits, '-' or '_', "
                "one separator at a time and never at the end."
            )
        if name.lower() in _RESERVED:
            raise InvalidProjectName(f"'{name}' is a reserved device name on Windows.")
        return cls(raw=name)

    @classmethod
    def existing(cls, value: str) -> "ProjectName":
        """A name that is already written down somewhere, taken as it is.

        `parse` guards names the toolbox is about to turn into a directory. This
        is for reading one back out of a project's own manifest, where it may
        have been hand-edited into something `parse` would refuse — a project
        that already exists is not made invalid by being asked its name.
        """
        return cls(raw=value.strip())

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(word for word in _WORD_BREAK.split(self.raw) if word)

    @property
    def slug(self) -> str:
        """`demo-app` — package names, Expo slugs, repository names."""
        return "-".join(word.lower() for word in self.words)

    @property
    def snake(self) -> str:
        """`demo_app` — Python packages and directory names."""
        return "_".join(word.lower() for word in self.words)

    @property
    def compact(self) -> str:
        """`demoapp` — URL schemes and the last segment of a bundle id, which
        allow neither separators nor capitals."""
        return "".join(word.lower() for word in self.words)

    @property
    def pascal(self) -> str:
        """`DemoApp` — component, class and screen names."""
        return "".join(word[:1].upper() + word[1:] for word in self.words)

    @property
    def camel(self) -> str:
        """`demoApp` — variables, functions and hook names."""
        pascal = self.pascal
        return pascal[:1].lower() + pascal[1:]

    @property
    def title(self) -> str:
        """`Demo App` — what a person reads."""
        return " ".join(word[:1].upper() + word[1:] for word in self.words)

    def __str__(self) -> str:
        return self.raw
