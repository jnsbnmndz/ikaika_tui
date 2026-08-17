from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from company_tui.domain.config import TemplateSource
from company_tui.domain.identity import ProjectIdentity
from company_tui.domain.options import Option, OptionKind, OptionValue, OptionValues
from company_tui.domain.project_name import ProjectName


class ScaffoldTarget(Enum):
    NEW_PROJECT = "new_project"
    CONTROLLER = "controller"


@dataclass(frozen=True, slots=True)
class ScaffoldTargetOption:
    target: ScaffoldTarget
    name: str
    description: str


SCAFFOLD_TARGET_OPTIONS: tuple[ScaffoldTargetOption, ...] = (
    ScaffoldTargetOption(
        target=ScaffoldTarget.NEW_PROJECT,
        name="New Project",
        description="Create a new project from a template pack",
    ),
    ScaffoldTargetOption(
        target=ScaffoldTarget.CONTROLLER,
        name="Components",
        description="Add a controller to an existing project",
    ),
)


@dataclass(frozen=True, slots=True)
class TemplatePackInfo:
    key: str
    name: str
    version: str
    description: str


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    """An executable a pack needs, declared so it can be checked before it is used.

    Doctor asks every pack for these and reports them together, and a pack asks
    for its own before it starts, so a missing tool costs a sentence rather than
    a half-finished directory. Tools behind an optional step are declared too —
    they are worth reporting, just not worth refusing to start over.
    """

    executable: str
    purpose: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class Generator:
    """One kind of file a pack can add to a project that already exists."""

    key: str
    name: str
    description: str
    folder: str
    """Where this kind of file conventionally lives, offered as an editable default."""


NAME_OPTION = Option(
    key="name",
    label="Project name",
    kind=OptionKind.TEXT,
    required=True,
    help="Letters, digits, '-' and '_'. Becomes the directory, package and bundle id.",
)

TITLE_OPTION = Option(
    key="title",
    label="Title",
    kind=OptionKind.TEXT,
    help="Shown to people. Defaults to the project name in title case.",
)

DESCRIPTION_OPTION = Option(
    key="description",
    label="Description",
    kind=OptionKind.TEXT,
    help="Recorded in ikaika.script.json. Defaults to 'A <title> project'.",
)

PARENT_OPTION = Option(
    key="parent",
    label="Parent directory",
    kind=OptionKind.PATH,
    default=".",
    help="Where the project directory is created. Browse, or type '.' for here.",
)

DESTINATION_OPTION = Option(
    key="destination",
    label="Destination",
    kind=OptionKind.INFO,
    template="{parent}/{name}",
)

def project_options(parent: str = ".") -> tuple[Option, ...]:
    """The form every new project starts from, rooted where the company keeps them.

    The parent is a default rather than a constant because `workspace_root` in
    `ikaika.toml` is where a team says "projects live here", and a form that
    ignored it would make everyone retype the same path.
    """
    return (
        NAME_OPTION,
        TITLE_OPTION,
        DESCRIPTION_OPTION,
        replace(PARENT_OPTION, default=parent),
        DESTINATION_OPTION,
    )


NEW_PROJECT_OPTIONS: tuple[Option, ...] = project_options()

GENERATOR_KEY = "generator"
FOLDER_KEY = "folder"


def generator_options(generators: tuple[Generator, ...]) -> tuple[Option, ...]:
    """The form for adding a file to a project that already exists.

    Nothing here is a project name, so the destination is a folder inside the
    current project rather than a new directory beside it.
    """
    if not generators:
        return ()
    return (
        Option(
            key=GENERATOR_KEY,
            label="Generate",
            kind=OptionKind.CHOICE,
            choices=tuple(generator.key for generator in generators),
            default=generators[0].key,
            help=" · ".join(f"{g.key}: {g.description}" for g in generators),
        ),
        Option(
            key="name",
            label="Name",
            kind=OptionKind.TEXT,
            required=True,
            help="Written out in the casing each file needs — 'user_profile' works.",
        ),
        Option(
            key=FOLDER_KEY,
            label="Folder",
            kind=OptionKind.TEXT,
            default=generators[0].folder,
            help="Relative to the project root. Change it to match where you keep these.",
        ),
        Option(
            key="target",
            label="Target",
            kind=OptionKind.INFO,
            template="./{folder}/",
        ),
    )


@dataclass(frozen=True, slots=True)
class ScaffoldContext:
    target: ScaffoldTarget
    identity: ProjectIdentity
    destination: Path
    values: Mapping[str, OptionValue] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.identity.name.raw

    def flag(self, key: str, default: OptionValue = "") -> OptionValue:
        return self.values.get(key, default)


def context_from(target: ScaffoldTarget, values: OptionValues) -> ScaffoldContext:
    """Turn a filled-in form into something a pack can act on.

    The name is parsed here, once, before any pack sees it — so `..`, a drive
    letter or a lone dot is a message in the panel rather than a path handed to
    the code that deletes directories.
    """
    name = ProjectName.parse(str(values.get("name", "")))
    identity = ProjectIdentity.derive(
        name,
        title=str(values.get("title", "")),
        description=str(values.get("description", "")),
    )
    if target is ScaffoldTarget.CONTROLLER:
        folder = str(values.get(FOLDER_KEY, "")).strip() or "."
        destination = Path(folder)
    else:
        parent = str(values.get("parent", "")).strip() or "."
        destination = Path(parent).expanduser() / name.raw
    return ScaffoldContext(
        target=target, identity=identity, destination=destination, values=values
    )


@dataclass(frozen=True, slots=True)
class PackActionResult:
    available: bool
    message: str
    exit_code: int = 0


class TemplatePack(ABC):
    @property
    @abstractmethod
    def info(self) -> TemplatePackInfo:
        raise NotImplementedError

    def options(self, target: ScaffoldTarget) -> tuple[Option, ...]:
        """Flags this pack wants filled in before it scaffolds `target`.

        The default is what every pack needs. Override to add your own; the
        presentation renders whatever you return without knowing the stack.
        """
        if target is ScaffoldTarget.CONTROLLER:
            return generator_options(self.generators())
        return NEW_PROJECT_OPTIONS

    def generators(self) -> tuple[Generator, ...]:
        """The kinds of file this pack can add to an existing project."""
        return ()

    def template_source(self) -> TemplateSource | None:
        """Where this pack clones from, if it clones at all.

        Answered with the configured source rather than the shipped one, so
        Settings shows what would actually be used and repointing a stack does
        not mean editing the file by hand.
        """
        return None

    def preflight(self) -> tuple[ToolRequirement, ...]:
        """Executables this pack needs on the machine to do its work."""
        return ()

    @abstractmethod
    async def scaffold(self, context: ScaffoldContext) -> PackActionResult:
        raise NotImplementedError

    @abstractmethod
    async def build(self) -> PackActionResult:
        raise NotImplementedError
