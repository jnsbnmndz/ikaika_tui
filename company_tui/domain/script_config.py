"""What a script repository says it can do."""

import json
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from company_tui.domain.options import Option, OptionKind, OptionValue, Refresh

ROOT = "root"
"""The reference standing for the project an action is aimed at."""

ERROR = "error"

STRING = "string"
FILE = "file"
NUMBER = "number"
BOOLEAN = "boolean"
ARRAY = "array"
OBJECT = "object"
PATH = "path"
"""A string that names a directory."""

GLOBAL_RULES = "global"

DEFAULT_RULES: Mapping[str, tuple[str, ...]] = {
    GLOBAL_RULES: ("flag", "type", "required", "description", "default"),
    STRING: ("allowed_regex",),
    PATH: ("allowed_regex",),
    FILE: ("allowed_regex",),
    ARRAY: ("allowed_values",),
    OBJECT: ("required_keys",),
    NUMBER: ("min", "max"),
    BOOLEAN: (),
}
"""What a document that declares no `rules` of its own is read as declaring."""

PLACEHOLDER = re.compile(r"\$\{([A-Za-z0-9_.\-]+)\}")

_ARGUMENT_REFERENCE = re.compile(r"\$\{[A-Za-z0-9_\-]+\.args\.([A-Za-z0-9_\-]+)\}")
_ARGUMENT_NAME = re.compile(r"[A-Za-z0-9_\-]+\.args\.([A-Za-z0-9_\-]+)")
_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

ACTION_MARKERS = ("args", "path", "template", "command-after-success")
"""Any of these makes a `config` entry one action rather than a group of them."""

SUCCESS = "message-success"
FAILURE = "message-error"
EXISTS = "message-exists"
INVALID_ARGS = "message-invalid-args"
INVALID_PATH = "message-invalid-path"
INVALID_TEMPLATE = "message-invalid-template"

AFTER_SUCCESS = "command-after-success"
AFTER_CLONE = "after-clone-command"
"""What a repository needs run once, in itself, before it can serve anybody."""

OVERWRITE = "overwrite"
"""The flag an action declares to let a run write over what is already there."""

_TRUE_WORDS = ("1", "on", "true", "yes")


def split_command(raw: str) -> tuple[str, ...]:
    """One declared command as an argument array, with no shell involved."""
    try:
        return tuple(shlex.split(raw, posix=True))
    except ValueError:
        return ()


def executable_of(raw: str) -> str:
    """The program one declared command needs on the machine, or `""`."""
    tokens = split_command(raw)
    if not tokens:
        return ""
    name = tokens[0]
    if unresolved(name) or _looks_like_a_path(name):
        return ""
    return name


def _looks_like_a_path(name: str) -> bool:
    return name.startswith(".") or "/" in name or "\\" in name


def _distinct(names: Sequence[str]) -> tuple[str, ...]:
    """The names in the order they were declared in, each said once."""
    return tuple(dict.fromkeys(name for name in names if name))


