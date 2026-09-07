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
"""A string that names a directory.

Its own type rather than a string with a convention, because the difference is
what the form can offer: a PATH row gets a picker, and a text row asking for a
directory is a box somebody has to remember the answer to."""

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
AFTER_CLONE = "after-clone-command"
"""What a repository needs run once, in itself, before it can serve anybody.

A script repository is a program as well as a pile of templates, and a
program that was cloned is not a program that was installed. Declared at the
top of the document rather than inside `config` because it belongs to the
repository rather than to any action in it: it runs at the clone, once, and
no workflow can ask for it."""

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


def split_command(raw: str) -> tuple[str, ...]:
    """One declared command as an argument array, with no shell involved.

    Split before any reference is filled in, never after. A Windows path
    substituted first arrives full of backslashes, every one of which is an
    escape to the splitter, and `C:\\src` comes back out as `C:src` — a path to
    somewhere that does not exist and, occasionally, to somewhere that does.
    """
    try:
        return tuple(shlex.split(raw, posix=True))
    except ValueError:
        return ()


def executable_of(raw: str) -> str:
    """The program one declared command needs on the machine, or `""`.

    Empty for the two cases nothing can be said about. A name written as a
    reference is not known until a form has been filled in, and this question
    is asked before there is one. A name with a path in it is a file in the
    repository rather than a program on the PATH — `node` is a tool, and
    `scripts/build.mjs` is an argument to it.
    """
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
    """Every program this repository's own commands invoke.

    Derived rather than declared, because it cannot then drift: this is token
    zero of the command that is actually going to run. A repository that starts
    calling `pnpm` says so by calling it, and a hand-kept list somewhere else
    would be a second copy of that fact with nothing keeping the two in step.
    """
    return _distinct(
        [executable_of(command) for command in after_clone_from(document)]
        + [name for action in actions_from(document) for name in action.executables]
    )


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
    refresh: Refresh | None = None
    declared_label: str = ""
    """What the document calls this argument, if it said.

    The WPF form prints `-Branch   [String]` - the flag as it would be typed and
    the type it expects - and a document written by that toolkit says so. Anything
    else falls through to `humanise`, which is right for a manifest whose flags are
    written for people (`apiEndpoint`) rather than for a shell."""

    choices_command: str = ""
    """How to ask the command for this argument's real values.

    Carried instead of `allowed_values` wherever the list was fetched rather than
    declared: a fetched list is local state - a branch list is this machine's -
    and a committed document has no business holding it. The values are asked for
    when the form opens, which is when the WPF dialog asks for them too."""

    @property
    def label(self) -> str:
        return self.declared_label or humanise(self.flag)

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
    skipped: tuple[str, ...] = ()
    """Arguments the document refused to describe, named but never offered.

    A credential has no field here and no default; what the name buys is the
    sentence saying so, because a parameter silently absent reads as one that does
    not exist rather than one that is deliberately not asked for."""

    description: str = ""
    """What the repository says this action is for, in its own words.

    Preferred over anything derived from the section name: a document that
    bothered to describe an action knows more about it than "Runs the git
    workflow", which is all a section of ten commands can otherwise say about
    any one of them."""

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
        """The one line the menu shows for whichever card has focus.

        The document's own words where it wrote any: a repository describing
        its arguments knows more about them than a table in this toolbox can.
        """
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

    executables: tuple[str, ...] = ()
    """What this repository's commands need on the machine.

    Part of what a store offers, because it is the half a machine can fail to
    hold up: Doctor reads it to report the tools a stack actually calls rather
    than the ones a pack remembered to list."""

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
    """The actions grouped as the document groups them, in declaration order.

    A menu per section rather than one menu of everything, because a repository
    that declares fifty actions has already said how it thinks about them — and
    fifty cards in one grid is a list to scroll rather than a choice to make.
    A section carrying one action still gets a card: skipping it would make the
    depth of the menu depend on how much a repository happened to declare.
    """
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
        # `${root}` is the project and nothing else, so an argument claiming that
        # name would answer the field above it rather than a field of its own.
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
    """What the run will actually be, in the words somebody could type instead.

    The same rules the run itself uses, because a preview that disagrees with the
    run is worse than none: an unanswered field is OMITTED rather than passed as an
    empty string, a switch appears as a bare flag only when it is on, and a
    multi-select is comma-joined.

    Mirrors `Get-ParamCommandPreview` in the WPF form, which is what makes the two
    front ends say the same thing about the same answers.
    """
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
    """The Update action an argument declares, or `None`.

    Both commands are required. One without the other is either an action that
    cannot be previewed - so it would act unasked - or a preview with nothing
    behind it, and neither is worth drawing a button for.
    """
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


# ------------------------------------------------------------------ shaping


def _option_for(argument: ScriptArgument) -> Option:
    refresh = _refresh_for(argument)
    # Order matters. An ARRAY with a declared set is several of that set, and
    # asking the `allowed_values` question first would hand it the single-select
    # dropdown - which accepts one where two were meant and says nothing.
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
    """How to bring this argument's list up to date, if there is a way.

    A command that DECLARES a refresh wins: it can do more than re-read - the
    branch list is brought up to date by deleting branches whose remote is gone,
    and the tag list by fetching from the remote.

    Otherwise, any list that was fetched can simply be fetched again. The desktop
    form does not offer that - its Update button exists only where a refresh
    provider does - but here the fetch is a declared command, so there is no
    reason a list read when the form opened cannot be read again. It changes
    nothing, so it never asks.
    """
    if argument.refresh is not None:
        # The fetch is carried alongside, because acting and reading the result
        # back are two different commands here.
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
