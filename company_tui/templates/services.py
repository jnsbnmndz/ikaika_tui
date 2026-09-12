"""What every pack is handed, and the few steps every pack does the same way.

A pack's own module should read as the stack it is for. Checking that a tool
exists, showing someone what a delete is about to take, and previewing a set of
files before writing them are not that — they are the same in every stack, so
they live here and a pack calls them.
"""

import re
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from company_tui.domain.config import ConfigPort
from company_tui.domain.identity import NotAProjectError
from company_tui.domain.ports import FileSystemPort, ProcessRunner
from company_tui.domain.project_name import ProjectName
from company_tui.domain.scaffolding import (
    CannotStampIdentity,
    ProjectFinalizer,
    display_path,
)
from company_tui.domain.template_pack import (
    GENERATOR_KEY,
    Generator,
    PackActionResult,
    ScaffoldContext,
    ToolRequirement,
)
from company_tui.presentation.ui import Ui

Renderer = Callable[[ProjectName], Mapping[str, str]]
"""Turns a name into the files one generator produces, keyed by relative path."""

RAW = "  "
"""Prefix that marks a line as verbatim subprocess output."""

PREVIEW_LIMIT = 12
"""How many names a preview lists before it starts counting instead."""

PACKAGE_TOKEN = "{package}"
"""Stands in, in a generator's default folder, for the project's own package name."""

QUIET_TAIL = 20
"""How many lines of a held-back command a failure gets to show."""

QUIET_HEARTBEAT = 15.0
"""Seconds of nothing worth saying before saying so anyway."""

_TROUBLE = re.compile(r"npm ERR!|\bfatal:|\berror:|\bERROR\b", re.IGNORECASE)


class QuietRun:
    """Watches a noisy command without repeating it.

    `npm install` is several thousand lines nobody reads and one line that
    matters. Streaming all of it buries the run's own narration; streaming none
    of it makes a three-minute install look like a hang. So: trouble is shown as
    it happens, a long silence is broken by saying the run is still alive, and
    the end of the output is kept back so a failure has something to show.
    """

    def __init__(
        self,
        report: Callable[[str], None],
        *,
        tail: int = QUIET_TAIL,
        heartbeat: float = QUIET_HEARTBEAT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._report = report
        self._kept: deque[str] = deque(maxlen=tail)
        self._heartbeat = heartbeat
        self._clock = clock
        self._started = clock()
        self._spoke_at = self._started
        self._lines = 0

    def __call__(self, line: str) -> None:
        self._lines += 1
        self._kept.append(line)
        if _TROUBLE.search(line):
            self._report(f"{RAW}{line}")
            self._spoke_at = self._clock()
            return
        if self._clock() - self._spoke_at >= self._heartbeat:
            self._spoke_at = self._clock()
            self._report(f"{RAW}still working — {self._lines} lines in, {self.elapsed}s")

    @property
    def elapsed(self) -> int:
        return int(self._clock() - self._started)

    def explain_failure(self) -> None:
        """Show the end of what was held back — the reason is almost always there."""
        if not self._kept:
            self._report("It failed without saying anything.")
            return
        self._report(f"Last {len(self._kept)} lines before it failed:")
        for line in self._kept:
            self._report(f"{RAW}{line}")


@dataclass(frozen=True, slots=True)
class PackServices:
    console: Ui
    file_system: FileSystemPort
    process_runner: ProcessRunner
    config: ConfigPort
    finalizer: ProjectFinalizer


def missing_tools(
    process_runner: ProcessRunner, requirements: Sequence[ToolRequirement]
) -> tuple[ToolRequirement, ...]:
    return tuple(
        requirement
        for requirement in requirements
        if process_runner.locate(requirement.executable) is None
    )


def describe_missing(missing: Sequence[ToolRequirement]) -> str:
    return "Install " + ", ".join(
        f"{requirement.executable} ({requirement.purpose})" for requirement in missing
    )


async def clear_destination(root: Path, services: PackServices) -> bool:
    """Make `root` safe to scaffold into, or report that the user said no.

    An occupied destination is listed before it is offered up for deletion. A
    yes/no with nothing behind it is not a confirmation — the person answering
    has to be able to see what the answer costs.
    """
    if not services.file_system.exists(root):
        return True

    entries = services.file_system.entries(root)
    services.console.write(
        f"{display_path(root)} already exists and holds {len(entries)} entries:"
    )
    for name in entries[:PREVIEW_LIMIT]:
        services.console.write(f"{RAW}{name}")
    if len(entries) > PREVIEW_LIMIT:
        services.console.write(f"{RAW}... and {len(entries) - PREVIEW_LIMIT} more")
    services.console.write("Replacing it deletes all of that, and cannot be undone.")

    if not await services.console.confirm(
        f"Delete {display_path(root)} and scaffold over it?"
    ):
        return False

    services.console.write(f"Replacing {display_path(root)}...")
    await services.file_system.remove_tree(root)
    return True


def preview_files(root: Path, files: Mapping[str, str], services: PackServices) -> None:
    services.console.write(f"Will create {display_path(root)}/ with {len(files)} files:")
    for relative_path in sorted(files)[:PREVIEW_LIMIT]:
        services.console.write(f"{RAW}{relative_path}")
    if len(files) > PREVIEW_LIMIT:
        services.console.write(f"{RAW}... and {len(files) - PREVIEW_LIMIT} more")


async def run_generator(
    context: ScaffoldContext,
    services: PackServices,
    generators: Sequence[Generator],
    renderers: Mapping[str, Renderer],
    stack_name: str,
) -> PackActionResult:
    """Add files to the project the user is standing in.

    Where a new project starts from an empty destination, this one starts from
    someone else's work, so it refuses twice before writing: once if the current
    directory is not an IKAIKA project at all, and again if the files it would
    write are already there.
    """
    root = Path(".")
    try:
        identity = services.finalizer.require_project(root)
    except (NotAProjectError, CannotStampIdentity) as error:
        return PackActionResult(
            available=True,
            message=f"{error} Run this from the root of the project you are adding to.",
            exit_code=1,
        )

    key = str(context.flag(GENERATOR_KEY, generators[0].key if generators else ""))
    renderer = renderers.get(key)
    if renderer is None:
        return PackActionResult(
            available=False,
            message=f"{stack_name} has no '{key}' generator.",
            exit_code=1,
        )

    services.console.write(f"Adding to '{identity.title}' ({identity.name}).")
    # A stack whose folders are named after the project cannot put a useful
    # default in a form built before the project is known, so it writes
    # `{package}` and the answer is substituted once the manifest has been read.
    folder = Path(str(context.destination).replace(PACKAGE_TOKEN, identity.name.snake))
    files = {
        str(folder / relative_path): content
        for relative_path, content in renderer(context.identity.name).items()
    }

    existing = tuple(
        path for path in sorted(files) if services.file_system.exists(Path(path))
    )
    for path in sorted(files):
        services.console.write(f"{RAW}{path}{'  (overwrites)' if path in existing else ''}")
    if existing and not await services.console.confirm(
        f"{len(existing)} of these already exist. Overwrite them?"
    ):
        return PackActionResult(
            available=True, message="Cancelled — nothing was changed.", exit_code=1
        )
    if not await services.console.confirm(
        f"Add {len(files)} files to {display_path(folder)}/?"
    ):
        return PackActionResult(
            available=True, message="Cancelled — nothing was changed.", exit_code=1
        )

    for path, content in files.items():
        services.file_system.write_text(Path(path), content)
    return PackActionResult(
        available=True,
        message=f"Added {len(files)} {stack_name} {key} files to {display_path(folder)}/.",
    )
