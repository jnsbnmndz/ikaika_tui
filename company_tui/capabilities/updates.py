"""Asking the release feed whether there is a newer build than this one."""

from datetime import UTC, datetime
from pathlib import Path

from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.updates import (
    BUILD_UNKNOWN,
    CHANNEL_FOR_BUILD,
    CHANNEL_LABELS,
    AssetDownloadPort,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateSource,
    UpdateState,
    UpdateStatePort,
    choose,
    parse_version,
)
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

DOWNLOAD_KEY = "download"
FOLDER_KEY = "folder"
INSTALL_KEY = "install"
ANYWAY_KEY = "anyway"
LOCAL_KEY = "local"
INSTALLER_KEY = "installer"

NOT_CONFIGURED = "not configured - set it in Advanced"

NO_FILE_CHOSEN = "No installer chosen - browse for one, or untick the box to use the feed."
NO_SUCH_FILE = "There is no file at {path}."
NOT_AN_INSTALLER = "{name} is not a setup program - it has to be a .exe."
"""Refused rather than attempted."""

UNKNOWN_BUILD_WARNING = (
    "Chosen by hand, so nothing here knows what version it holds or which "
    "install it replaces. A debug build installs beside the release one."
)
"""Said before the app is asked to run it."""

INSTALL_HINT = "Ctrl+U installs it and closes the toolbox."
"""Said after a download, because the download is not the end of it any more."""

