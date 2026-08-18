"""Editing `ikaika.toml` from inside the toolbox.

The settings are already a port, so the only thing missing was somewhere to
change them. It reuses the run panel rather than inventing a screen: the same
form on the left, the same terminal on the right saying which file was written
and what is now in it.
"""

import re
from collections.abc import Mapping
from pathlib import Path

from company_tui.application.template_registry import TemplatePackRegistry
from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import (
    DEFAULT_SCRIPTS_ROOT,
    DEFAULT_WORKSPACE_ROOT,
    ConfigPort,
    ConfigScope,
    Settings,
    TemplateSource,
)
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.script_config import ScriptCatalogue
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

SCOPE_KEY = "scope"
WORKSPACE_KEY = "workspace_root"
PREFIX_KEY = "bundle_prefix"
SCRIPTS_ROOT_KEY = "scripts_root"
URL_KEY = "url_"
REF_KEY = "ref_"
SCRIPT_URL_KEY = "scripturl_"
SCRIPT_REF_KEY = "scriptref_"
STORE_KEY = "store_"
FETCH_KEY = "fetch_"
CHECK_KEY = "check_"

NOT_INSTALLED = "not installed — tick below to install it"

BUNDLE_PREFIX_SHAPE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$")
NO_FILE_YET = "none yet — these are the built-in defaults"


