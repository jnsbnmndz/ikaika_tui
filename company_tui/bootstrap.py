"""Constructs the object graph: every concrete port, capability and template pack."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from company_tui.application.app import Application
from company_tui.application.registry import CapabilityRegistry
from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.application.updates import CACHE_DIRECTORY, UpdateWatch
from company_tui.capabilities.advanced import AdvancedCapability
from company_tui.capabilities.app_setup import AppSetupCapability
from company_tui.capabilities.build import BuildCapability
from company_tui.capabilities.builder import BuilderCapability
from company_tui.capabilities.deploy import DeployCapability
from company_tui.capabilities.doctor import DoctorCapability
from company_tui.capabilities.scaffold import ScaffoldCapability
from company_tui.capabilities.scripts import ScriptsCapability
from company_tui.capabilities.settings import SettingsCapability
from company_tui.capabilities.updates import UpdatesCapability
from company_tui.domain import naming
from company_tui.domain.destinations import DestinationLocks
from company_tui.domain.scaffolding import ProjectFinalizer
from company_tui.domain.updates import BUILD_UNKNOWN, build_kind
from company_tui.infrastructure.config import FileConfig
from company_tui.infrastructure.filesystem import LocalFileSystem
from company_tui.infrastructure.handover import WindowsHandover
from company_tui.infrastructure.processes import LocalProcessRunner
from company_tui.infrastructure.recent_file import FileRecentPaths
from company_tui.infrastructure.release_feed import HttpAssetDownload, HttpReleaseFeed
from company_tui.infrastructure.session_file import FileSessionMemory
from company_tui.infrastructure.update_state import FileUpdateState, state_path
from company_tui.presentation.plain_console import PlainConsole
from company_tui.presentation.ui import Ui
from company_tui.templates.flutter.pack import FlutterTemplatePack
from company_tui.templates.python.pack import PythonTemplatePack
from company_tui.templates.react.pack import ReactTemplatePack
from company_tui.templates.react_native.pack import ReactNativeTemplatePack
from company_tui.templates.services import PackServices
from company_tui.version import APP_VERSION

if TYPE_CHECKING:
    from company_tui.presentation.tui_console import TuiConsole


def running_build() -> str:
    """Which line this process is: the release build, the debug build, or neither."""
    if not getattr(sys, "frozen", False):
        return BUILD_UNKNOWN
    return build_kind(sys.executable)


def _build_capability_registry(console: Ui) -> CapabilityRegistry:
    file_system = LocalFileSystem()
    process_runner = LocalProcessRunner()
    config = FileConfig()
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
    arranging = BuilderCapability(console=console, config=config)
    registry = CapabilityRegistry(
        menu=config.layout().menu,
        capabilities=(
            ScaffoldCapability(
                console=console,
                pack_registry=pack_registry,
                config=config,
                locks=DestinationLocks(),
            ),
            BuildCapability(
                console=console, pack_registry=pack_registry, config=config
            ),
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
            AppSetupCapability(console=console, config=config),
            UpdatesCapability(
                console=console,
                config=config,
                feed=HttpReleaseFeed(),
                version=APP_VERSION,
                build=running_build(),
                downloads=HttpAssetDownload(),
                state=FileUpdateState(state_path(running_build())),
            ),
            AdvancedCapability(console=console, config=config),
            arranging,
        ),
    )
    arranging.knows(registry)
    return registry


def create_application(console: PlainConsole) -> Application:
    return Application(console=console, registry=_build_capability_registry(console))


def _build_update_watch() -> UpdateWatch:
    """The launch-time check, with every piece of I/O behind a port."""
    return UpdateWatch(
        config=FileConfig(),
        feed=HttpReleaseFeed(),
        downloads=HttpAssetDownload(),
        state=FileUpdateState(state_path(running_build())),
        handover=WindowsHandover(),
        version=APP_VERSION,
        cache=naming.store_dir() / CACHE_DIRECTORY,
        build=running_build(),
    )


def create_tui_console(start: str = "") -> TuiConsole:
    from company_tui.presentation.tui_console import TuiConsole

    console = TuiConsole(
        workspace_label=Path.cwd().name,
        memory=FileSessionMemory(),
        workspace=str(Path.cwd().resolve()),
        watch=_build_update_watch(),
        recent=FileRecentPaths(),
        layout=FileConfig().layout(),
    )
    console.application = Application(
        console=console, registry=_build_capability_registry(console)
    )
    console.start_capability = start
    return console
