"""React Native projects, cloned from the IKAIKA structure repository.

Cloning is the easy half. A clone is a copy of somebody else's project until it
is told who it is, so the sequence here is: check the tools exist, clear the
destination with the user watching, clone, write down which revision arrived,
then stamp the identity across `ikaika.script.json` and Expo's `app.json` and
start a repository of its own. Stopping at any point takes the directory with
it, because a half-adopted clone is worse than no directory at all.
"""

import asyncio
from collections.abc import Mapping
from pathlib import Path

from company_tui.domain.config import TemplateSource
from company_tui.domain.identity import NotAProjectError
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.project_name import ProjectName
from company_tui.domain.scaffolding import (
    CannotStampIdentity,
    IdentityRewrite,
    display_path,
)
from company_tui.domain.script_config import ScriptAction, ScriptCatalogue, ScriptUpdate
from company_tui.domain.template_pack import (
    Generator,
    PackActionResult,
    ScaffoldContext,
    ToolRequirement,
    project_options,
)
from company_tui.templates import scripts
from company_tui.templates.react_native import expo
from company_tui.templates.services import (
    RAW,
    PackServices,
    QuietRun,
    Renderer,
    clear_destination,
    describe_missing,
    missing_tools,
    run_generator,
)

STACK_NAME = "React Native"
PACK_KEY = "react_native"

TEMPLATE = TemplateSource(
    url="https://github.com/JDM-Github/react_native_structure.git"
)

SCRIPTS = TemplateSource(
    url="https://github.com/JDM-Github/react_native_scripts.git"
)
"""The repository the build workflows come from.

Cloned once into the shared store rather than into each project, which is what
makes editing a template there mean editing it for every React Native project on
the machine. Its `ikaika.script.json` is what decides which workflows exist; this
file names the repository and nothing else about it.
"""

GIT_TOOL = ToolRequirement("git", f"clones the {STACK_NAME} template")
NPM_TOOL = ToolRequirement("npm", "installs project dependencies", required=False)
NODE_TOOL = ToolRequirement("node", "runs the build scripts", required=False)
REQUIRED_TOOLS = (GIT_TOOL,)
DECLARED_TOOLS = (GIT_TOOL, NPM_TOOL, NODE_TOOL)

INSTALL_OPTION = Option(
    key="install",
    label="Install dependencies after cloning",
    kind=OptionKind.BOOLEAN,
    default=False,
    help="Runs npm install in the new project. Slow, and needs npm on PATH.",
)

HISTORY_OPTION = Option(
    key="history",
    label="Template history",
    kind=OptionKind.INFO,
    default="Replaced by a first commit of your own",
)


def new_project_options(source: TemplateSource, parent: str = ".") -> tuple[Option, ...]:
    """The form for a new project, showing the template it will actually use.

    The source is a row rather than a constant in this file because it can be
    repointed or pinned in the settings file, and a form that still advertised the
    default would be quietly lying about what is about to be cloned.
    """
    return (
        *project_options(parent),
        INSTALL_OPTION,
        Option(
            key="source",
            label="Source",
            kind=OptionKind.INFO,
            default=source.described,
        ),
        HISTORY_OPTION,
    )