def executables_from(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Every program this repository's own commands invoke."""
    return _distinct(
        [executable_of(command) for command in after_clone_from(document)]
        + [name for action in actions_from(document) for name in action.executables]
    )


def humanise(key: str) -> str:
    """`apiEndpoint` as 'Api Endpoint' — a manifest key with a menu to appear on."""
    spaced = _WORD_BREAK.sub(" ", key).replace("-", " ").replace("_", " ")
    return " ".join(word[:1].upper() + word[1:] for word in spaced.split())


def expand(text: str, references: Mapping[str, str]) -> str:
    """Fill in every `${...}` this map has an answer for, and leave the rest."""
    return PLACEHOLDER.sub(
        lambda match: references.get(match.group(1), match.group(0)), text
    )


def unresolved(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in PLACEHOLDER.finditer(text))


@dataclass(frozen=True, slots=True)
class ScriptArgument:
    """One flag an action asks for, and what the document says it may hold."""

    flag: str
    kind: str = STRING
    required: bool = False
    description: str = ""
    default: str = ""
    allowed_regex: str = ""
    allowed_values: tuple[str, ...] = ()
    required_keys: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    refresh: Refresh | None = None
    declared_label: str = ""
    """What the document calls this argument, if it said."""

    choices_command: str = ""
    """How to ask the command for this argument's real values."""

    @property
    def label(self) -> str:
        return self.declared_label or humanise(self.flag)

    def reason_to_refuse(self, value: OptionValue) -> str:
        """Why this value cannot be used, or `""` if it can."""
        if self.kind == BOOLEAN or isinstance(value, bool):
            return ""

        text = str(value).strip()
        if not text:
            return f"{self.label} is required." if self.required else ""

        if self.kind == NUMBER:
            return self._reason_number(text)
        if self.kind == ARRAY:
            return self._reason_array(text)
        if self.kind == OBJECT:
            return self._reason_object(text)
        if self.allowed_regex and not re.fullmatch(self.allowed_regex, text):
            return f"{self.label} must match {self.allowed_regex}."
        return ""

    def _reason_number(self, text: str) -> str:
        try:
            number = float(text)
        except ValueError:
            return f"{self.label} must be a number."
        if self.minimum is not None and number < self.minimum:
            return f"{self.label} must be at least {self.minimum:g}."
        if self.maximum is not None and number > self.maximum:
            return f"{self.label} must be at most {self.maximum:g}."
        return ""

    def _reason_array(self, text: str) -> str:
        if not self.allowed_values:
            return ""
        unknown = tuple(
            item
            for item in (part.strip() for part in text.split(","))
            if item and item not in self.allowed_values
        )
        if unknown:
            return (
                f"{self.label} does not take {', '.join(unknown)} — "
                f"choose from {', '.join(self.allowed_values)}."
            )
        return ""

    def _reason_object(self, text: str) -> str:
        try:
            document = json.loads(text)
        except ValueError:
            return f"{self.label} must be a JSON object."
        if not isinstance(document, dict):
            return f"{self.label} must be a JSON object."
        absent = tuple(key for key in self.required_keys if key not in document)
        if absent:
            return f"{self.label} is missing {', '.join(absent)}."
        return ""


@dataclass(frozen=True, slots=True)
class ScriptAction:
    """One thing a script repository knows how to do."""

    section: str
    key: str = ""
    """Empty when the section is itself the action, as `config.build` is."""

    arguments: tuple[ScriptArgument, ...] = ()
    path: str = ""
    template: str = ""
    filename: str = ""
    skipped: tuple[str, ...] = ()
    """Arguments the document refused to describe, named but never offered."""

    description: str = ""
    """What the repository says this action is for, in its own words."""

    messages: Mapping[str, str] = field(default_factory=dict)
    after_success: tuple[str, ...] = ()

    @property
    def reference(self) -> str:
        """What this action calls itself inside `${...}` — its key, or its section."""
        return self.key or self.section

    @property
    def identifier(self) -> str:
        return f"{self.section}.{self.key}" if self.key else self.section

    @property
    def name(self) -> str:
        return humanise(self.reference)

    @property
    def summary(self) -> str:
        """Where this writes, in the words the project would use for it."""
        if not self.path:
            return self.description or f"Runs the {humanise(self.section).lower()} workflow"
        target = f"{self.path}/{self.filename}" if self.filename else self.path
        stripped = target.replace(f"${{{ROOT}}}/", "").replace(f"${{{ROOT}}}", ".")
        return _ARGUMENT_REFERENCE.sub(lambda m: f"<{m.group(1)}>", stripped)

    @property
    def detail(self) -> str:
        """The one line the menu shows for whichever card has focus."""
        described = next(
            (argument.description for argument in self.arguments if argument.description),
            "",
        )
        return self.description or described or self.summary

    @property
    def preview(self) -> str:
        """`summary` as a format string over a filled-in form, for an INFO row."""
        target = f"{self.path}/{self.filename}" if self.filename else self.path
        return _as_format_template(target)

    @property
    def writes_a_file(self) -> bool:
        return bool(self.template and self.filename)

    @property
    def executables(self) -> tuple[str, ...]:
        """The programs this action's commands need on the machine."""
        return _distinct([executable_of(command) for command in self.after_success])

    def message(self, key: str, references: Mapping[str, str], fallback: str = "") -> str:
        return expand(self.messages.get(key, "") or fallback, references)

    def references_from(self, values: Mapping[str, OptionValue]) -> dict[str, str]:
        """This action's arguments as the references a config writes them as."""
        return {
            f"{self.reference}.args.{argument.flag}": (
                _word(_as_flag(values.get(argument.flag, argument.default)))
                if argument.kind == BOOLEAN
                else _as_text(values.get(argument.flag, argument.default))
            )
            for argument in self.arguments
        }

    def overwrites(self, values: Mapping[str, OptionValue]) -> bool:
        """Whether this form asked for whatever is already there to be replaced."""
        declared = next(
            (
                argument
                for argument in self.arguments
                if argument.flag == OVERWRITE and argument.kind == BOOLEAN
            ),
            None,
        )
        if declared is None:
            return False
        return _as_flag(values.get(OVERWRITE, declared.default))

    def reason_to_refuse(self, values: Mapping[str, OptionValue]) -> str:
        for argument in self.arguments:
            reason = argument.reason_to_refuse(values.get(argument.flag, argument.default))
            if reason:
                return reason
        return ""


class ScriptUpdate(Enum):
    """What to do about a store that has fallen behind the repository it came from."""

    RECLONE = "reclone"
    KEEP = "keep"
    SILENCE = "silence"


@dataclass(frozen=True, slots=True)
class ScriptCatalogue:
    """Everything one script repository offers, or why it offers nothing."""

    actions: tuple[ScriptAction, ...] = ()
    problem: str = ""
    location: str = ""
    present: bool = False
    """Whether there is anything in the store at all, which is a different."""

    installed: str = ""
    """The version of the manifest in the store."""

    available: str = ""
    """The version of the manifest the remote has, when it was worth asking."""

    executables: tuple[str, ...] = ()
    """What this repository's commands need on the machine."""

    @property
    def stale(self) -> bool:
        """Whether the copy being run is a different one from what is published."""
        return bool(self.installed and self.available and self.installed != self.available)


ROOT_OPTION = Option(
    key=ROOT,
    label="Project",
    kind=OptionKind.PATH,
    default=".",
    required=True,
    help="The project this runs in — what ${root} means in the script config.",
)

TARGET_KEY = "target"
SKIPPED_KEY = "skipped"


@dataclass(frozen=True, slots=True)
class ScriptSection:
    """One `config` section, and the actions declared under it."""

    key: str
    actions: tuple[ScriptAction, ...] = ()

    @property
    def name(self) -> str:
        return humanise(self.key)

    @property
    def summary(self) -> str:
        return f"{len(self.actions)} command{'' if len(self.actions) == 1 else 's'}"


def sections_from(actions: Sequence[ScriptAction]) -> tuple[ScriptSection, ...]:
    """The actions grouped as the document groups them, in declaration order."""
    grouped: dict[str, list[ScriptAction]] = {}
    for action in actions:
        grouped.setdefault(action.section, []).append(action)
    return tuple(
        ScriptSection(key=key, actions=tuple(members))
        for key, members in grouped.items()
    )


def action_options(action: ScriptAction, project_root: str = ".") -> tuple[Option, ...]:
    """The form for one action: where it runs, then what the document asks for."""
    options = [replace(ROOT_OPTION, default=project_root)]
    options += [
        _option_for(argument)
        for argument in action.arguments
        if argument.flag != ROOT
    ]
    if action.skipped:
        options.append(
            Option(
                key=SKIPPED_KEY,
                label="Not shown here",
                kind=OptionKind.INFO,
                default=(
                    ", ".join(f"-{name}" for name in action.skipped)
                    + " - a form will not collect a credential. Pass it on the "
                    "command line, or put it in the environment."
                ),
            )
        )
    if action.path:
        options.append(
            Option(
                key=TARGET_KEY,
                label="Creates" if action.writes_a_file else "Runs in",
                kind=OptionKind.INFO,
                default=action.summary,
                template=action.preview,
            )
        )
    return tuple(options)


def command_preview(action: ScriptAction, values: Mapping[str, OptionValue]) -> str:
    """What the run will actually be, in the words somebody could type instead."""
    name = f"{action.section}/{action.key}" if action.key else action.section
    parts = [f".{chr(92)}script.ps1 {name}"]
    for argument in action.arguments:
        value = values.get(argument.flag, "")
        if argument.kind == BOOLEAN:
            if _as_flag(value):
                parts.append(f"-{argument.flag}")
            continue
        text = _as_text(value).strip()
        if not text:
            continue
        shown = f"'{text}'" if " " in text else text
        parts.append(f"-{argument.flag} {shown}")
    return " ".join(parts)


def after_clone_from(document: Mapping[str, Any]) -> tuple[str, ...]:
    """The setup this repository says it needs, in the order it wrote them."""
    declared = document.get(AFTER_CLONE)
    return tuple(
        str(command)
        for command in (declared if isinstance(declared, list) else ())
        if str(command).strip()
    )


def components(actions: Sequence[ScriptAction]) -> tuple[ScriptAction, ...]:
    """The actions that add a file to a project that already exists."""
    return tuple(action for action in actions if action.writes_a_file)


def workflows(actions: Sequence[ScriptAction]) -> tuple[ScriptAction, ...]:
    """The actions that run something rather than write a file — Build's menu."""
    return tuple(action for action in actions if not action.writes_a_file)


def actions_from(document: Mapping[str, Any]) -> tuple[ScriptAction, ...]:
    rules = _rules_from(document.get("rules"))
    config = document.get("config")
    if not isinstance(config, dict):
        return ()

    actions: list[ScriptAction] = []
    for section, body in config.items():
        if not isinstance(body, dict):
            continue
        if any(marker in body for marker in ACTION_MARKERS):
            actions.append(_action_from(section, "", body, rules))
            continue
        for key, entry in body.items():
            if isinstance(entry, dict):
                actions.append(_action_from(section, key, entry, rules))
    return tuple(actions)


def _rules_from(declared: object) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(declared, dict):
        return DEFAULT_RULES
    return {
        name: tuple(str(item) for item in properties)
        for name, properties in declared.items()
        if isinstance(properties, list)
    } or DEFAULT_RULES


def _action_from(
    section: str, key: str, entry: Mapping[str, Any], rules: Mapping[str, tuple[str, ...]]
) -> ScriptAction:
    declared = entry.get("args")
    arguments = tuple(
        _argument_from(item, rules)
        for item in (declared if isinstance(declared, list) else ())
        if isinstance(item, dict) and item.get("flag")
    )
    commands = entry.get(AFTER_SUCCESS)
    return ScriptAction(
        section=section,
        key=key,
        arguments=arguments,
        path=str(entry.get("path", "")),
        template=str(entry.get("template", "")),
        filename=str(entry.get("filename", "")),
        description=str(entry.get("description", "")),
        skipped=tuple(
            str(name) for name in entry.get("skipped", []) if isinstance(name, str)
        ),
        messages={
            name: str(value)
            for name, value in entry.items()
            if name.startswith("message-") and isinstance(value, str)
        },
        after_success=tuple(
            str(command)
            for command in (commands if isinstance(commands, list) else ())
            if str(command).strip()
        ),
    )


def _argument_from(
    entry: Mapping[str, Any], rules: Mapping[str, tuple[str, ...]]
) -> ScriptArgument:
    kind = str(entry.get("type", STRING)) or STRING
    allowed = set(rules.get(GLOBAL_RULES, ())) | set(rules.get(kind, ()))

    def declared(name: str, fallback: Any = None) -> Any:
        return entry.get(name) if name in allowed else fallback

    values = declared("allowed_values")
    keys = declared("required_keys")
    return ScriptArgument(
        flag=str(entry["flag"]),
        kind=kind,
        required=bool(declared("required", False)),
        description=str(declared("description", "") or ""),
        default=_as_text(declared("default", "")),
        allowed_regex=str(declared("allowed_regex", "") or ""),
        allowed_values=tuple(str(item) for item in values) if isinstance(values, list) else (),
        required_keys=tuple(str(item) for item in keys) if isinstance(keys, list) else (),
        minimum=_as_number(declared("min")),
        maximum=_as_number(declared("max")),
        refresh=_refresh_from(declared("refresh")),
        choices_command=str(declared("choices", "") or ""),
        declared_label=str(declared("label", "") or ""),
    )


def _refresh_from(declared: object) -> Refresh | None:
    """The Update action an argument declares, or `None`."""
    if not isinstance(declared, dict):
        return None
    command = str(declared.get("command", "") or "")
    preview = str(declared.get("preview", "") or "")
    if not command or not preview:
        return None
    return Refresh(
        label=str(declared.get("label", "") or "Update"),
        command=command,
        preview=preview,
    )


def _option_for(argument: ScriptArgument) -> Option:
    refresh = _refresh_for(argument)
    if argument.kind == ARRAY and argument.allowed_values:
        return Option(
            key=argument.flag,
            label=argument.label,
            kind=OptionKind.MULTI,
            choices=argument.allowed_values,
            default=argument.default,
            required=argument.required,
            help=argument.description or _shape_help(argument),
            refresh=refresh,
        )
    if argument.kind == NUMBER:
        return Option(
            key=argument.flag,
            label=argument.label,
            kind=OptionKind.NUMBER,
            default=argument.default,
            required=argument.required,
            help=argument.description or _shape_help(argument),
            minimum=argument.minimum,
            maximum=argument.maximum,
        )
    if argument.kind in (PATH, FILE) and not argument.allowed_values:
        return Option(
            key=argument.flag,
            label=argument.label,
            kind=OptionKind.PATH if argument.kind == PATH else OptionKind.FILE,
            default=argument.default,
            required=argument.required,
            help=argument.description,
        )
    if argument.kind == BOOLEAN:
        return Option(
            key=argument.flag,
            label=argument.label,
            kind=OptionKind.BOOLEAN,
            default=_as_flag(argument.default),
            help=argument.description,
        )
    if argument.allowed_values:
        return Option(
            key=argument.flag,
            label=argument.label,
            kind=OptionKind.CHOICE,
            choices=argument.allowed_values,
            default=argument.default or argument.allowed_values[0],
            required=argument.required,
            help=argument.description,
            refresh=refresh,
        )
    return Option(
        key=argument.flag,
        label=argument.label,
        kind=OptionKind.TEXT,
        default=argument.default,
        required=argument.required,
        help=argument.description or _shape_help(argument),
    )


def _refresh_for(argument: ScriptArgument) -> Refresh | None:
    """How to bring this argument's list up to date, if there is a way."""
    if argument.refresh is not None:
        return replace(argument.refresh, values_command=argument.choices_command)
    if argument.choices_command:
        return Refresh(
            label="Update", command=argument.choices_command, lists_values=True
        )
    return None


def _shape_help(argument: ScriptArgument) -> str:
    if argument.allowed_regex:
        return f"Must match {argument.allowed_regex}."
    if argument.kind == NUMBER:
        low, high = argument.minimum, argument.maximum
        if low is not None and high is not None:
            return f"A number between {_plain(low)} and {_plain(high)}."
        if low is not None:
            return f"A number, {_plain(low)} or more."
        if high is not None:
            return f"A number, {_plain(high)} or less."
        return "A number."
    if argument.kind == ARRAY and argument.allowed_values:
        return "Choose as many as apply."
    return ""


def _plain(value: float) -> str:
    """`8080` rather than `8080.0` - the document wrote an integer."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _as_format_template(text: str) -> str:
    """`${root}/x/${screen.args.name}.tsx` as `{root}/x/{name}.tsx`."""
    pieces: list[str] = []
    cursor = 0
    for match in PLACEHOLDER.finditer(text):
        pieces.append(_escaped(text[cursor : match.start()]))
        name = match.group(1)
        argument = _ARGUMENT_NAME.fullmatch(name)
        if name == ROOT:
            pieces.append(f"{{{ROOT}}}")
        elif argument is not None:
            pieces.append(f"{{{argument.group(1)}}}")
        else:
            pieces.append(_escaped(match.group(0)))
        cursor = match.end()
    pieces.append(_escaped(text[cursor:]))
    return "".join(pieces)


def _escaped(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def _as_text(value: object) -> str:
    if isinstance(value, bool):
        return _word(value)
    return "" if value is None else str(value)


def _word(value: bool) -> str:
    return "true" if value else "false"


def _as_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_WORDS


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


__all__: Sequence[str] = (
    "AFTER_CLONE",
    "AFTER_SUCCESS",
    "DEFAULT_RULES",
    "ERROR",
    "EXISTS",
    "FAILURE",
    "FILE",
    "INVALID_ARGS",
    "INVALID_PATH",
    "INVALID_TEMPLATE",
    "OVERWRITE",
    "PATH",
    "ROOT",
    "SUCCESS",
    "ScriptAction",
    "ScriptArgument",
    "ScriptCatalogue",
    "ScriptSection",
    "ScriptUpdate",
    "action_options",
    "actions_from",
    "after_clone_from",
    "command_preview",
    "components",
    "executable_of",
    "executables_from",
    "expand",
    "humanise",
    "sections_from",
    "split_command",
    "unresolved",
    "workflows",
)
