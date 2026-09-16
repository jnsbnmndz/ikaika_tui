"""Running the work a script repository declares."""

import asyncio
import dataclasses
import os
import shlex
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from company_tui.domain import json_document, naming
from company_tui.domain.config import ConfigScope, TemplateSource
from company_tui.domain.identity import SCRIPT_MANIFEST, NotAProjectError
from company_tui.domain.interactive import ListView, Untimed
from company_tui.domain.json_document import MalformedJson
from company_tui.domain.options import OptionValue
from company_tui.domain.scaffolding import CannotStampIdentity, display_path
from company_tui.domain.script_config import (
    ERROR,
    EXISTS,
    FAILURE,
    INVALID_ARGS,
    INVALID_PATH,
    INVALID_TEMPLATE,
    ROOT,
    SUCCESS,
    ScriptAction,
    ScriptCatalogue,
    actions_from,
    after_clone_from,
    executable_of,
    executables_from,
    expand,
    split_command,
    unresolved,
)
from company_tui.domain.template_pack import PackActionResult, ToolRequirement
from company_tui.templates.services import (
    RAW,
    PackServices,
    describe_missing,
    missing_tools,
)

GIT_TOOL = ToolRequirement("git", "fetches the build scripts")

_SCP_FORM = "@"


def repository_folder(url: str) -> str:
    """`JDM-Github/react_native_scripts` out of a clone URL."""
    trimmed = url.strip().rstrip("/")
    trimmed = trimmed.removesuffix(".git")
    if _SCP_FORM in trimmed and "//" not in trimmed:
        trimmed = trimmed.split(":", 1)[-1]
    parts = [part for part in trimmed.replace("\\", "/").split("/") if part and part != "."]
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "scripts")


def repository_path(root: Path, source: TemplateSource) -> Path:
    return root / repository_folder(source.url)


async def catalogue_for(
    source: TemplateSource,
    services: PackServices,
    stack: str,
    *,
    compare: bool = False,
) -> ScriptCatalogue:
    """What this stack's scripts offer, fetching them the first time they are asked for."""
    root = repository_path(services.config.scripts_root(), source)
    problem = await _ensure(source, root, services, stack)
    if problem:
        return ScriptCatalogue(problem=problem, location=str(root))

    document, problem = _manifest_at(root, services)
    if document is None:
        return ScriptCatalogue(problem=problem, location=str(root), present=True)

    actions = actions_from(document)
    if not actions:
        return ScriptCatalogue(
            problem=f"{root / SCRIPT_MANIFEST} declares no config sections to run.",
            location=str(root),
            present=True,
        )
    return ScriptCatalogue(
        actions=actions,
        location=str(root),
        present=True,
        installed=str(document.get("version", "")),
        available=await _published_version(source, root, services) if compare else "",
        executables=executables_from(document),
    )


async def status_for(
    source: TemplateSource, services: PackServices, *, compare: bool = False
) -> ScriptCatalogue:
    """What the store holds for this stack, without fetching anything it lacks."""
    root = repository_path(services.config.scripts_root(), source)
    if not services.file_system.exists(root):
        return ScriptCatalogue(location=str(root))

    document, problem = _manifest_at(root, services)
    if document is None:
        return ScriptCatalogue(problem=problem, location=str(root), present=True)
    return ScriptCatalogue(
        actions=actions_from(document),
        location=str(root),
        present=True,
        installed=str(document.get("version", "")),
        available=await _published_version(source, root, services) if compare else "",
        executables=executables_from(document),
    )


async def install(
    source: TemplateSource, services: PackServices, stack: str, *, replace: bool = False
) -> str:
    """Put this stack's scripts in the store, or `""` and a reason if it could not."""
    root = repository_path(services.config.scripts_root(), source)
    if replace and services.file_system.exists(root):
        services.console.write(f"Replacing {root}...")
        await services.file_system.remove_tree(root)
    return await _ensure(source, root, services, stack)


