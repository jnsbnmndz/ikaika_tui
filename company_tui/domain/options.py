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

    INFO = "info"
    """Not an input: a value the workflow wants shown alongside the fields."""


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
