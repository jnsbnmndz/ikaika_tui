"""The update check the app makes for itself as it starts."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from company_tui.domain.config import ConfigPort
from company_tui.domain.updates import (
    BUILD_UNKNOWN,
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

SWEEPABLE = frozenset({".exe", ".part"})
"""The only suffixes `_discard` will delete."""

CACHE_DIRECTORY = "updates"
"""Where a fetched installer waits, under the toolbox's own store directory."""

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
        build: str = BUILD_UNKNOWN,
    ) -> None:
        self._config = config
        self._build = build
        self._feed = feed
        self._downloads = downloads
        self._state = state
        self._handover = handover
        self._version = version
        self._cache = cache

    async def look(self) -> UpdateReport:
        """What is waiting, or nothing. Never raises."""
        try:
            return await self._look()
        except Exception as error:  # noqa: BLE001 - see the docstring
            return UpdateReport(problem=str(error))

    async def _look(self) -> UpdateReport:
        source = self._config.update_source()
        if not source.check_on_launch:
            return NOTHING_TO_REPORT
        if not source.configured or source.problem:
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
        """The answer from a previous launch, when it is still the answer."""
        if not state.fetched:
            return None
        if not Release(tag=state.tag).replaces(self._build):
            return None
        installer = Path(state.installer)
        if not installer.is_file():
            return None
        available = parse_version(state.tag)
        if not available.newer_than(installed):
            self._state.save(UpdateState(checked_at=state.checked_at))
            self._discard()
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
            return UpdateReport(problem=str(error))

        now = datetime.now(UTC).isoformat()
        latest = choose(releases, source, self._build)
        if latest is None:
            return self._nothing_newer(now)

        available = latest.version
        if not available.valid or not available.newer_than(installed):
            return self._nothing_newer(now)

        installer = await self._fetch(latest)
        if installer is None:
            self._state.save(UpdateState(checked_at=now))
            return UpdateReport(
                tag=latest.tag,
                installed=installed,
                available=available,
                problem="the installer could not be downloaded",
            )

        self._discard(keep=installer)
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
        """Record that we looked, and forget anything we were holding."""
        self._state.save(UpdateState(checked_at=now))
        self._discard()
        return NOTHING_TO_REPORT

    def _discard(self, keep: Path | None = None) -> None:
        """Empty the download cache, except for a file being kept."""
        if self._cache.name != CACHE_DIRECTORY or not self._cache.is_dir():
            return
        for entry in self._cache.iterdir():
            if not entry.is_file() or entry.suffix not in SWEEPABLE:
                continue
            if keep is not None and entry == keep:
                continue
            with suppress(OSError):
                entry.unlink()

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

    def arm(self, installer: Path) -> str:
        """Arm the installer for a path, without a report around it."""
        return self._handover.hand_over(installer)

    def hand_over(self, report: UpdateReport) -> str:
        """Arm the installer for after this process exits. Returns a problem, or ""."""
        if not report.waiting:
            return "there is no installer to run"
        return self.arm(Path(report.installer))


def _safe_name(name: str) -> str:
    """An asset's name reduced to something that is only ever a filename."""
    cleaned = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return cleaned or "update-setup.exe"
