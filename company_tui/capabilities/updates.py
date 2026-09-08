"""Asking the release feed whether there is a newer build than this one.

The installer is published by `.github/workflows/release.yml`, which tags an
official build `v<x.y.z>-released` and publishes a debug one as a prerelease.
This is the consumer of that: read the feed, compare, and say which of the three
answers it is - up to date, something newer, or the check could not be made.


IT DOWNLOADS, AND IT DOES NOT RUN ANYTHING ITSELF

The warning this paragraph used to carry was right and still is: the installer
replaces the very files this process is executing from, so a launch from here
would have the uninstaller deleting a running program. The one-line-of-code
version of this feature is the one that corrupts an install.

What changed is that there is now a version that is not one line of code.
`infrastructure/handover.py` starts a third process that waits for this one to
exit and only then runs the installer, and `Ctrl+U` is how somebody asks for
that. So this capability records what it downloaded - through `UpdateStatePort`,
the same file the launch check reads - and the install is offered by the chrome,
which is the only thing here that can quit the app without cancelling the
workflow doing the asking. See
`docs/decisions/0004-the-toolbox-can-install-its-own-update.md`.


WHERE IT LOOKS IS A SETTING, AND IT HAS A DEFAULT

`UpdateSource` comes from the settings file and is edited in Advanced. A fork, an
internal mirror and a GitHub Enterprise host are the same program pointed
somewhere else, which is why it is a setting at all - but it defaults to this
build's own repository rather than to nothing, because a check that is off until
somebody finds the screen that turns it on is a feature that does not exist. See
`DEFAULT_REPOSITORY`.

Empty is still off, and an unconfigured source is still reported as unconfigured,
with the name of the screen that configures it - which is now the state somebody
chose rather than the state it shipped in.
"""

from datetime import UTC, datetime
from pathlib import Path

from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.updates import (
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

NOT_CONFIGURED = "not configured - set it in Advanced"

INSTALL_HINT = "Ctrl+U installs it and closes the toolbox."
"""Said after a download, because the download is not the end of it any more.

Not a prompt and not a dialog: this runs inside a run panel, and quitting the app
from inside a workflow means cancelling the workflow that asked - which is the
one path that cannot work. The chrome owns the install; this says so.
"""


class UpdatesCapability(Capability):
    def __init__(
        self,
        console: Ui,
        config: ConfigPort,
        feed: ReleaseFeedPort,
        version: str,
        downloads: AssetDownloadPort,
        state: UpdateStatePort | None = None,
    ) -> None:
        self._console = console
        self._config = config
        self._feed = feed
        self._downloads = downloads
        """The same downloader the launch check uses. One implementation of
        "fetch an installer without leaving a partial file that looks whole"."""
        self._state = state
        """Where a finished download is recorded, so the chrome can offer to
        install it. Optional: the plain console has no chrome to offer it in."""
        # Passed in rather than imported from branding: this is the one fact the
        # whole comparison rests on, and a capability that reads it from a module
        # global cannot be tested against a version it is not running.
        self._version = version

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
                default=CHANNEL_LABELS.get(source.channel, source.channel),
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
        )

    async def _check(self, values: OptionValues) -> tuple[str, bool]:
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
        latest = choose(releases, source)
        if latest is None:
            # Every release was a prerelease and prereleases are not wanted. Not
            # a failure: the honest answer is that nothing is on offer, and
            # saying which switch would change that is more use than an error.
            return (
                (
                    f"{source.repository} has published nothing on the "
                    f"{CHANNEL_LABELS.get(source.channel, source.channel)} "
                    "channel. Advanced is where that is changed."
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
            # Asked for explicitly. Said out loud, because "installing an update" and
            # "reinstalling the version you are running" are different acts and only
            # one of them was ticked.
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

    async def _install(
        self, release: Release, target: Path, megabytes: float
    ) -> tuple[str, bool]:
        """Hand the installer to the app, which is the only thing that can run it.

        On success this does not come back: the app confirms, arms the handover and
        starts shutting down, and this workflow is one of the runs that shutting down
        cancels. So the line before it is the last thing written - said in the past
        tense on purpose, because by the time anybody reads it, it has happened.
        """
        version = release.version.text or release.tag
        self._console.write(f"Installing {version} - the toolbox will reopen.")
        problem = await self._console.install_update(str(target), version)
        if problem:
            self._console.write(INSTALL_HINT)
            return (f"Downloaded {target.name} ({megabytes:.1f} MB), but {problem}", False)
        # Reached only if the app declined to leave after all; the shutdown above does
        # not return.
        return (f"Installing {version}.", True)

    def _remember(self, release: Release, target: Path) -> None:
        """Record the download where the chrome looks for one.

        `checked_at` goes down with it: the feed did answer, and leaving the
        timestamp alone would have the launch check ask again within minutes for
        an answer it already has on disk.

        Swallowed, like every other write to that store. A recorded download that
        failed to record costs the offer of an install; it does not cost the
        installer, which is on disk with its path in the message above.
        """
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

