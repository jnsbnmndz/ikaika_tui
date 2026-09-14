"""What a workflow needs from the user, described rather than asked for."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

OptionValue = str | bool
OptionValues = Mapping[str, OptionValue]


class OptionKind(Enum):
    TEXT = "text"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    PATH = "path"
    """A directory. Typed like text, but a presentation may offer to browse for."""

    FILE = "file"
    """A file. PATH's other half, and separate because the picker is: browsing."""

    MULTI = "multi"
    """Several of a known set, offered as one tick box per value."""

    NUMBER = "number"
    """A number, with the field refusing anything that is not one."""

    INFO = "info"
    """Not an input: a value the workflow wants shown alongside the fields."""

@dataclass(frozen=True, slots=True)
class Refresh:
    """An action that re-computes one option's choices."""

    label: str = "Update"
    command: str = ""
    preview: str = ""

    values_command: str = ""
    """How to read the list back after acting, when that is a separate command."""

    lists_values: bool = False
    """Whether `command` prints the new values, or a sentence about what it did."""

    @property
    def asks_first(self) -> bool:
        """Whether acting could change something worth confirming."""
        return bool(self.preview)

    @property
    def is_usable(self) -> bool:
        return bool(self.command)


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """What running a refresh produced."""

    message: str = ""
    choices: tuple[str, ...] = ()
    ok: bool = True


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    label: str
    kind: OptionKind = OptionKind.TEXT
    default: OptionValue = ""
    choices: tuple[str, ...] = ()
    help: str = ""
    required: bool = False
    template: str = ""
    """For INFO options: a format string over the other values, so a row can."""

    minimum: float | None = None
    maximum: float | None = None
    """For NUMBER options: the range the document declared, if it declared one."""

    refresh: "Refresh | None" = None
    """For a CHOICE whose values were fetched: how to fetch them again."""

    @property
    def is_input(self) -> bool:
        return self.kind is not OptionKind.INFO

    def render(self, values: OptionValues) -> str:
        if not self.template:
            return str(self.default)
        try:
            return self.template.format(**values)
        except (KeyError, IndexError):
            return str(self.default)


def defaults_for(options: tuple[Option, ...]) -> dict[str, OptionValue]:
    return {option.key: option.default for option in options if option.is_input}


def missing_required(options: tuple[Option, ...], values: OptionValues) -> tuple[str, ...]:
    return tuple(
        option.label
        for option in options
        if option.is_input and option.required and not str(values.get(option.key, "")).strip()
    )
