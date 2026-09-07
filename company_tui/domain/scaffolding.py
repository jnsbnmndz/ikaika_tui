"""The part of scaffolding that does not vary by stack.

A pack decides how a tree appears — cloned from a structure repository, or
written file by file. What happens to it next is the same either way: it is
stamped with its own identity instead of the template's, it stops being a copy
of someone else's repository and starts being its own, and the examples the
template left behind become the real thing.

Packs hand that to a finalizer rather than each getting it slightly wrong. It
reaches the disk through ports, so this stays testable without one.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.config import TemplateSource
from company_tui.domain.identity import (
    SCRIPT_MANIFEST,
    MalformedScriptManifest,
    NotAnIkaikaProject,
    ProjectIdentity,
    apply_identity,
    read_identity,
)
from company_tui.domain.json_document import MalformedJson, dump
from company_tui.domain.ports import FileSystemPort, ProcessRunner

GIT = "git"
GIT_DIRECTORY = ".git"
ENVIRONMENT_EXAMPLE = ".env.example"
ENVIRONMENT = ".env"
TEMPLATE_RECORD = Path(naming.STORE_DIR_NAME) / "template.json"

FIRST_COMMIT = "Initial commit"


class CannotStampIdentity(Exception):
    """The project carries the files, but they are not shaped the way they must be."""


def display_path(path: Path) -> str:
    """A path the way the user would have typed it.

    Kept in one place because `./` in front of an absolute path is nonsense, and
    a destination is named in nearly every line a scaffold reports.
    """
    if path == Path("."):
        return "the current directory"
    return path.as_posix() if path.is_absolute() else f"./{path.as_posix()}"


@dataclass(frozen=True, slots=True)
class IdentityRewrite:
    """A stack-specific file that also spells out who the project is.

    `ikaika.script.json` is the contract every project shares; this is for the
    rest — an Expo `app.json`, a `pubspec.yaml` — which belong to one stack and
    so are declared by that stack rather than assumed here.
    """

    relative_path: str
    rewrite: Callable[[str, ProjectIdentity], str]
    required: bool = False


@dataclass(frozen=True, slots=True)
class FinalizeReport:
    stamped: tuple[str, ...]
    seeded: tuple[str, ...]
    repository: str

    @property
    def summary(self) -> str:
        return f"stamped {', '.join(self.stamped)}"


class ProjectFinalizer:
    def __init__(
        self,
        file_system: FileSystemPort,
        process_runner: ProcessRunner,
        report: Callable[[str], None],
    ) -> None:
        self._file_system = file_system
        self._process_runner = process_runner
        self._report = report

    def require_project(self, root: Path) -> ProjectIdentity:
        """Confirm `root` is an IKAIKA project, and say which one.

        Both halves of scaffolding lean on this: a clone that arrives without a
        manifest is not a template this toolbox produced, and a generator asked
        to add a file to the current directory has no business writing into a
        tree it cannot identify.
        """
        manifest = naming.manifest_path(root)
        if not self._file_system.exists(manifest):
            raise NotAnIkaikaProject(
                f"No {SCRIPT_MANIFEST} in {display_path(root)} — "
                "every IKAIKA project has one."
            )
        try:
            return read_identity(self._file_system.read_text(manifest))
        except (MalformedJson, MalformedScriptManifest) as error:
            raise CannotStampIdentity(str(error)) from error

    async def finalize(
        self,
        root: Path,
        identity: ProjectIdentity,
        *,
        rewrites: Sequence[IdentityRewrite] = (),
        adopt_repository: bool = True,
    ) -> FinalizeReport:
        stamped = self._stamp(root, identity, rewrites)
        seeded = self._seed_environment(root)
        repository = (
            await self._adopt_repository(root, identity)
            if adopt_repository
            else "left alone"
        )
        return FinalizeReport(stamped=stamped, seeded=seeded, repository=repository)

    def record_template(
        self, root: Path, source: TemplateSource, commit: str, stack: str
    ) -> None:
        """Write down which template this came from, and exactly which revision.

        Cloning the default branch means "whatever it looked like today", and a
        project that cannot answer which revision it started from cannot be told
        what it is now missing.
        """
        self._file_system.write_text(
            root / TEMPLATE_RECORD,
            dump(
                {
                    "stack": stack,
                    "url": source.url,
                    "ref": source.ref or "(default branch)",
                    "commit": commit or "(unknown)",
                }
            ),
        )

    def _stamp(
        self,
        root: Path,
        identity: ProjectIdentity,
        rewrites: Sequence[IdentityRewrite],
    ) -> tuple[str, ...]:
        self.require_project(root)
        # Stamped where it already is: renaming the file while rewriting what is
        # inside it would leave the old one holding a stale copy of the same keys.
        existing = naming.manifest_path(root)
        stamped = [existing.name]
        self._rewrite(existing, apply_identity, identity)

        for entry in rewrites:
            target = root / entry.relative_path
            if not self._file_system.exists(target):
                if entry.required:
                    raise CannotStampIdentity(
                        f"{entry.relative_path} is missing, and this stack needs it "
                        "to name the project."
                    )
                continue
            self._rewrite(target, entry.rewrite, identity)
            stamped.append(entry.relative_path)

        self._report(f"Stamped {', '.join(stamped)} as '{identity.name}'.")
        return tuple(stamped)

    def _rewrite(
        self,
        path: Path,
        rewrite: Callable[[str, ProjectIdentity], str],
        identity: ProjectIdentity,
    ) -> None:
        source = self._file_system.read_text(path)
        try:
            self._file_system.write_text(path, rewrite(source, identity))
        except (MalformedJson, MalformedScriptManifest) as error:
            raise CannotStampIdentity(f"{path.name}: {error}") from error

    def _seed_environment(self, root: Path) -> tuple[str, ...]:
        example = root / ENVIRONMENT_EXAMPLE
        target = root / ENVIRONMENT
        if not self._file_system.exists(example) or self._file_system.exists(target):
            return ()
        self._file_system.write_text(target, self._file_system.read_text(example))
        self._report(f"Copied {ENVIRONMENT_EXAMPLE} to {ENVIRONMENT}.")
        return (ENVIRONMENT,)

    async def _adopt_repository(self, root: Path, identity: ProjectIdentity) -> str:
        """Drop the template's history and start one belonging to this project.

        Best effort on purpose. A machine with no `git`, or one that has never
        been told who its user is, still gets a complete project — it just gets
        it without the first commit, and is told so.
        """
        history = root / GIT_DIRECTORY
        if self._file_system.exists(history):
            self._report("Removing template Git history...")
            await self._file_system.remove_tree(history)

        if self._process_runner.locate(GIT) is None:
            return "no repository (git is not installed)"

        self._report("Starting a repository for this project...")
        for command in (
            (GIT, "-C", str(root), "init", "--quiet"),
            (GIT, "-C", str(root), "add", "-A"),
            (
                GIT,
                "-C",
                str(root),
                "commit",
                "--quiet",
                "-m",
                f"{FIRST_COMMIT}: {identity.title}",
            ),
        ):
            result = await self._process_runner.stream(command, lambda _line: None)
            if result.exit_code != 0:
                self._report(f"Skipped the first commit ({command[3]} failed).")
                return f"repository started, but '{command[3]}' failed"
        return "repository started with a first commit"
