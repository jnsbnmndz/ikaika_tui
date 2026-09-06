"""What a workflow needs from the user, described rather than asked for.

A capability or template pack declares its flags as `Option`s instead of driving
a sequence of prompts. That lets one presentation render them all at once as a
form, and another ask them one at a time, without either knowing the workflow.
"""

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
    """A directory. Typed like text, but a presentation may offer to browse for
    it — the answer is somewhere on this machine, and remembering exactly where
    is not something to ask of whoever is filling the form in."""

    FILE = "file"
    """A file. PATH's other half, and separate because the picker is: browsing
    for a file in a directory tree means never finding one."""

    MULTI = "multi"
    """Several of a known set, offered as one tick box per value.

    A single-select dropdown is the wrong control for an argument that takes
    more than one: it silently accepts one where two were meant, and nothing
    about it says several are allowed. The answer comes back comma-joined,
    which is the form a command line already reads a list in."""

    NUMBER = "number"
    """A number, with the field refusing anything that is not one.

    Its own kind rather than text with a hint, because the hint is advice and
    this is the difference between a typo caught in the form and one that
    reaches whatever the command hands its argument to."""

    INFO = "info"
    """Not an input: a value the workflow wants shown alongside the fields."""


@dataclass(frozen=True, slots=True)
class Refresh:
    """An action that re-computes one option's choices.

    A dropdown whose values were FETCHED can go out of date while a form is open,
    and re-fetching them may mean changing something on the machine - the branch
    list is brought up to date by deleting local branches whose remote is gone.

    So there are two commands, not one. `preview` reports what acting would do
    and does nothing; empty output means there is nothing to ask about. `command`
    acts. A front end runs the first, confirms only if it said something, and
    runs the second on a yes."""

    label: str = "Update"
    command: str = ""
    preview: str = ""

    values_command: str = ""
    """How to read the list back after acting, when that is a separate command.

    A declared refresh CHANGES something and reports what it did - it does not
    print the new list. The values used to be re-read from the document, and then
    the document stopped carrying them, so Update reported a success and left the
    dropdown exactly as it was."""

    lists_values: bool = False
    """Whether `command` prints the new values, or a sentence about what it did.

    A plain re-fetch of a list prints the list; a declared refresh acts on the
    machine and reports, and the values are read back out of the document
    afterwards. Told apart explicitly rather than by whether `preview` is empty,
    because that would make one behaviour the side effect of another."""

    @property
    def asks_first(self) -> bool:
        """Whether acting could change something worth confirming.

        A re-fetch of a list changes nothing, so there is nothing to ask about
        and no dialog to put in the way of a button press."""
        return bool(self.preview)

    @property
    def is_usable(self) -> bool:
        return bool(self.command)


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """What running a refresh produced.

    `choices` is the list as it stands AFTER acting, which is the whole point:
    the values on screen were fetched, and the refresh is what makes them
    current. Empty means the run failed or had nothing to offer, and the field
    keeps what it already had rather than emptying itself."""

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
    """For INFO options: a format string over the other values, so a row can
    restate what the current input will actually do (`"./{name}"`)."""

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