async def scaffold_new_project(
    context: ScaffoldContext, services: PackServices
) -> PackActionResult:
    source = services.config.template_source(PACK_KEY, TEMPLATE)
    wanted = REQUIRED_TOOLS + ((NPM_TOOL,) if context.flag("install", False) else ())
    missing = missing_tools(services.process_runner, wanted)
    if missing:
        return PackActionResult(
            available=False,
            message=f"{describe_missing(missing)} and try again.",
            exit_code=1,
        )

    root = context.destination
    services.console.write("Checking destination...")
    if not await clear_destination(root, services):
        return PackActionResult(
            available=True, message="Cancelled — nothing was changed.", exit_code=1
        )

    services.console.write(f"Cloning {source.described}...")
    try:
        clone = await services.process_runner.stream(
            _clone_command(source, root),
            lambda line: services.console.write(f"{RAW}{line}"),
        )
    except asyncio.CancelledError:
        await _discard(root, services)
        raise

    if clone.exit_code != 0:
        return PackActionResult(
            available=True,
            message=f"Could not clone the {STACK_NAME} template.",
            exit_code=clone.exit_code,
        )

    try:
        services.finalizer.record_template(
            root, source, await _cloned_revision(root, services), STACK_NAME
        )
        report = await services.finalizer.finalize(
            root,
            context.identity,
            rewrites=(
                IdentityRewrite(
                    relative_path=expo.APP_MANIFEST,
                    rewrite=expo.rewriter(services.config.bundle_prefix()),
                    required=True,
                ),
            ),
        )
    except (NotAProjectError, CannotStampIdentity) as error:
        # The clone is not a template this toolbox can finish, and an unfinished
        # one still answers to the template's name in four places. Nothing is
        # kept rather than handing back a project that is subtly not one.
        await _discard(root, services)
        return PackActionResult(
            available=True, message=f"{error} Nothing was kept.", exit_code=1
        )
    except asyncio.CancelledError:
        await _discard(root, services)
        raise

    if context.flag("install", False):
        services.console.write("Installing dependencies with npm...")
        services.console.write(
            f"{RAW}Only problems are shown. This usually takes a few minutes."
        )
        # npm is thousands of lines of nothing and one line that matters, and
        # the run's own narration is what gets lost if all of it comes through.
        watcher = QuietRun(services.console.write)
        install = await services.process_runner.stream(
            ("npm", "install", "--prefix", str(root)), watcher
        )
        if install.exit_code != 0:
            watcher.explain_failure()
            return PackActionResult(
                available=True,
                message=f"Created {display_path(root)}/, but npm install failed.",
                exit_code=install.exit_code,
            )
        services.console.write(f"Dependencies installed in {watcher.elapsed}s.")

    return PackActionResult(
        available=True,
        message=(
            f"Created {STACK_NAME} project '{context.identity.title}' "
            f"at {display_path(root)}/ — "
            f"{report.summary}, {report.repository}."
        ),
    )


async def scaffold_controller(
    context: ScaffoldContext, services: PackServices
) -> PackActionResult:
    return await run_generator(context, services, GENERATORS, RENDERERS, STACK_NAME)


def script_source(services: PackServices) -> TemplateSource:
    return services.config.script_source(PACK_KEY, SCRIPTS)


async def script_actions(services: PackServices) -> ScriptCatalogue:
    return await scripts.catalogue_for(
        script_source(services),
        services,
        STACK_NAME,
        compare=services.config.script_check(PACK_KEY),
    )


async def script_status(services: PackServices, *, compare: bool = False) -> ScriptCatalogue:
    return await scripts.status_for(script_source(services), services, compare=compare)


async def install_scripts(
    services: PackServices, *, replace: bool = False
) -> PackActionResult:
    problem = await scripts.install(
        script_source(services), services, STACK_NAME, replace=replace
    )
    if problem:
        return PackActionResult(available=True, message=problem, exit_code=1)
    verb = "Replaced" if replace else "Installed"
    return PackActionResult(
        available=True,
        message=f"{verb} the {STACK_NAME} scripts in the store.",
    )


async def apply_script_update(
    choice: ScriptUpdate, services: PackServices
) -> PackActionResult:
    if choice is ScriptUpdate.RECLONE:
        return await install_scripts(services, replace=True)
    if choice is ScriptUpdate.SILENCE:
        written = scripts.stop_watching(PACK_KEY, services)
        return PackActionResult(
            available=True,
            message=(
                f"Not checking the {STACK_NAME} scripts again — "
                f"noted in {written}, and still in Settings."
            ),
        )
    return PackActionResult(
        available=True, message=f"Carrying on with the {STACK_NAME} scripts in the store."
    )


async def run_script(
    action: ScriptAction, values: OptionValues, services: PackServices
) -> PackActionResult:
    repository = scripts.repository_path(
        services.config.scripts_root(), script_source(services)
    )
    return await scripts.run_action(action, values, repository, services)


