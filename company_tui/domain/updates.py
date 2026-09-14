"""Where updates come from, and whether the one on offer is newer."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath

from company_tui.domain import naming

USER_AGENT = f"{naming.APP_SLUG}-toolbox"
"""What every request from here identifies itself as."""

DEFAULT_REPOSITORY = "jnsbnmndz/ikaika_tui"
"""Where this build's own releases are published."""

DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_ASSET_PATTERN = "*-setup*.exe"

CHANNEL_OFFICIAL = "official"
CHANNEL_PRERELEASE = "prerelease"
CHANNEL_ANY = "any"
CHANNELS = (CHANNEL_OFFICIAL, CHANNEL_PRERELEASE, CHANNEL_ANY)
"""Which releases are worth offering. Three answers, not two."""

CHANNEL_LABELS = {
    CHANNEL_OFFICIAL: "official releases only",
    CHANNEL_PRERELEASE: "prereleases only (debug builds)",
    CHANNEL_ANY: "whichever is newest",
}
"""What each channel is called on a form and in a report. Here rather than in the."""
RELEASED_SUFFIX = "-released"

BUILD_RELEASE = "release"
BUILD_DEBUG = "debug"
BUILD_UNKNOWN = ""
CHANNEL_FOR_BUILD = {BUILD_RELEASE: CHANNEL_OFFICIAL, BUILD_DEBUG: CHANNEL_PRERELEASE}
"""Which line a build belongs to, and which channel is that line."""

DEBUG_SUFFIX = "-debug"
"""What the debug build's command is called, against `naming.COMMAND`."""

def build_kind(command: str) -> str:
    """Which line the running build belongs to, from the name it runs under."""
    stem = PurePath(command).stem.lower() if command else ""
    if not stem:
        return BUILD_UNKNOWN
    return BUILD_DEBUG if stem.endswith(DEBUG_SUFFIX) else BUILD_RELEASE

_VERSION_SHAPE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?")
_REPOSITORY_SHAPE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

UNKNOWN_BUILD = -1
"""No build number was published for this release."""

@dataclass(frozen=True, slots=True)
class UpdateSource:
    """Where to look for a newer build. Every field is editable in Advanced."""

    repository: str = DEFAULT_REPOSITORY
    """`owner/name` on the host. Empty means update checking is off."""

    api_base: str = DEFAULT_API_BASE
    """The API root. Configurable for GitHub Enterprise, and for pointing a test."""

    channel: str = CHANNEL_OFFICIAL
    """Which releases to offer: see `CHANNELS`. Official by default, so a signed."""

    asset_pattern: str = DEFAULT_ASSET_PATTERN
    """Which asset of a release is the installer, as a glob."""

    check_on_launch: bool = True
    """Ask the feed as the app starts, as well as when somebody asks."""

    @property
    def include_prereleases(self) -> bool:
        """Whether a prerelease can be offered at all."""
        return self.channel != CHANNEL_OFFICIAL

    @property
    def configured(self) -> bool:
        return bool(self.repository.strip())

    @property
    def problem(self) -> str:
        """Why this source cannot be used, or `""`."""
        repository = self.repository.strip()
        if not repository:
            return "no repository is set"
        if not _REPOSITORY_SHAPE.match(repository):
            return f"'{repository}' is not owner/name"
        if not self.api_base.strip().startswith(("http://", "https://")):
            return f"'{self.api_base}' is not an http or https URL"
        return ""

    @property
    def releases_url(self) -> str:
        base = self.api_base.strip().rstrip("/")
        repository = self.repository.strip().strip("/")
        return f"{base}/repos/{repository}/releases"


@dataclass(frozen=True, slots=True)
class Release:
    """One published release, as much of it as matters here."""

    tag: str
    name: str = ""
    prerelease: bool = False
    notes: str = ""
    page_url: str = ""
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0

    @property
    def official(self) -> bool:
        """Whether this is a release rather than a debug build."""
        return not self.prerelease and self.tag.endswith(RELEASED_SUFFIX)

    @property
    def kind(self) -> str:
        """Which line this release belongs to. See `CHANNEL_FOR_BUILD`."""
        return BUILD_RELEASE if self.official else BUILD_DEBUG

    def replaces(self, build: str) -> bool:
        """Whether installing this would replace a build of that kind."""
        return not build or self.kind == build

    @property
    def version(self) -> "Version":
        return parse_version(self.tag)


