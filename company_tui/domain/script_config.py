"""What a script repository says it can do.

Every repository the toolbox runs work out of carries an `ikaika.script.json` —
the same file that makes a directory an IKAIKA project. Past the four keys that
name it, a script repository declares two more: `rules`, saying which properties
an argument of each type may carry, and `config`, one section per kind of work
with an entry per action.

Nothing here touches a disk. It reads the document into actions, checks a filled
in form against the rules that document declared, and expands the `${...}`
references it is written in. Running the result is somebody else's job.

Everything is resolved against one map, so a config can say `${screen.path}` in
a message and mean exactly the directory the file was written to:

    ${root}                  the project the action was aimed at, absolute
    ${<action>.args.<flag>}  what the form came back with
    ${<action>.path}         the expanded path
    ${<action>.filename}     the expanded filename
    ${error}                 why it failed, for `message-error`

A path with no `${root}` in front of it belongs to the repository the config came
from rather than to the project. That is what lets one repository hold the
templates every project it serves is written from, and it is the only reason a
config needs two roots at all.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from company_tui.domain.options import Option, OptionKind, OptionValue

ROOT = "root"
"""The reference standing for the project an action is aimed at."""

ERROR = "error"

STRING = "string"
NUMBER = "number"
BOOLEAN = "boolean"
ARRAY = "array"
OBJECT = "object"

GLOBAL_RULES = "global"

DEFAULT_RULES: Mapping[str, tuple[str, ...]] = {
    GLOBAL_RULES: ("flag", "type", "required", "description", "default"),
    STRING: ("allowed_regex",),
    ARRAY: ("allowed_values",),
    OBJECT: ("required_keys",),
    NUMBER: ("min", "max"),
    BOOLEAN: (),
}
"""What a document that declares no `rules` of its own is read as declaring.

The vocabulary rather than a policy: `rules` is how a repository says which
constraints it writes, and a constraint the document did not claim is not
applied even when an argument carries it. A repository that drops
`allowed_regex` from `rules.string` has said its strings are unconstrained, and
quietly enforcing a pattern it stopped declaring would be this file overruling
the file it is meant to be reading.
"""

PLACEHOLDER = re.compile(r"\$\{([A-Za-z0-9_.\-]+)\}")

_ARGUMENT_REFERENCE = re.compile(r"\$\{[A-Za-z0-9_\-]+\.args\.([A-Za-z0-9_\-]+)\}")
_ARGUMENT_NAME = re.compile(r"[A-Za-z0-9_\-]+\.args\.([A-Za-z0-9_\-]+)")
_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

ACTION_MARKERS = ("args", "path", "template", "command-after-success")
"""Any of these makes a `config` entry one action rather than a group of them.

`config.scaffold` holds a dozen actions and `config.build` is one, and the two
are told apart by what they carry rather than by name, because a repository
gets to call its sections whatever it likes.
"""

SUCCESS = "message-success"
FAILURE = "message-error"
EXISTS = "message-exists"
INVALID_ARGS = "message-invalid-args"
INVALID_PATH = "message-invalid-path"
INVALID_TEMPLATE = "message-invalid-template"

AFTER_SUCCESS = "command-after-success"

OVERWRITE = "overwrite"
"""The flag an action declares to let a run write over what is already there.