async def build(services: PackServices) -> PackActionResult:
    # Reached when the store is readable and declares nothing Build can offer —
    # a store that could not be read says so on the stack menu long before here.
    # A section with no template and no filename is a workflow; one carrying
    # both is a generator, and those are Scaffold's Components.
    return PackActionResult(
        available=False,
        message=(
            f"{STACK_NAME} declares no build workflow. "
            f"Add a config section without a template to {SCRIPTS.url}."
        ),
    )


def _clone_command(source: TemplateSource, root: Path) -> tuple[str, ...]:
    branch = ("--branch", source.ref) if source.ref else ()
    return ("git", "clone", "--depth", "1", *branch, source.url, str(root))


async def _cloned_revision(root: Path, services: PackServices) -> str:
    result = await services.process_runner.capture(
        ("git", "-C", str(root), "rev-parse", "HEAD")
    )
    return result.stdout.strip() if result.exit_code == 0 else ""


async def _discard(root: Path, services: PackServices) -> None:
    if services.file_system.exists(root):
        await services.file_system.remove_tree(root)


SCREEN = "screen"
COMPONENT = "component"
SERVICE = "service"
HOOK = "hook"

GENERATORS = (
    Generator(
        key=SCREEN,
        name="Screen",
        description="a screen component with its styles",
        folder="app/screens",
    ),
    Generator(
        key=COMPONENT,
        name="Component",
        description="a reusable presentational component",
        folder="components",
    ),
    Generator(
        key=SERVICE,
        name="Service",
        description="a typed client for one API resource",
        folder="services",
    ),
    Generator(
        key=HOOK,
        name="Hook",
        description="a hook wrapping one piece of state",
        folder="hooks",
    ),
)

_SCREEN_FILE = """import { StyleSheet, Text, View } from "react-native";

export default function __PASCAL__Screen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>__TITLE__</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 20, fontWeight: "600" },
});
"""

_COMPONENT_FILE = """import { StyleSheet, Text, View } from "react-native";

type __PASCAL__Props = {
  label?: string;
};

export function __PASCAL__({ label = "__TITLE__" }: __PASCAL__Props) {
  return (
    <View style={styles.container}>
      <Text>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: 12 },
});
"""

_SERVICE_FILE = """import Constants from "expo-constants";

const baseUrl = Constants.expoConfig?.extra?.apiBaseUrl ?? "";

export type __PASCAL__ = {
  id: string;
};

export async function fetch__PASCAL__List(): Promise<__PASCAL__[]> {
  const response = await fetch(`${baseUrl}/__SLUG__`);
  if (!response.ok) {
    throw new Error(`__TITLE__ request failed: ${response.status}`);
  }
  return (await response.json()) as __PASCAL__[];
}
"""

_HOOK_FILE = """import { useCallback, useState } from "react";

export function use__PASCAL__(initial: string = "") {
  const [__CAMEL__, set__PASCAL__] = useState(initial);
  const reset = useCallback(() => set__PASCAL__(initial), [initial]);
  return { __CAMEL__, set__PASCAL__, reset };
}
"""


def _fill(template: str, name: ProjectName) -> str:
    for token, value in (
        ("__PASCAL__", name.pascal),
        ("__CAMEL__", name.camel),
        ("__TITLE__", name.title),
        ("__SLUG__", name.slug),
    ):
        template = template.replace(token, value)
    return template


def _screen(name: ProjectName) -> Mapping[str, str]:
    return {f"{name.pascal}Screen.tsx": _fill(_SCREEN_FILE, name)}


def _component(name: ProjectName) -> Mapping[str, str]:
    return {f"{name.pascal}.tsx": _fill(_COMPONENT_FILE, name)}


def _service(name: ProjectName) -> Mapping[str, str]:
    return {f"{name.camel}Service.ts": _fill(_SERVICE_FILE, name)}


def _hook(name: ProjectName) -> Mapping[str, str]:
    return {f"use{name.pascal}.ts": _fill(_HOOK_FILE, name)}


RENDERERS: Mapping[str, Renderer] = {
    SCREEN: _screen,
    COMPONENT: _component,
    SERVICE: _service,
    HOOK: _hook,
}