@dataclass(frozen=True, slots=True)
class Version:
    """`x.y.z+n`, comparable. `build` may be `UNKNOWN_BUILD`."""

    major: int = 0
    minor: int = 0
    patch: int = 0
    build: int = UNKNOWN_BUILD
    valid: bool = True

    @property
    def name(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def text(self) -> str:
        if self.build == UNKNOWN_BUILD:
            return self.name
        return f"{self.name}+{self.build}"

    @property
    def _name_parts(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def newer_than(self, other: "Version") -> bool:
        """Whether this version supersedes `other`."""
        if not self.valid or not other.valid:
            return False
        if self._name_parts != other._name_parts:
            return self._name_parts > other._name_parts
        if self.build == UNKNOWN_BUILD or other.build == UNKNOWN_BUILD:
            return False
        return self.build > other.build


INVALID_VERSION = Version(valid=False)


def parse_version(raw: str) -> Version:
    """Reads `v1.2.3+4`, `1.2.3`, or `v1.2.3-released`."""
    match = _VERSION_SHAPE.match(str(raw).strip())
    if not match:
        return INVALID_VERSION
    return Version(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        build=int(match.group(4)) if match.group(4) else UNKNOWN_BUILD,
    )


@dataclass(frozen=True, slots=True)
class UpdateOutcome:
    """What a check found. Reported whether or not there is anything to install."""

    ok: bool
    message: str
    installed: Version = INVALID_VERSION
    available: Version = INVALID_VERSION
    release: Release | None = None
    considered: tuple[Release, ...] = field(default_factory=tuple)

    @property
    def update_available(self) -> bool:
        return self.ok and self.release is not None and self.available.newer_than(
            self.installed
        )


class ReleaseFeedPort(ABC):
    """Fetches published releases. A port, so a check is testable without a network."""

    @abstractmethod
    async def releases(self, source: UpdateSource) -> tuple[Release, ...]:
        """Every published release, newest first."""
        raise NotImplementedError


class ReleaseFeedError(RuntimeError):
    """The feed could not be read. Carries what to tell the person who asked."""

def wanted(release: Release, channel: str, build: str = BUILD_UNKNOWN) -> bool:
    """Whether this release is worth offering to a build of that kind."""
    if not release.replaces(build):
        return False
    if build:
        return True
    if channel == CHANNEL_ANY:
        return True
    if channel == CHANNEL_PRERELEASE:
        return release.prerelease
    return release.official


def choose(
    releases: tuple[Release, ...], source: UpdateSource, build: str = BUILD_UNKNOWN
) -> Release | None:
    """The newest release worth offering on this source's channel."""
    usable = [release for release in releases if wanted(release, source.channel, build)]
    if not usable:
        return None
    parsed = [release for release in usable if release.version.valid]
    if not parsed:
        return usable[0]
    return max(
        parsed,
        key=lambda release: (
            release.version.major,
            release.version.minor,
            release.version.patch,
            release.version.build,
        ),
    )


CHECK_INTERVAL_HOURS = 6
"""How stale the last answer has to be before the feed is asked again."""

UPDATE_NOTICE = "{mark} {version} ready"
"""The badge, when an installer is sitting on disk waiting to be run."""

@dataclass(frozen=True, slots=True)
class UpdateState:
    """What the last launch check found, as it survives a restart."""

    checked_at: str = ""
    """When the feed last answered, ISO 8601. Empty means it never has."""

    tag: str = ""
    """The tag of the newer release that was found, or empty for none."""

    installer: str = ""
    """Where the installer for that tag was downloaded to, or empty."""

    @property
    def fetched(self) -> bool:
        """Whether this state names an installer that was actually downloaded."""
        return bool(self.tag and self.installer)


def due(
    state: UpdateState,
    now: datetime,
    interval_hours: int = CHECK_INTERVAL_HOURS,
) -> bool:
    """Whether enough time has passed to ask the feed again."""
    if not state.checked_at:
        return True
    try:
        last = datetime.fromisoformat(state.checked_at)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last > now:
        return True
    return (now - last) >= timedelta(hours=interval_hours)


@dataclass(frozen=True, slots=True)
class UpdateReport:
    """What the launch check concluded. Empty when there is nothing to say."""

    tag: str = ""
    installed: "Version" = INVALID_VERSION
    available: "Version" = INVALID_VERSION
    installer: str = ""
    problem: str = ""

    @property
    def waiting(self) -> bool:
        """Whether there is an installer here, newer than this build, ready to run."""
        return bool(self.tag and self.installer)

    def notice(self, mark: str) -> str:
        """The badge text, or empty. `mark` is the interface's glyph."""
        if not self.waiting:
            return ""
        return UPDATE_NOTICE.format(mark=mark, version=self.available.text or self.tag)


NOTHING_TO_REPORT = UpdateReport()


class AssetDownloadPort(ABC):
    """Fetches a release asset to a path. A port, so nothing above it holds a socket."""

    @abstractmethod
    async def fetch(self, url: str, target: Path) -> int:
        """Download `url` to `target`, returning the bytes written."""
        raise NotImplementedError


class UpdateStatePort(ABC):
    """Remembers what the last check found, between launches."""

    @abstractmethod
    def load(self) -> UpdateState:
        """The last state, or an empty one. Never raises: unreadable is empty."""
        raise NotImplementedError

    @abstractmethod
    def save(self, state: UpdateState) -> None:
        """Write it down. Never raises: a state that cannot be saved costs one."""
        raise NotImplementedError


class HandoverPort(ABC):
    """Starts an installer in such a way that it runs AFTER this process is gone."""

    @abstractmethod
    def hand_over(self, installer: Path) -> str:
        """Arrange for `installer` to run once this process has exited."""
        raise NotImplementedError