A convention rather than a keyword, and the narrowest one that could work: only
a boolean argument spelled exactly this waives the refusal, and only for the
action that declared it. An action that never mentions it cannot be overwritten
at all, so the message a repository wrote for a collision stands exactly where
it stood. The alternative was reading the flags out of `command-after-success`,
which is guessing at a shell line to find out what a form already said.
"""

_TRUE_WORDS = ("1", "on", "true", "yes")


def humanise(key: str) -> str:
    """`apiEndpoint` as 'Api Endpoint' — a manifest key with a menu to appear on."""
    spaced = _WORD_BREAK.sub(" ", key).replace("-", " ").replace("_", " ")
    return " ".join(word[:1].upper() + word[1:] for word in spaced.split())


def expand(text: str, references: Mapping[str, str]) -> str:
    """Fill in every `${...}` this map has an answer for, and leave the rest.

    Left rather than blanked: `${root}/src` with the root blanked is `/src`,
    which is a real path to somewhere nobody chose. A reference that survives
    expansion is visible, and `unresolved` is what refuses to act on one.
    """
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

    @property
    def label(self) -> str:
        return humanise(self.flag)

    def reason_to_refuse(self, value: OptionValue) -> str:
        """Why this value cannot be used, or `""` if it can.

        Checked before anything is written rather than after: the messages a
        config declares for bad input exist so a typo costs a sentence, and a
        sentence is only cheaper than the alternative while the alternative has
        not happened yet.
        """
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
            return f"Runs the {humanise(self.section).lower()} workflow"
        target = f"{self.path}/{self.filename}" if self.filename else self.path
        stripped = target.replace(f"${{{ROOT}}}/", "").replace(f"${{{ROOT}}}", ".")
        return _ARGUMENT_REFERENCE.sub(lambda m: f"<{m.group(1)}>", stripped)

    @property
    def detail(self) -> str:
        """The one line the menu shows for whichever card has focus.

        The document's own words where it wrote any: a repository describing
        its arguments knows more about them than a table in this toolbox can.
        """
        described = next(
            (argument.description for argument in self.arguments if argument.description),
            "",
        )
        return described or self.summary

    @property
    def preview(self) -> str:
        """`summary` as a format string over a filled-in form, for an INFO row."""
        target = f"{self.path}/{self.filename}" if self.filename else self.path
        return _as_format_template(target)

    @property
    def writes_a_file(self) -> bool:
        return bool(self.template and self.filename)

    def message(self, key: str, references: Mapping[str, str], fallback: str = "") -> str:
        return expand(self.messages.get(key, "") or fallback, references)

    def references_from(self, values: Mapping[str, OptionValue]) -> dict[str, str]:
        """This action's arguments as the references a config writes them as.

        A declared boolean always comes out as one of two words, never as the
        empty string an unanswered field would leave. `--overwrite ""` is not a
        no to any program that reads it: it is a flag with a missing value, and
        what a reader makes of that is its own business.
        """
        return {
            f"{self.reference}.args.{argument.flag}": (
                _word(_as_flag(values.get(argument.flag, argument.default)))
                if argument.kind == BOOLEAN
                else _as_text(values.get(argument.flag, argument.default))
            )
            for argument in self.arguments
        }

    def overwrites(self, values: Mapping[str, OptionValue]) -> bool:
        """Whether this form asked for whatever is already there to be replaced.

        The answer to the argument the document declared, not a policy of this
        toolbox: a config that does not ask the question never gets a yes.
        """
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
    """Whether there is anything in the store at all, which is a different
    question from whether it is readable. Settings offers to install one and to
    replace the other, and telling them apart is the whole of that choice."""

    installed: str = ""
    """The version of the manifest in the store."""

    available: str = ""
    """The version of the manifest the remote has, when it was worth asking."""

    @property
    def stale(self) -> bool:
        """Whether the copy being run is a different one from what is published.

        Different rather than older: these are the manifest's own words and
        nothing here knows how a repository counts. Saying "0.1.0 is available"
        about a version somebody is deliberately sitting behind is a nuisance;
        pretending to order two strings nobody defined an order for is worse.
        """
        return bool(self.installed and self.available and self.installed != self.available)


ROOT_OPTION = Option(
    key=ROOT,
    label="Project",
    kind=OptionKind.PATH,
    default=".",
    required=True,
    help="The IKAIKA project this runs in — what ${root} means in the script config.",
)

TARGET_KEY = "target"


def action_options(action: ScriptAction, project_root: str = ".") -> tuple[Option, ...]:
    """The form for one action: where it runs, then what the document asks for."""
    options = [replace(ROOT_OPTION, default=project_root)]
    options += [
        _option_for(argument)
        # `${root}` is the project and nothing else, so an argument claiming that
        # name would answer the field above it rather than a field of its own.
        for argument in action.arguments
        if argument.flag != ROOT
    ]
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


def components(actions: Sequence[ScriptAction]) -> tuple[ScriptAction, ...]:
    """The actions that add a file to a project that already exists.

    Told apart by what they carry rather than by which section they sit in,
    the same way an action is told apart from a group of them: a repository
    gets to call its sections whatever it likes, and one that renamed
    `config.scaffold` would otherwise find its generators had left the menu.
    An action with a template and a filename puts a file somewhere; that is
    what Components is a menu of, and what Build is not.
    """
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


# ------------------------------------------------------------------- reading


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
    )


# ------------------------------------------------------------------ shaping


def _option_for(argument: ScriptArgument) -> Option:
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
        )
    return Option(
        key=argument.flag,
        label=argument.label,
        kind=OptionKind.TEXT,
        default=argument.default,
        required=argument.required,
        help=argument.description or _shape_help(argument),
    )


def _shape_help(argument: ScriptArgument) -> str:
    if argument.allowed_regex:
        return f"Must match {argument.allowed_regex}."
    if argument.kind == NUMBER:
        return "A number."
    return ""


def _as_format_template(text: str) -> str:
    """`${root}/x/${screen.args.name}.tsx` as `{root}/x/{name}.tsx`.

    An INFO row restates the current answers, and it does that through
    `str.format`, which reads braces of its own. Both alphabets are rewritten in
    one pass so a literal brace in a path cannot be mistaken for a field.
    """
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
    "AFTER_SUCCESS",
    "DEFAULT_RULES",
    "ERROR",
    "EXISTS",
    "FAILURE",
    "INVALID_ARGS",
    "INVALID_PATH",
    "INVALID_TEMPLATE",
    "OVERWRITE",
    "ROOT",
    "SUCCESS",
    "ScriptAction",
    "ScriptArgument",
    "ScriptCatalogue",
    "ScriptUpdate",
    "action_options",
    "actions_from",
    "components",
    "expand",
    "humanise",
    "unresolved",
    "workflows",
)