def stop_watching(pack_key: str, services: PackServices) -> Path:
    """Write down that this stack's store is not to be compared again."""
    settings = services.config.settings()
    checks = dict(settings.script_checks)
    checks[pack_key] = False
    return services.config.save(
        dataclasses.replace(settings, script_checks=checks), _active_scope(services)
    )


def _active_scope(services: PackServices) -> ConfigScope:
    active = services.config.active_location()
    if active is not None and active == services.config.location(ConfigScope.PROJECT):
        return ConfigScope.PROJECT
    return ConfigScope.USER


async def run_action(
    action: ScriptAction,
    values: Mapping[str, OptionValue],
    repository: Path,
    services: PackServices,
) -> PackActionResult:
    """Do what one action says, in the project the form pointed at."""
    root = _absolute(Path(str(values.get(ROOT, ".")).strip() or ".").expanduser())
    references: dict[str, str] = {ROOT: str(root)}

    try:
        identity = services.finalizer.require_project(root)
    except (NotAProjectError, CannotStampIdentity) as error:
        return _refused(f"{error}")

    reason = action.reason_to_refuse(values)
    references.update(action.references_from(values))
    if reason:
        services.console.write(reason)
        return _refused(action.message(INVALID_ARGS, references, reason))

    if action.template and not action.path:
        return _refused(
            action.message(
                INVALID_PATH,
                references,
                f"{action.identifier} has a template but no path to put it in.",
            )
        )

    target: Path | None = None
    if action.path:
        directory = expand(action.path, references)
        if unresolved(directory) or not _inside(root, Path(directory)):
            return _refused(
                action.message(
                    INVALID_PATH,
                    {**references, ERROR: directory},
                    f"'{directory}' is not a path inside {display_path(root)}.",
                )
            )
        references[f"{action.reference}.path"] = directory

        filename = expand(action.filename, references)
        if unresolved(filename):
            return _refused(
                action.message(
                    INVALID_ARGS,
                    {**references, ERROR: filename},
                    f"{action.identifier} names {', '.join(unresolved(filename))}, "
                    "which it does not declare as an argument.",
                )
            )
        references[f"{action.reference}.filename"] = filename
        if filename:
            target = Path(directory) / filename

    missing = missing_tools(
        services.process_runner,
        tuple(
            ToolRequirement(name, f"{action.name} runs it")
            for name in action.executables
        ),
    )
    if missing:
        return _refused(
            action.message(
                FAILURE,
                {**references, ERROR: describe_missing(missing)},
                f"{describe_missing(missing)} and try again.",
            )
        )

    services.console.write(f"Running {action.name} in '{identity.title}'.")

    staged: _Staged | None = None
    if action.writes_a_file and target is not None:
        staged, outcome = _stage(
            action,
            target,
            references,
            repository,
            services,
            overwrite=action.overwrites(values),
        )
        if outcome is not None:
            return outcome
    elif not action.after_success:
        return _refused(f"{action.identifier} declares neither a template nor a command.")

    try:
        failure = await _run_commands(action, references, repository, services)
    except asyncio.CancelledError:
        if staged is not None:
            _unstage(staged, services)
        raise

    if failure is not None:
        if staged is not None:
            _unstage(staged, services)
            services.console.write(_undone(staged))
        return PackActionResult(
            available=True,
            message=action.message(
                FAILURE, {**references, ERROR: failure[0]}, failure[0]
            ),
            exit_code=failure[1],
        )

    return PackActionResult(
        available=True,
        message=action.message(
            SUCCESS,
            references,
            f"{action.name} finished in {display_path(root)}.",
        ),
    )


async def _ensure(
    source: TemplateSource, root: Path, services: PackServices, stack: str
) -> str:
    if services.file_system.exists(root):
        return ""
    if missing_tools(services.process_runner, (GIT_TOOL,)):
        return f"Install git ({GIT_TOOL.purpose}) and try again."

    services.console.write(f"Fetching the {stack} scripts from {source.described}...")
    services.console.write(f"{RAW}into {root}")
    try:
        result = await services.process_runner.stream(
            _clone_command(source, root),
            lambda line: services.console.write(f"{RAW}{line}"),
        )
        if result.exit_code != 0:
            await _discard(root, services)
            return f"Could not fetch {source.described}."

        problem = await _set_up(root, services, stack)
        if problem:
            await _discard(root, services)
            return problem
    except asyncio.CancelledError:
        await _discard(root, services, shielded=True)
        raise

    services.console.write(f"Fetched the {stack} scripts into {root}.")
    return ""


