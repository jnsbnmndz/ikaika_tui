"""Asking the release feed whether there is a newer build than this one.

The installer is published by `.github/workflows/release.yml`, which tags an
official build `v<x.y.z>-released` and publishes a debug one as a prerelease.
This is the consumer of that: read the feed, compare, and say which of the three
answers it is - up to date, something newer, or the check could not be made.


IT DOES NOT INSTALL ANYTHING

It downloads the installer when asked and says where it put it. Running it is
left to the person, and that is deliberate: the installer replaces the very
files this process is executing from, so launching it from here would have the
uninstaller deleting a running program. The one-line-of-code version of this
feature is the one that corrupts an install.


WHERE IT LOOKS IS A SETTING, NOT A CONSTANT

`UpdateSource` comes from the settings file and is edited in Advanced. Empty by
default - a fork, an internal mirror and a GitHub Enterprise host are the same
program pointed somewhere else, and this code should not guess which one it is a
build of. An unconfigured source is reported as unconfigured, with the name of
the screen that configures it.
"""

import asyncio
import urllib.error
import urllib.request
from pathlib import Path

from company_tui.domain.capability import CANCELLED, Capability, CapabilityInfo
from company_tui.domain.config import ConfigPort
from company_tui.domain.options import Option, OptionKind, OptionValues
from company_tui.domain.updates import (
    USER_AGENT,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateSource,
    choose,
    parse_version,
)
from company_tui.presentation.ui import Ui

STOPPED_MESSAGE = "Stopped before it finished."
FAILED = 1

DOWNLOAD_KEY = "download"
FOLDER_KEY = "folder"

NOT_CONFIGURED = "not configured - set it in Advanced"
DOWNLOAD_CHUNK = 64 * 1024


class UpdatesCapability(Capability):
    def __init__(
        self,
        console: Ui,
        config: ConfigPort,
        feed: ReleaseFeedPort,
        version: str,
    ) -> None:
        self._console = console
        self._config = config
        self._feed = feed
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
                default=(
                    "official releases and prereleases"
                    if source.include_prereleases
                    else "official releases only"
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
                    f"{source.repository} has only prereleases, and this is "
                    "set to official releases only."
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
        if not available.newer_than(installed):
            return (f"Up to date - {self._version} is current.", True)

        for line in latest.notes.splitlines()[:20]:
            self._console.write(line)

        if not values.get(DOWNLOAD_KEY):
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
            written = await self._fetch_to(release.asset_url, target)
        except (OSError, urllib.error.URLError) as error:
            return (f"The download failed: {error}", False)

        megabytes = written / (1024 * 1024)
        self._console.write(f"Saved {written} bytes.")
        self._console.write("Close the toolbox before running it.")
        return (f"Downloaded {target.name} ({megabytes:.1f} MB) to {folder}", True)

    async def _fetch_to(self, url: str, target: Path) -> int:
        # In a thread, and in chunks. urllib is blocking, and an installer is
        # tens of megabytes - read whole into memory it would hold that twice,
        # once in the buffer and once on the way to disk.
        def _pull() -> int:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}
            )
            total = 0
            with urllib.request.urlopen(request, timeout=60) as response:
                # A partial file must not be left looking like a finished one, so
                # it is written beside the target and moved into place at the end.
                staging = target.with_suffix(target.suffix + ".part")
                with staging.open("wb") as handle:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        total += len(chunk)
                staging.replace(target)
            return total

        return await asyncio.to_thread(_pull)