class SettingsCapability(Capability):
    def __init__(
        self, console: Ui, config: ConfigPort, pack_registry: TemplatePackRegistry
    ) -> None:
        self._console = console
        self._config = config
        self._pack_registry = pack_registry

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="settings",
            name="Settings",
            description="Edit the toolbox configuration",
        )

    async def execute(self) -> int:
        while True:
            # Re-read every time round: the previous pass may have written the
            # file this one is about to show — and may have installed the very
            # store the next form is about to report on.
            values = await self._console.open_run_panel(
                "Settings", self._options(self._config.settings(), await self._stores())
            )
            if values is None:
                return CANCELLED

            outcome = await self._console.run_in_panel(self._save(values))
            if outcome is None:
                failure = self._console.panel_failure()
                if await self._console.close_run_panel(
                    failure or STOPPED_MESSAGE, ok=False
                ):
                    continue
                return FAILED if failure else CANCELLED

            message, ok = outcome
            if await self._console.close_run_panel(message, ok=ok):
                continue
            return 0 if ok else FAILED

    async def _stores(self) -> dict[str, str]:
        """One line per stack about what is in the store, and nothing fetched.

        A form has to be on screen before anyone can ask for anything, so
        building it must never be what clones a repository — or opening Settings
        on a slow morning would be a network call nobody asked for.
        """
        described: dict[str, str] = {}
        for pack in self._pack_registry.all():
            if pack.script_source() is None:
                continue
            described[pack.info.key] = self._store_line(await pack.script_status())
        return described

    def _store_line(self, status: ScriptCatalogue) -> str:
        if not status.present:
            return NOT_INSTALLED
        folder = Path(status.location)
        try:
            shown = folder.relative_to(self._config.scripts_root()).as_posix()
        except ValueError:
            shown = folder.as_posix()
        if status.problem:
            return f"{shown} — unreadable"
        return f"{shown} — version {status.installed or 'unnamed'}"

    def _options(
        self, settings: Settings, stores: Mapping[str, str]
    ) -> tuple[Option, ...]:
        active = self._config.active_location()
        options = [
            Option(
                key=SCOPE_KEY,
                label="Save to",
                kind=OptionKind.CHOICE,
                choices=tuple(scope.value for scope in ConfigScope),
                default=ConfigScope.PROJECT.value,
                help="project: beside this repository · user: this machine's default.",
            ),
            Option(
                key="project_file",
                label="Project file",
                kind=OptionKind.INFO,
                default=str(self._config.location(ConfigScope.PROJECT)),
            ),
            Option(
                key="user_file",
                label="User file",
                kind=OptionKind.INFO,
                default=str(self._config.location(ConfigScope.USER)),
            ),
            Option(
                key="active_file",
                label="Reading now",
                kind=OptionKind.INFO,
                default=str(active) if active else NO_FILE_YET,
            ),
            Option(
                key=WORKSPACE_KEY,
                label="Workspace root",
                kind=OptionKind.PATH,
                default=settings.workspace_root,
                help="Where new projects are created. '.' is the current directory.",
            ),
            Option(
                key=PREFIX_KEY,
                label="Bundle prefix",
                kind=OptionKind.TEXT,
                default=settings.bundle_prefix,
                help="Reverse-DNS. iOS and Android identifiers are built on it.",
            ),
            Option(
                key=SCRIPTS_ROOT_KEY,
                label="Scripts root",
                kind=OptionKind.PATH,
                default=settings.scripts_root,
                help="Where build script repositories are kept, shared by every project.",
            ),
        ]

        # Only stacks that actually clone something have a source worth pinning.
        for pack in self._pack_registry.all():
            template = pack.template_source()
            if template is not None:
                options += [
                    Option(
                        key=f"{URL_KEY}{pack.info.key}",
                        label=f"{pack.info.name} template",
                        kind=OptionKind.TEXT,
                        default=template.url,
                        help="Repository this stack is cloned from.",
                    ),
                    Option(
                        key=f"{REF_KEY}{pack.info.key}",
                        label=f"{pack.info.name} ref",
                        kind=OptionKind.TEXT,
                        default=template.ref,
                        help="Branch or tag to pin. Empty means the default branch.",
                    ),
                ]
            script = pack.script_source()
            if script is not None:
                options += [
                    Option(
                        key=f"{SCRIPT_URL_KEY}{pack.info.key}",
                        label=f"{pack.info.name} scripts",
                        kind=OptionKind.TEXT,
                        default=script.url,
                        help="Repository this stack's build workflows are read from.",
                    ),
                    Option(
                        key=f"{SCRIPT_REF_KEY}{pack.info.key}",
                        label=f"{pack.info.name} scripts ref",
                        kind=OptionKind.TEXT,
                        default=script.ref,
                        help="Branch or tag to clone. Only read the first time it is fetched.",
                    ),
                    Option(
                        key=f"{STORE_KEY}{pack.info.key}",
                        label=f"{pack.info.name} store",
                        kind=OptionKind.INFO,
                        default=stores.get(pack.info.key, NOT_INSTALLED),
                    ),
                    Option(
                        key=f"{FETCH_KEY}{pack.info.key}",
                        label=(
                            f"Install {pack.info.name} scripts"
                            if stores.get(pack.info.key, "") == NOT_INSTALLED
                            else f"Re-clone {pack.info.name} scripts"
                        ),
                        kind=OptionKind.BOOLEAN,
                        default=False,
                        help=(
                            "Done when this form is saved. Re-cloning replaces the copy "
                            "in the store, and anything edited there goes with it."
                        ),
                    ),
                    Option(
                        key=f"{CHECK_KEY}{pack.info.key}",
                        label=f"Watch {pack.info.name} scripts",
                        kind=OptionKind.BOOLEAN,
                        default=settings.script_checks.get(pack.info.key, True),
                        help=(
                            "Compare the store against the repository when Build opens, "
                            "and offer to re-clone when they differ."
                        ),
                    ),
                ]
        return tuple(options)

    async def _save(self, values: OptionValues) -> tuple[str, bool]:
        prefix = str(values.get(PREFIX_KEY, "")).strip()
        if not BUNDLE_PREFIX_SHAPE.match(prefix):
            # Caught here rather than at the next scaffold, where it would have
            # already been written into an app's iOS and Android identifiers.
            return (
                f"'{prefix}' is not a bundle prefix — use reverse-DNS, like com.ikaika.",
                False,
            )

        scope = self._scope(values)
        settings = Settings(
            workspace_root=str(values.get(WORKSPACE_KEY, "")).strip()
            or DEFAULT_WORKSPACE_ROOT,
            bundle_prefix=prefix,
            templates=self._sources(values, URL_KEY, REF_KEY),
            scripts_root=str(values.get(SCRIPTS_ROOT_KEY, "")).strip()
            or DEFAULT_SCRIPTS_ROOT,
            scripts=self._sources(values, SCRIPT_URL_KEY, SCRIPT_REF_KEY),
            script_checks=self._checks(values),
        )

        self._console.write(f"Writing {self._config.location(scope)}...")
        path = self._config.save(settings, scope)

        self._console.write(f"Workspace root: {settings.workspace_root}")
        self._console.write(f"Bundle prefix: {settings.bundle_prefix}")
        self._console.write(f"Scripts root: {settings.scripts_root}")
        for key in sorted(settings.templates):
            self._console.write(f"{key}: {settings.templates[key].described}")
        for key in sorted(settings.scripts):
            self._console.write(f"{key} scripts: {settings.scripts[key].described}")

        # After the file, never before: what gets cloned is the URL and ref this
        # form just saved, not the ones it was opened with.
        failures = await self._fetch(values)
        if failures:
            return (f"Saved settings to {path}, but {failures} did not install.", False)
        return (f"Saved settings to {path}", True)

    async def _fetch(self, values: OptionValues) -> str:
        wanted = []
        for pack in self._pack_registry.all():
            if pack.script_source() is None or not values.get(f"{FETCH_KEY}{pack.info.key}"):
                continue
            wanted.append(pack)

        broken: list[str] = []
        for pack in wanted:
            status = await pack.script_status()
            outcome = await pack.install_scripts(replace=status.present)
            self._console.write(outcome.message)
            if outcome.exit_code != 0:
                broken.append(pack.info.name)
        return ", ".join(broken)

    def _checks(self, values: OptionValues) -> dict[str, bool]:
        return {
            pack.info.key: bool(values.get(f"{CHECK_KEY}{pack.info.key}", True))
            for pack in self._pack_registry.all()
            if pack.script_source() is not None
        }

    def _sources(
        self, values: OptionValues, url_key: str, ref_key: str
    ) -> dict[str, TemplateSource]:
        sources: dict[str, TemplateSource] = {}
        for pack in self._pack_registry.all():
            key = pack.info.key
            url = str(values.get(f"{url_key}{key}", "")).strip()
            if not url:
                continue
            sources[key] = TemplateSource(
                url=url, ref=str(values.get(f"{ref_key}{key}", "")).strip()
            )
        return sources

    @staticmethod
    def _scope(values: OptionValues) -> ConfigScope:
        chosen = str(values.get(SCOPE_KEY, "")).strip()
        return next(
            (scope for scope in ConfigScope if scope.value == chosen),
            ConfigScope.PROJECT,
        )
