"""The settings most people should never need to change."""

from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort, ConfigScope, Settings
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.updates import (
    CHANNEL_LABELS,
    CHANNEL_OFFICIAL,
    CHANNELS,
    DEFAULT_API_BASE,
    DEFAULT_ASSET_PATTERN,
    UpdateSource,
)
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

SCOPE_KEY = "scope"
REPOSITORY_KEY = "repository"
API_BASE_KEY = "api_base"
CHANNEL_KEY = "channel"
ASSET_KEY = "asset_pattern"
RESET_KEY = "reset"


class AdvancedCapability(Capability):
    def __init__(self, console: Ui, config: ConfigPort) -> None:
        self._console = console
        self._config = config

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="advanced",
            name="Advanced",
            description="Where updates come from, and other rarely-touched settings",
        )

    async def execute(self) -> int:
        while True:
            values = await self._console.open_run_panel(
                "Advanced", self._options(self._config.settings())
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

    def _options(self, settings: Settings) -> tuple[Option, ...]:
        source = settings.updates
        active = self._config.active_location()
        return (
            Option(
                key=SCOPE_KEY,
                label="Save to",
                kind=OptionKind.CHOICE,
                choices=tuple(scope.value for scope in ConfigScope),
                default=ConfigScope.USER.value,
                help=(
                    "user is usually right here: which build you run is a "
                    "property of this machine, not of the repository."
                ),
            ),
            Option(
                key="active_file",
                label="Reading now",
                kind=OptionKind.INFO,
                default=str(active) if active else "the built-in defaults",
            ),
            Option(
                key=REPOSITORY_KEY,
                label="Update repository",
                kind=OptionKind.TEXT,
                default=source.repository,
                help="owner/name, not a URL. Empty turns update checking off.",
            ),
            Option(
                key=API_BASE_KEY,
                label="API host",
                kind=OptionKind.TEXT,
                default=source.api_base,
                help=f"The API root. {DEFAULT_API_BASE} unless this is Enterprise.",
            ),
            Option(
                key=CHANNEL_KEY,
                label="Channel",
                kind=OptionKind.CHOICE,
                choices=tuple(CHANNEL_LABELS[name] for name in CHANNELS),
                default=CHANNEL_LABELS[source.channel],
                help=(
                    "Debug builds are published as prereleases. An installed "
                    "build only ever takes updates from its own line - a debug "
                    "installer cannot replace a release install, it installs "
                    "beside it - so all three settings mean the same thing to "
                    "it. This decides for a copy run from source, which has no "
                    "install to replace."
                ),
            ),
            Option(
                key=ASSET_KEY,
                label="Installer pattern",
                kind=OptionKind.TEXT,
                default=source.asset_pattern,
                help=f"Which asset of a release is the installer. Default {DEFAULT_ASSET_PATTERN}.",
            ),
            Option(
                key="releases_url",
                label="Would ask",
                kind=OptionKind.INFO,
                default=source.releases_url if source.configured else "nothing yet",
            ),
            Option(
                key=RESET_KEY,
                label="Reset these to defaults",
                kind=OptionKind.BOOLEAN,
                default=False,
                help="Clears the repository and puts everything else back.",
            ),
        )

    @staticmethod
    def _channel_named(label: str) -> str:
        for name, shown in CHANNEL_LABELS.items():
            if shown == label or name == label:
                return name
        return CHANNEL_OFFICIAL

    async def _save(self, values: OptionValues) -> tuple[str, bool]:
        current = self._config.settings()

        if values.get(RESET_KEY):
            source = UpdateSource()
            self._console.write("Reset the update source to its defaults.")
        else:
            source = UpdateSource(
                repository=str(values.get(REPOSITORY_KEY, "")).strip(),
                api_base=str(values.get(API_BASE_KEY, "")).strip() or DEFAULT_API_BASE,
                channel=self._channel_named(str(values.get(CHANNEL_KEY, ""))),
                asset_pattern=str(values.get(ASSET_KEY, "")).strip()
                or DEFAULT_ASSET_PATTERN,
            )
            if source.configured and source.problem:
                return (f"That is not a usable update source: {source.problem}.", False)

        scope = self._scope(values)
        settings = Settings(
            workspace_root=current.workspace_root,
            bundle_prefix=current.bundle_prefix,
            templates=current.templates,
            scripts_root=current.scripts_root,
            scripts=current.scripts,
            updates=source,
            script_checks=current.script_checks,
        )

        self._console.write(f"Writing {self._config.location(scope)}...")
        path = self._config.save(settings, scope)

        self._console.write(f"Repository: {source.repository or 'not configured'}")
        self._console.write(f"API host: {source.api_base}")
        self._console.write(
            f"Channel: {CHANNEL_LABELS.get(source.channel, source.channel)}"
        )
        self._console.write(f"Installer pattern: {source.asset_pattern}")
        if source.configured:
            self._console.write(f"Would ask: {source.releases_url}")

        return (f"Saved advanced settings to {path}", True)

    @staticmethod
    def _scope(values: OptionValues) -> ConfigScope:
        chosen = str(values.get(SCOPE_KEY, "")).strip()
        return next(
            (scope for scope in ConfigScope if scope.value == chosen),
            ConfigScope.USER,
        )
