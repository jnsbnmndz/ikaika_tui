"""Running the work a script repository declares.

A stack's scripts are a repository of their own — templates, the program that
finishes them, and the `ikaika.script.json` that says how the two go together.
It is cloned once into the toolbox's own store and shared by every project on
this machine, so the copy the user edits is the copy every project runs.

Fetched rather than kept in step: a repository that is already there is left
exactly as it is, never pulled and never checked out over. Somebody who went and
edited a template in that directory did so because that is the point of keeping
one copy, and a toolbox that quietly reset it would be taking that back. Which
revision arrives is settled at the clone, from the ref in `ikaika.toml`.

`domain/script_config.py` is what reads the document; this is what has a disk.
The split matters more than it looks: the rules a config declares are worth
testing against a dozen malformed documents, and none of those need a clone.
"""

import asyncio
import dataclasses
import os
import shlex
from collections.abc import Mapping
from pathlib import Path

from company_tui.domain import json_document
from company_tui.domain.config import ConfigScope, TemplateSource
from company_tui.domain.identity import SCRIPT_MANIFEST, NotAnIkaikaProject
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
    expand,
    unresolved,
)
from company_tui.domain.template_pack import PackActionResult, ToolRequirement
from company_tui.templates.services import RAW, PackServices, missing_tools

GIT_TOOL = ToolRequirement("git", "fetches the build scripts")

_SCP_FORM = "@"


def repository_folder(url: str) -> str:
    """`JDM-Github/react_native_scripts` out of a clone URL.

    Owner and repository rather than just the repository, because two
    organisations forking the same name is not a reason for one clone to land on
    top of the other, and because a directory named for its origin is one
    somebody can find without asking the toolbox where it put things.
    """
    trimmed = url.strip().rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[: -len(".git")]
    if _SCP_FORM in trimmed and "//" not in trimmed:
        # git@github.com:owner/repo — the host is before the colon, not a path.
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
    """What this stack's scripts offer, fetching them the first time they are asked for.

    Every way of having nothing to offer comes back as a `problem` rather than
    an exception, because the caller is a menu: what it does with "git is not
    installed" and with "that repository has no manifest" is the same thing —
    say so on the menu the user is standing on, and let them choose again.

    `compare` also asks the remote what version it publishes, which costs a
    fetch. Off by default and answered by settings at the call site, because a
    store nobody has said anything about is worth watching and one somebody
    chose to stop being asked about is not worth a network round trip.
    """
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
    )


async def status_for(
    source: TemplateSource, services: PackServices, *, compare: bool = False
) -> ScriptCatalogue:
    """What the store holds for this stack, without fetching anything it lacks.

    The reading Settings shows: a form has to be on screen before the user can
    ask for anything, so building it must never be the thing that clones a
    repository. A stack with nothing in the store says so and offers to install.
    """
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
    )


async def install(
    source: TemplateSource, services: PackServices, stack: str, *, replace: bool = False
) -> str:
    """Put this stack's scripts in the store, or `""` and a reason if it could not.

    `replace` is the one thing that overwrites the copy in the store, and it is
    only ever reached by somebody asking for it — from the prompt when a store
    has fallen behind, or from Settings. Everything else leaves what is there.
    """
    root = repository_path(services.config.scripts_root(), source)
    if replace and services.file_system.exists(root):
        services.console.write(f"Replacing {root}...")
        await services.file_system.remove_tree(root)
    return await _ensure(source, root, services, stack)


def stop_watching(pack_key: str, services: PackServices) -> Path:
    """Write down that this stack's store is not to be compared again.

    Into whichever file is being read, not always the user's. Settings are one
    file winning outright rather than two merged, so a preference written to the
    user's copy while a project one exists is a preference nothing will ever
    read — an answer to a question that then keeps being asked. Which file it
    landed in is said out loud for the same reason.
    """
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
    """Do what one action says, in the project the form pointed at.

    The order is the order the config is written in: check the answers, work out
    where the file goes, refuse if something is already there and the form did
    not ask to replace it, stage the template, then hand over to whatever the
    config wanted run afterwards. Every refusal quotes the message the
    repository wrote for it, because those messages are the repository's own
    voice and this toolbox is only carrying them.
    """
    root = _absolute(Path(str(values.get(ROOT, ".")).strip() or ".").expanduser())
    references: dict[str, str] = {ROOT: str(root)}

    try:
        identity = services.finalizer.require_project(root)
    except (NotAnIkaikaProject, CannotStampIdentity) as error:
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
            # The config asked for a flag it never declared. Left alone this
            # writes a file literally called `${screen.args.nmae}.screen.tsx`.
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
        # A stopped run leaves nothing half-written: the staged file is still
        # the raw template, and a raw template sitting where a finished one
        # belongs is worse than the file not being there at all.
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


# ----------------------------------------------------------------- fetching