async def _discard(root: Path, services: PackServices, *, shielded: bool = False) -> None:
    """Take a store back off the disk, even while being cancelled."""
    if not services.file_system.exists(root):
        return
    removal = services.file_system.remove_tree(root)
    if not shielded:
        await removal
        return
    with suppress(asyncio.CancelledError):
        await asyncio.shield(asyncio.ensure_future(removal))


async def _set_up(root: Path, services: PackServices, stack: str) -> str:
    """Run what the freshly cloned repository says it needs, or say what failed."""
    document, _ = _manifest_at(root, services)
    if document is None:
        return ""

    commands = after_clone_from(document)
    if not commands:
        return ""

    missing = missing_tools(
        services.process_runner,
        tuple(
            ToolRequirement(name, f"the {stack} scripts set themselves up with it")
            for name in _distinct(executable_of(command) for command in commands)
        ),
    )
    if missing:
        return f"{describe_missing(missing)} and try again."

    services.console.write(f"Setting up the {stack} scripts...")
    for raw in commands:
        command = _command_from(raw, {})
        if not command:
            continue
        if any(unresolved(argument) for argument in command):
            return f"{SCRIPT_MANIFEST} asks for '{raw}', which nothing here can fill in."

        services.console.write(f"{RAW}$ {shlex.join(command)}")
        tail: deque[str] = deque(maxlen=SETUP_TAIL)
        result = await services.process_runner.stream(command, tail.append, root)
        if result.exit_code == 0:
            continue
        for line in (line for line in tail if line.strip()):
            services.console.write(f"{RAW}{line}")
        return (
            f"Setting up the {stack} scripts failed: "
            f"{command[0]} exited {result.exit_code}."
        )
    return ""


SETUP_TAIL = 12
"""How much of a failed setup command is worth reading in the header's margin."""

def _clone_command(source: TemplateSource, root: Path) -> tuple[str, ...]:
    """A whole clone, not a shallow one, and pinned when a ref says so."""
    branch = ("--branch", source.ref) if source.ref else ()
    return ("git", "clone", *branch, source.url, str(root))


def _manifest_at(
    root: Path, services: PackServices
) -> tuple[dict | None, str]:
    manifest = naming.manifest_path(root)
    if not services.file_system.exists(manifest):
        return None, (
            f"No {SCRIPT_MANIFEST} in {root} — a script repository is one that "
            "carries the same manifest every project of this kind does."
        )
    try:
        return json_document.load(services.file_system.read_text(manifest)), ""
    except (MalformedJson, OSError) as error:
        return None, f"{manifest}: {error}"


async def _published_version(
    source: TemplateSource, root: Path, services: PackServices
) -> str:
    """What the repository this came from says its manifest is now, or `""`."""
    if missing_tools(services.process_runner, (GIT_TOOL,)):
        return ""
    fetched = await services.process_runner.capture(
        ("git", "-C", str(root), "fetch", "--quiet", "origin", source.ref or "HEAD")
    )
    if fetched.exit_code != 0:
        return ""
    shown = await services.process_runner.capture(
        ("git", "-C", str(root), "show", f"FETCH_HEAD:{SCRIPT_MANIFEST}")
    )
    if shown.exit_code != 0:
        return ""
    try:
        return str(json_document.load(shown.stdout).get("version", ""))
    except MalformedJson:
        return ""


@dataclasses.dataclass(frozen=True, slots=True)
class _Staged:
    """One template written where the config said, and what it was written over."""

    path: Path
    replaced: str | None = None


