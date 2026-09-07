from pathlib import Path

from company_tui.application.app import Application
from company_tui.application.registry import CapabilityRegistry
from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.capabilities.advanced import AdvancedCapability
from company_tui.capabilities.app_setup import AppSetupCapability
from company_tui.capabilities.build import BuildCapability
from company_tui.capabilities.deploy import DeployCapability
from company_tui.capabilities.doctor import DoctorCapability
from company_tui.capabilities.scaffold import ScaffoldCapability
from company_tui.capabilities.scripts import ScriptsCapability
from company_tui.capabilities.settings import SettingsCapability
from company_tui.capabilities.updates import UpdatesCapability
from company_tui.domain.destinations import DestinationLocks
from company_tui.domain.scaffolding import ProjectFinalizer
from company_tui.infrastructure.config import FileConfig
from company_tui.infrastructure.filesystem import LocalFileSystem
from company_tui.infrastructure.processes import LocalProcessRunner
from company_tui.infrastructure.release_feed import HttpReleaseFeed
from company_tui.infrastructure.session_file import FileSessionMemory
from company_tui.presentation.branding import APP_VERSION
from company_tui.presentation.plain_console import PlainConsole
from company_tui.presentation.tui_console import TuiConsole
from company_tui.presentation.ui import Ui
from company_tui.templates.flutter.pack import FlutterTemplatePack
from company_tui.templates.python.pack import PythonTemplatePack
from company_tui.templates.react.pack import ReactTemplatePack
from company_tui.templates.react_native.pack import ReactNativeTemplatePack
from company_tui.templates.services import PackServices


def _build_capability_registry(console: Ui) -> CapabilityRegistry:
    file_system = LocalFileSystem()
    process_runner = LocalProcessRunner()
    config = FileConfig()
    # The finalizer narrates into whichever panel is open, so it reports through
    # the same console every pack writes to rather than one of its own.
    services = PackServices(
        console=console,
        file_system=file_system,
        process_runner=process_runner,
        config=config,
        finalizer=ProjectFinalizer(file_system, process_runner, console.write),
    )
    pack_registry = TemplatePackRegistry(
        packs=(
            PythonTemplatePack(services),
            ReactNativeTemplatePack(services),
            FlutterTemplatePack(services),
            ReactTemplatePack(services),
        )
    )
    return CapabilityRegistry(
        capabilities=(
            ScaffoldCapability(
                console=console, pack_registry=pack_registry, locks=DestinationLocks()
            ),
            BuildCapability(console=console, pack_registry=pack_registry),
            DeployCapability(console=console),
            ScriptsCapability(console=console, services=services),
            SettingsCapability(
                console=console, config=config, pack_registry=pack_registry
            ),
            DoctorCapability(
                console=console,
                pack_registry=pack_registry,
                process_runner=process_runner,
                config=config,
            ),
            # The toolbox's own three, after the six about projects. Order is
            # what the menu numbers, so appending is what keeps 01-06 where
            # people have learned them.
            AppSetupCapability(console=console, config=config),
            UpdatesCapability(
                console=console,
                config=config,
                feed=HttpReleaseFeed(),
                # The running version, read once from the one file that holds
                # it. Passed in so the comparison has a single source and can be
                # tested against a version this process is not.
                version=APP_VERSION,
            ),
            AdvancedCapability(console=console, config=config),
        )
    )


def create_application(console: PlainConsole) -> Application:
    return Application(console=console, registry=_build_capability_registry(console))


def create_tui_console(start: str = "") -> TuiConsole:
    # Keyed by the directory the toolbox was started in, which is the project
    # whose tabs these are. The store itself lives under the user's home, so one
    # person's open forms never arrive in somebody else's checkout.
    console = TuiConsole(
        workspace_label=Path.cwd().name,
        memory=FileSessionMemory(),
        workspace=str(Path.cwd().resolve()),
    )
    console.application = Application(
        console=console, registry=_build_capability_registry(console)
    )
    console.start_capability = start
    return console
