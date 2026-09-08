"""The update check the app makes for itself as it starts.

`capabilities/updates.py` is somebody asking. This is the same question asked on their
behalf at launch, and everything different about it follows from nobody having asked:

- It may not delay the first paint, so it runs as a worker and every blocking part of it
  is already behind a thread.
- It may not report its own plumbing. Offline, rate-limited, an unparseable tag, a
  repository that does not exist - all of it is silence, exactly as the script-store
  version check is silent. A courtesy that explains why it could not be a courtesy is
  noise, and worse, it is noise at the moment the app opens.
- It may not ask on every launch. `due()` and a remembered timestamp are why.
- It downloads, and having downloaded, it remembers WHERE. A second launch with an
  installer already fetched touches the network not at all.

What it never does is install. `hand_over` arms the installer and returns; the caller
quits. Those are two decisions and they belong to two different things - this service
knows when there is something to install, and the interface knows whether the person in
front of it said yes.


THE COMPARISON IS THE SAME ONE THE MANUAL CHECK MAKES

`choose` then `newer_than`, out of `domain/updates.py`. Deliberately not a second
implementation with its own idea of what "newer" means: two answers to that question is
how an app offers a downgrade.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from company_tui.domain.config import ConfigPort
from company_tui.domain.updates import (
    NOTHING_TO_REPORT,
    AssetDownloadPort,
    HandoverPort,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateReport,
    UpdateSource,
    UpdateState,
    UpdateStatePort,
    choose,
    due,
    parse_version,
)

CACHE_DIRECTORY = "updates"
"""Where a fetched installer waits, under the toolbox's own store directory.

Not the temp directory: a download that survives a restart is the whole point of
remembering it, and %TEMP% is swept. Not the install directory either - that is the
directory the installer is about to delete.
"""


class UpdateWatch:
    """Looks for a newer build at launch, and arms the installer when asked."""

    def __init__(
        self,
        *,
        config: ConfigPort,
        feed: ReleaseFeedPort,
        downloads: AssetDownloadPort,
        state: UpdateStatePort,
        handover: HandoverPort,
        version: str,
        cache: Path,
    ) -> None:
        self._config = config
        self._feed = feed
        self._downloads = downloads
        self._state = state
        self._handover = handover
        self._version = version
        self._cache = cache

    async def look(self) -> UpdateReport:
        """What is waiting, or nothing. Never raises.

        Never raises is load-bearing rather than defensive: this is called from a worker
        started at mount, and an exception there is a traceback in a log nobody is
        reading, on the one screen where the app has not finished appearing yet.
        """
        try:
            return await self._look()
        except Exception as error:  # noqa: BLE001 - see the docstring
            return UpdateReport(problem=str(error))

    async def _look(self) -> UpdateReport:
        source = self._config.update_source()
        if not source.check_on_launch:
            return NOTHING_TO_REPORT
        if not source.configured or source.problem:
            # An unconfigured source is the shipped default, and a misconfigured one is
            # already reported - loudly, with the name of the screen that fixes it - by
            # the manual check. Saying it again here would be an error message at every
            # launch for a feature the user has not set up.
            return NOTHING_TO_REPORT

        installed = parse_version(self._version)
        state = self._state.load()

        remembered = self._remembered(state, installed)
        if remembered is not None:
            return remembered

        if not due(state, datetime.now(UTC)):
            return NOTHING_TO_REPORT

        return await self._ask(source, state, installed)

    def _remembered(self, state: UpdateState, installed) -> UpdateReport | None:
        """The answer from a previous launch, when it is still the answer.

        Three things have to hold: something was fetched, the file is still there, and it
        is still newer than what is running. The third is what stops a badge surviving
        the install it was offering - the app comes back up as the version that installer
        held, and without this check the state file would keep offering it to itself.
        """
        if not state.fetched:
            return None
        installer = Path(state.installer)
        if not installer.is_file():
            return None
        available = parse_version(state.tag)
        if not available.newer_than(installed):
            self._state.save(UpdateState(checked_at=state.checked_at))
            return None
        return UpdateReport(
            tag=state.tag,
            installed=installed,
            available=available,
            installer=str(installer),
        )

    async def _ask(
        self, source: UpdateSource, state: UpdateState, installed
    ) -> UpdateReport:
        try:
            releases = await self._feed.releases(source)
        except ReleaseFeedError as error:
            # Silent, and the timestamp is NOT written. An offline launch costs a failed
            # lookup and asks again next time; recording it would hold the check off for
            # six hours after the network came back.
            return UpdateReport(problem=str(error))

        now = datetime.now(UTC).isoformat()
        latest = choose(releases, source)
        if latest is None:
            return self._nothing_newer(now)

        available = latest.version
        if not available.valid or not available.newer_than(installed):
            return self._nothing_newer(now)

        installer = await self._fetch(latest)
        if installer is None:
            # The check succeeded and the download did not. The timestamp still goes
            # down: the feed answered, and asking it again in a minute would not make
            # the disk writable.
            self._state.save(UpdateState(checked_at=now))
            return UpdateReport(
                tag=latest.tag,
                installed=installed,
                available=available,
                problem="the installer could not be downloaded",
            )

        self._state.save(
            UpdateState(checked_at=now, tag=latest.tag, installer=str(installer))
        )
        return UpdateReport(
            tag=latest.tag,
            installed=installed,
            available=available,
            installer=str(installer),
        )

    def _nothing_newer(self, now: str) -> UpdateReport:
        """Record that we looked, and forget anything we were holding.

        Forgetting matters: the previous state may name an installer for a version that
        is now the running one, and a state file that keeps it would offer an install of
        what is already installed at every launch until something overwrote it.
        """
        self._state.save(UpdateState(checked_at=now))
        return NOTHING_TO_REPORT

    async def _fetch(self, release: Release) -> Path | None:
        if not release.asset_url:
            return None
        name = release.asset_name or f"{release.tag}-setup.exe"
        target = self._cache / _safe_name(name)
        try:
            self._cache.mkdir(parents=True, exist_ok=True)
            await self._downloads.fetch(release.asset_url, target)
        except Exception:  # noqa: BLE001 - a failed download is a silent no
            return None
        return target if target.is_file() else None

    def hand_over(self, report: UpdateReport) -> str:
        """Arm the installer for after this process exits. Returns a problem, or "".

        The caller quits on `""` and must: what has been armed is waiting for exactly
        that. See `infrastructure/handover.py` for why it is a third process rather than
        a child of this one.
        """
        if not report.waiting:
            return "there is no installer to run"
        return self._handover.hand_over(Path(report.installer))


def _safe_name(name: str) -> str:
    """An asset's name reduced to something that is only ever a filename.

    The name comes off a release feed, which is to say off a server, and it is joined to
    a directory and then handed to Windows to execute. A name of `..\\..\\dti.exe` would
    otherwise resolve outside the cache; taking the last component of either separator
    leaves nothing that can traverse.
    """
    cleaned = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return cleaned or "update-setup.exe"