class UpdatesCapability(Capability):
    def __init__(
        self,
        console: Ui,
        config: ConfigPort,
        feed: ReleaseFeedPort,
        version: str,
        downloads: AssetDownloadPort,
        state: UpdateStatePort | None = None,
        build: str = BUILD_UNKNOWN,
    ) -> None:
        self._console = console
        self._config = config
        self._feed = feed
        self._downloads = downloads
        """The same downloader the launch check uses. One implementation of."""
        self._state = state
        """Where a finished download is recorded, so the chrome can offer to."""
        self._version = version
        self._build = build
        """Which line this build is on, so a release that could not replace it is."""

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            key="updates",
            name="Check for Updates",
            description="See whether a newer build has been published",
        )

    async def execute(self) -> int:
        while True:
            values = await self._console.open_run_panel(
                "Check for Updates", self._options(self._config.update_source())
            )
            if values is None:
                return CANCELLED

            outcome = await self._console.run_in_panel(self._check(values))
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

    def _channel_label(self, source: UpdateSource) -> str:
        """What the form says the channel is, which is not always what it is set to."""
        if self._build in CHANNEL_FOR_BUILD:
            channel = CHANNEL_FOR_BUILD[self._build]
            return f"{CHANNEL_LABELS[channel]} - this is the {self._build} build"
        return CHANNEL_LABELS.get(source.channel, source.channel)

    def _options(self, source: UpdateSource) -> tuple[Option, ...]:
        return (
            Option(
                key="installed",
                label="Installed",
                kind=OptionKind.INFO,
                default=self._version,
            ),
            Option(
                key="source",
                label="Looking at",
                kind=OptionKind.INFO,
                default=source.repository or NOT_CONFIGURED,
            ),
            Option(
                key="channel",
                label="Channel",
                kind=OptionKind.INFO,
                default=self._channel_label(source),
            ),
            Option(
                key=ANYWAY_KEY,
                label="Download and install anyway",
                kind=OptionKind.BOOLEAN,
                default=False,
                help=(
                    "Fetch and run the latest release even when it is the "
                    "version already running. A repair: the installer removes "
                    "the old copy first either way, so this rebuilds the "
                    "install rather than layering on it."
                ),
            ),
            Option(
                key=INSTALL_KEY,
                label="Install it when the download finishes",
                kind=OptionKind.BOOLEAN,
                default=False,
                help=(
                    "Asks first, then closes the toolbox, installs, and "
                    "reopens on the new build. Leave it off to be told where "
                    "the installer was saved instead."
                ),
            ),
            Option(
                key=DOWNLOAD_KEY,
                label="Download the installer",
                kind=OptionKind.BOOLEAN,
                default=False,
                help=(
                    "Saves it and tells you where. It is never run for you - the "
                    "installer replaces the files this app is running from."
                ),
            ),
            Option(
                key=FOLDER_KEY,
                label="Download into",
                kind=OptionKind.PATH,
                default=str(Path.home() / "Downloads"),
                help="Only used when downloading.",
            ),
            Option(
                key=LOCAL_KEY,
                label="Run an installer I already have",
                kind=OptionKind.BOOLEAN,
                default=False,
                help=(
                    "Runs a setup program you point at instead of asking the "
                    "feed. Nothing above applies - no check and no download - so "
                    "a build that has not been published can be installed the "
                    "same way a released one is. It is how an update is tested "
                    "before anyone else gets it."
                ),
            ),
            Option(
                key=INSTALLER_KEY,
                label="Installer to run",
                kind=OptionKind.FILE,
                default="",
                help="Only used when the box above is ticked.",
            ),
        )

    async def _check(self, values: OptionValues) -> tuple[str, bool]:
        if values.get(LOCAL_KEY):
            return await self._install_file(values)

        source = self._config.update_source()
        problem = source.problem
        if problem:
            self._console.write(f"Cannot check: {problem}.")
            self._console.write("Advanced is where the update source is set.")
            return (f"Update checking is {problem}.", False)

        installed = parse_version(self._version)
        self._console.write(f"Installed: {installed.text or self._version}")
        self._console.write(f"Asking {source.releases_url}...")

        try:
            releases = await self._feed.releases(source)
        except ReleaseFeedError as error:
            return (f"Could not check for updates: {error}", False)

        if not releases:
            return (f"{source.repository} has published no releases yet.", True)

        self._console.write(f"{len(releases)} release(s) published.")
        latest = choose(releases, source, self._build)
        if latest is None:
            where = "" if self._build else " Advanced is where that is changed."
            return (
                (
                    f"{source.repository} has published nothing on the "
                    f"{self._channel_label(source)} channel.{where}"
                ),
                True,
            )

        available = latest.version
        self._console.write(f"Latest: {latest.tag} ({available.text or 'unversioned'})")
        if latest.asset_name:
            megabytes = latest.asset_size / (1024 * 1024)
            self._console.write(f"Asset: {latest.asset_name} ({megabytes:.1f} MB)")
        else:
            self._console.write(
                f"No asset in that release matches '{source.asset_pattern}'."
            )
        if latest.page_url:
            self._console.write(latest.page_url)

        if not available.valid:
            return (
                f"{latest.tag} does not parse as a version, so it cannot be compared.",
                False,
            )
        if not available.newer_than(installed) and not values.get(ANYWAY_KEY):
            return (f"Up to date - {self._version} is current.", True)
        if not available.newer_than(installed):
            self._console.write(
                f"{self._version} is already current - reinstalling it as asked."
            )

        for line in latest.notes.splitlines()[:20]:
            self._console.write(line)

        if not values.get(DOWNLOAD_KEY) and not values.get(ANYWAY_KEY):
            return (
                (
                    f"{latest.tag} is newer than {self._version}. "
                    "Tick 'Download the installer' to fetch it."
                ),
                True,
            )
        return await self._download(latest, values)

    async def _download(
        self, release: Release, values: OptionValues
    ) -> tuple[str, bool]:
        if not release.asset_url:
            return (
                f"{release.tag} is newer, but it has no installer to download.",
                False,
            )
        folder = Path(str(values.get(FOLDER_KEY, "")).strip() or ".").expanduser()
        target = folder / (release.asset_name or f"{release.tag}-setup.exe")

        self._console.write(f"Downloading to {target}...")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            written = await self._downloads.fetch(release.asset_url, target)
        except Exception as error:  # noqa: BLE001 - the port raises OSError or URLError
            return (f"The download failed: {error}", False)

        megabytes = written / (1024 * 1024)
        self._console.write(f"Saved {written} bytes.")
        self._remember(release, target)

        if values.get(INSTALL_KEY) or values.get(ANYWAY_KEY):
            return await self._install(release, target, megabytes)

        self._console.write(INSTALL_HINT)
        return (f"Downloaded {target.name} ({megabytes:.1f} MB) to {folder}", True)

    async def _install_file(self, values: OptionValues) -> tuple[str, bool]:
        """Hand over an installer the user picked, with no feed involved at all."""
        raw = str(values.get(INSTALLER_KEY, "")).strip()
        if not raw:
            return (NO_FILE_CHOSEN, False)
        target = Path(raw).expanduser()
        if not target.is_file():
            return (NO_SUCH_FILE.format(path=target), False)
        if target.suffix.lower() != ".exe":
            return (NOT_AN_INSTALLER.format(name=target.name), False)

        self._console.write(f"Installer: {target}")
        self._console.write(UNKNOWN_BUILD_WARNING)
        problem = await self._console.install_update(str(target), target.name)
        if problem:
            return (f"{target.name} was not installed: {problem}", False)
        return (f"Installing {target.name}.", True)

    async def _install(
        self, release: Release, target: Path, megabytes: float
    ) -> tuple[str, bool]:
        """Hand the installer to the app, which is the only thing that can run it."""
        version = release.version.text or release.tag
        self._console.write(f"Installing {version} - the toolbox will reopen.")
        problem = await self._console.install_update(str(target), version)
        if problem:
            self._console.write(INSTALL_HINT)
            return (f"Downloaded {target.name} ({megabytes:.1f} MB), but {problem}", False)
        return (f"Installing {version}.", True)

    def _remember(self, release: Release, target: Path) -> None:
        """Record the download where the chrome looks for one."""
        if self._state is None:
            return
        try:
            self._state.save(
                UpdateState(
                    checked_at=datetime.now(UTC).isoformat(),
                    tag=release.tag,
                    installer=str(target.resolve()),
                )
            )
        except Exception:  # noqa: BLE001 - see the docstring
            return