def _stage(
    action: ScriptAction,
    target: Path,
    references: Mapping[str, str],
    repository: Path,
    services: PackServices,
    *,
    overwrite: bool,
) -> tuple[_Staged | None, PackActionResult | None]:
    """Copy the template where the config said, or say why that cannot happen."""
    replaced: str | None = None
    if services.file_system.exists(target):
        if not overwrite:
            return None, _refused(
                action.message(
                    EXISTS, references, f"{display_path(target)} already exists."
                )
            )
        try:
            replaced = services.file_system.read_text(target)
        except OSError as error:
            return None, _refused(
                action.message(
                    FAILURE, {**references, ERROR: str(error)}, f"{target}: {error}"
                )
            )

    template = _template_path(action, references, repository)
    if not services.file_system.exists(template):
        return None, _refused(
            action.message(
                INVALID_TEMPLATE,
                {**references, ERROR: str(template)},
                f"No template at {template}.",
            )
        )

    try:
        services.file_system.write_text(target, services.file_system.read_text(template))
    except OSError as error:
        return None, _refused(
            action.message(
                FAILURE, {**references, ERROR: str(error)}, f"{target}: {error}"
            )
        )
    written = display_path(target)
    services.console.write(
        f"{RAW}{written} (replaced)" if replaced is not None else f"{RAW}{written}"
    )
    return _Staged(target, replaced), None


def _unstage(staged: _Staged, services: PackServices) -> None:
    if staged.replaced is None:
        services.file_system.remove_file(staged.path)
        return
    services.file_system.write_text(staged.path, staged.replaced)


def _undone(staged: _Staged) -> str:
    if staged.replaced is None:
        return f"Removed the staged {display_path(staged.path)}."
    return f"Put back the {display_path(staged.path)} this run was replacing."


def _template_path(
    action: ScriptAction, references: Mapping[str, str], repository: Path
) -> Path:
    """Where the template actually is, which depends on whose root it was written against."""
    resolved = expand(action.template, references)
    if f"${{{ROOT}}}" in action.template or Path(resolved).is_absolute():
        return Path(resolved)
    return repository / resolved


def _list_view(action: ScriptAction, services: PackServices) -> "ListView | None":
    """A view only when BOTH halves said yes, and `None` every other time.

    The setting alone is not enough and neither is the declaration: one is the
    person saying the experiment may run at all, the other is the command saying it
    knows how to speak. `None` is what leaves the run byte for byte as it was - no
    stdin pipe, no variable in the environment, nothing to parse.

    The countdown is a second setting over the top of it, and off it takes the
    `timeout` out of every listing rather than passing a flag along beside one.
    """
    if not action.interactive:
        return None
    if not services.config.interactive_lists():
        return None
    view = services.console.list_view()
    if view is None or services.config.timed_prompts():
        return view
    return Untimed(view)


async def _run_commands(
    action: ScriptAction,
    references: Mapping[str, str],
    repository: Path,
    services: PackServices,
) -> tuple[str, int] | None:
    view = _list_view(action, services)
    for raw in action.after_success:
        command = _command_from(raw, references)
        if not command:
            continue
        services.console.write(f"{RAW}$ {shlex.join(command)}")
        result = await services.process_runner.stream(
            command,
            lambda line: services.console.write(f"{RAW}{line}"),
            repository,
            view,
        )
        if result.exit_code != 0:
            return (f"{command[0]} exited {result.exit_code}", result.exit_code)
    return None


def _command_from(raw: str, references: Mapping[str, str]) -> tuple[str, ...]:
    """One declared command as an argument array, filled in and ready to run."""
    return tuple(expand(token, references) for token in split_command(raw))


def _distinct(names) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for name in names if name))


def _refused(message: str) -> PackActionResult:
    return PackActionResult(available=True, message=message, exit_code=1)


def _absolute(path: Path) -> Path:
    """`path` made absolute without asking the disk about it."""
    return Path(os.path.abspath(path))


def _inside(root: Path, target: Path) -> bool:
    base = _absolute(root)
    full = _absolute(target)
    return full == base or base in full.parents


__all__ = [
    "GIT_TOOL",
    "catalogue_for",
    "repository_folder",
    "repository_path",
    "run_action",
]