async def _ensure(
    source: TemplateSource, root: Path, services: PackServices, stack: str
) -> str:
    if services.file_system.exists(root):
        return ""
    if missing_tools(services.process_runner, (GIT_TOOL,)):
        return f"Install git ({GIT_TOOL.purpose}) and try again."

    services.console.write(f"Fetching the {stack} scripts from {source.described}...")
    services.console.write(f"{RAW}into {root}")
    result = await services.process_runner.stream(
        _clone_command(source, root),
        lambda line: services.console.write(f"{RAW}{line}"),
    )
    if result.exit_code != 0:
        # Half a clone is a directory that would pass for a good one next time,
        # and the run after this would fail somewhere far less obvious.
        if services.file_system.exists(root):
            await services.file_system.remove_tree(root)
        return f"Could not fetch {source.described}."
    services.console.write(f"Fetched the {stack} scripts into {root}.")
    return ""


def _clone_command(source: TemplateSource, root: Path) -> tuple[str, ...]:
    """A whole clone, not a shallow one, and pinned when a ref says so.

    Depth is what a template clone wants, because that history is thrown away an
    instant later. This one is kept and worked in, so it arrives with something
    to commit against — and with a remote to ask what it has published since.
    """
    branch = ("--branch", source.ref) if source.ref else ()
    return ("git", "clone", *branch, source.url, str(root))


def _manifest_at(
    root: Path, services: PackServices
) -> tuple[dict | None, str]:
    manifest = root / SCRIPT_MANIFEST
    if not services.file_system.exists(manifest):
        return None, (
            f"No {SCRIPT_MANIFEST} in {root} — a script repository is one that "
            "carries the same manifest every IKAIKA project does."
        )
    try:
        return json_document.load(services.file_system.read_text(manifest)), ""
    except (MalformedJson, OSError) as error:
        return None, f"{manifest}: {error}"


async def _published_version(
    source: TemplateSource, root: Path, services: PackServices
) -> str:
    """What the repository this came from says its manifest is now, or `""`.

    Read out of the fetched objects rather than out of the working tree, which
    is the whole point: the copy in the store is the one the user edits, and
    nothing here may touch it to answer a question about the remote. Every
    failure is silence — offline, unreachable, no such ref — because a version
    check is a courtesy and a courtesy that reports its own plumbing is noise.
    """
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


# ------------------------------------------------------------------ running


@dataclasses.dataclass(frozen=True, slots=True)
class _Staged:
    """One template written where the config said, and what it was written over.

    `replaced` is the file that was there — `None` when there was none — because
    undoing a staging and undoing a replacement are not the same act. Deleting
    what a failed run wrote back is right for a file this run invented and
    wrong for one somebody had been editing since March.
    """

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
            # Refused rather than written over: a file that cannot be read
            # cannot be put back, and this run is one failed command away from
            # owing it.
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
        # The directories above it are made on the way: a config naming a folder
        # this project has not needed yet is describing where the file goes, not
        # asserting that somebody already made room for it.
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
    """Where the template actually is, which depends on whose root it was written against.

    `${root}/templates/x` is the project's own copy; a bare `templates/x` is the
    script repository's. That is the whole convention, and it is what lets one
    repository serve every project on the stack without each of them carrying
    the templates it is scaffolded from.
    """
    resolved = expand(action.template, references)
    if f"${{{ROOT}}}" in action.template or Path(resolved).is_absolute():
        return Path(resolved)
    return repository / resolved


async def _run_commands(
    action: ScriptAction,
    references: Mapping[str, str],
    repository: Path,
    services: PackServices,
) -> tuple[str, int] | None:
    for raw in action.after_success:
        command = _command_from(raw, references)
        if not command:
            continue
        services.console.write(f"{RAW}$ {shlex.join(command)}")
        # Run from the repository the config came from, which is what makes a
        # bare `scripts/finalize.mjs` mean the copy beside that config. Every
        # `${root}` was expanded to an absolute path for the same reason: a
        # relative one would be read from here instead of from the project.
        result = await services.process_runner.stream(
            command,
            lambda line: services.console.write(f"{RAW}{line}"),
            repository,
        )
        if result.exit_code != 0:
            return (f"{command[0]} exited {result.exit_code}", result.exit_code)
    return None


def _command_from(raw: str, references: Mapping[str, str]) -> tuple[str, ...]:
    """One declared command as an argument array, with no shell involved.

    Split before the references are filled in, never after. A Windows path
    substituted first arrives full of backslashes, and every one of them is an
    escape to the splitter — `C:\\src` comes back out as `C:src`, which is a
    path to somewhere that does not exist and, occasionally, to somewhere that
    does.
    """
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError:
        return ()
    return tuple(expand(token, references) for token in tokens)


# ------------------------------------------------------------------ helpers


def _refused(message: str) -> PackActionResult:
    return PackActionResult(available=True, message=message, exit_code=1)


def _absolute(path: Path) -> Path:
    """`path` made absolute without asking the disk about it.

    `resolve` would follow links and, on a path that does not exist yet, differs
    between platforms. Nothing here needs the real inode — only a root that
    still means the same directory once a command is run from somewhere else.
    """
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
