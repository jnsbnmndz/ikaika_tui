"""Where updates come from, and whether the one on offer is newer.

The toolbox ships as an installer built by `scripts/build-installer.ps1` and
published by `.github/workflows/release.yml`, which tags an official build
`v<x.y.z>+<n>-released` and a debug build `v<x.y.z>+<n>`. This is the other half
of that: given a release feed, decide whether what it is offering is worth
installing.


THE COMPARISON IS ON FOUR NUMBERS, AND THE BUILD NUMBER IS ONE OF THEM

`0.1.0+2` — three parts and a build number that rises globally, across version
names, so `1.1.9+7` is followed by `1.2.0+8` and never by `1.2.0+1`. The name is
compared first because that is what a person reads, and the build number settles
two artefacts of the same name — a rebuild of the same source is a different
artefact, and something has to be able to tell them apart.

A tag written by the release workflow carries the build number, so the four
numbers all come off the tag. A tag that does not - one made by hand, or by an
older version of that workflow, which put only `x.y.z` in the name - leaves the
build unknown. Unknown is NOT zero: zero would make every release of the current
version look older than what is installed and silently suppress a legitimate
update.


AN OFFICIAL BUILD IS THE DEFAULT, AND A PRERELEASE IS OPT-IN

`include_prereleases` is off, so the feed is asked for the latest official
release. The release workflow publishes debug builds with `--prerelease`
precisely so this default cannot offer one.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from company_tui.domain import naming

USER_AGENT = f"{naming.APP_SLUG}-toolbox"
"""What every request from here identifies itself as.

GitHub rejects an API request with no User-Agent, so this is not optional. Here in
the domain rather than in the feed because the downloader sends it too, and it was
building its own out of a capability key - so an installer download announced
itself as "updates-toolbox". Built from APP_SLUG, not APP_TITLE: the title has
spaces in it.
"""

DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_ASSET_PATTERN = "*-setup*.exe"
RELEASED_SUFFIX = "-released"

_VERSION_SHAPE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?")
_REPOSITORY_SHAPE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

UNKNOWN_BUILD = -1
"""No build number was published for this release.

Negative, because 0 is a REAL build number. `x.y.z` with no `+n` is read as
build 0 by anything that defaults it, and the first build of a version is
legitimately `+0` - so a sentinel of 0 cannot tell "nothing was published" from
"build zero was published", and `1.0.0+1` would stop counting as newer than
`1.0.0+0`.

The abstain itself is `newer_than`'s short-circuit rather than this value: an
unknown build number declines to vote instead of voting low, so a release of the
installed version with no build number reads as "the same" rather than "older" -
which would suppress a legitimate update and look exactly like the check not
working.
"""


@dataclass(frozen=True, slots=True)
class UpdateSource:
    """Where to look for a newer build. Every field is editable in Advanced."""

    repository: str = ""
    """`owner/name` on the host. Empty means update checking is not configured -
    which is the shipped default, because this code has no business guessing
    which fork of it somebody is running."""

    api_base: str = DEFAULT_API_BASE
    """The API root. Configurable for GitHub Enterprise, and for pointing a test
    at something local without editing code."""

    include_prereleases: bool = False
    """Offer debug builds too. Off, so `-released` is what a person is offered."""

    asset_pattern: str = DEFAULT_ASSET_PATTERN
    """Which asset of a release is the installer, as a glob."""

    @property
    def configured(self) -> bool:
        return bool(self.repository.strip())

    @property
    def problem(self) -> str:
        """Why this source cannot be used, or `""`.

        Checked before a request rather than after: `owner/name` typed as a full
        URL produces a 404 that reads as "there is no such release" rather than
        "that is not a repository name".
        """
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
        # /releases, then filtered here, rather than /releases/latest: that
        # endpoint hides prereleases entirely, so `include_prereleases` could
        # never be honoured and the two settings would silently disagree.
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
        """Whether this is a release rather than a debug build.

        Both signals have to agree, and they are independent: `prerelease` is
        how it was published and the suffix is how it was tagged. A release
        marked official but tagged without the suffix was published by
        something other than the workflow, and the conservative reading is that
        it is not the official artefact.
        """
        return not self.prerelease and self.tag.endswith(RELEASED_SUFFIX)

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
        """Whether this version supersedes `other`.

        The name decides it whenever the two names differ. Only when they are
        the same does the build number get a say, and an unknown build number
        abstains rather than voting zero - so a release of the installed version
        with no build number published reads as "the same", not as "older".
        """
        if not self.valid or not other.valid:
            return False
        if self._name_parts != other._name_parts:
            return self._name_parts > other._name_parts
        if self.build == UNKNOWN_BUILD or other.build == UNKNOWN_BUILD:
            return False
        return self.build > other.build


INVALID_VERSION = Version(valid=False)


def parse_version(raw: str) -> Version:
    """Reads `v1.2.3+4`, `1.2.3`, or `v1.2.3-released`.

    The suffix and a leading `v` are decoration around the same four numbers, so
    both are tolerated: the caller is handing over whatever a tag or a file said,
    and making each one strip its own would be the same three lines four times.
    """
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
        """Every published release, newest first.

        Raises `ReleaseFeedError` for anything that stops the answer arriving.
        A caller turns that into a sentence; nothing here decides how loudly to
        say it.
        """
        raise NotImplementedError


class ReleaseFeedError(RuntimeError):
    """The feed could not be read. Carries what to tell the person who asked."""


def choose(releases: tuple[Release, ...], source: UpdateSource) -> Release | None:
    """The newest release worth offering, honouring `include_prereleases`.

    The feed's own order is not trusted. GitHub returns releases by creation
    date, and a patch published for an older branch after a newer release would
    then come first - so this sorts by version and only falls back to feed order
    for releases whose tags do not parse.
    """
    usable = [
        release
        for release in releases
        if source.include_prereleases or release.official
    ]
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
