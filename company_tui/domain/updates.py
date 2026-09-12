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
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath

from company_tui.domain import naming

USER_AGENT = f"{naming.APP_SLUG}-toolbox"
"""What every request from here identifies itself as.

GitHub rejects an API request with no User-Agent, so this is not optional. Here in
the domain rather than in the feed because the downloader sends it too, and it was
building its own out of a capability key - so an installer download announced
itself as "updates-toolbox". Built from APP_SLUG, not APP_TITLE: the title has
spaces in it.
"""

DEFAULT_REPOSITORY = "jnsbnmndz/ikaika_tui"
"""Where this build's own releases are published.

It was empty, on the grounds that this code has no business guessing which fork of
itself somebody is running. Named now, because the alternative it was protecting
turned out to be worse: a toolbox that ships with update checking switched off is
one where the feature exists and does nothing until somebody finds the screen that
turns it on - and the people running this are the people releasing it.

A fork changes one line in Advanced, which is a smaller cost than everybody else
having to. Being wrong here is inert rather than harmful: the check reads a public
release feed and offers an installer, and the offer is a badge nobody has to press.

Empty is still off, and still means off. See `infrastructure/config.py` for the one
distinction that makes both true - a repository absent from the settings file gets
this default, and a repository written there as empty stays empty.
"""

DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_ASSET_PATTERN = "*-setup*.exe"

CHANNEL_OFFICIAL = "official"
CHANNEL_PRERELEASE = "prerelease"
CHANNEL_ANY = "any"
CHANNELS = (CHANNEL_OFFICIAL, CHANNEL_PRERELEASE, CHANNEL_ANY)
"""Which releases are worth offering. Three answers, not two.

This was a boolean, `include_prereleases`, which could only say "official" or "official
and prereleases too". It had no way to say the thing somebody testing debug builds
actually wants: the newest PRERELEASE, and never mind the official line.

The distinction is not academic here. Debug builds are cut far more often than official
ones and carry higher build numbers, so `any` usually lands on a prerelease by accident -
until the day an official release is newer, and then it silently switches channel. A
person tracking prereleases wants the prerelease line whatever the official one is doing.

  official     signed with the release certificate, tagged -released. The default.
  prerelease   debug builds only. Never offers an official release, even a newer one.
  any          whichever is newest, of either kind.
"""

CHANNEL_LABELS = {
    CHANNEL_OFFICIAL: "official releases only",
    CHANNEL_PRERELEASE: "prereleases only (debug builds)",
    CHANNEL_ANY: "whichever is newest",
}
"""What each channel is called on a form and in a report. Here rather than in the
interface, because the manual card, the Advanced form and the settings summary all name
them and three copies of a word is two too many."""
RELEASED_SUFFIX = "-released"

BUILD_RELEASE = "release"
BUILD_DEBUG = "debug"
BUILD_UNKNOWN = ""
CHANNEL_FOR_BUILD = {BUILD_RELEASE: CHANNEL_OFFICIAL, BUILD_DEBUG: CHANNEL_PRERELEASE}
"""Which line a build belongs to, and which channel is that line.

A debug build and a release build are two separate INSTALLS by design - own
directory, own uninstall entry, own command (`docs/pitfalls.md` and the
`INSTALL_SLUG` note in CLAUDE.md). That is what stops a build somebody is testing
from replacing the copy they work in, and it is also why an update has a line: a
debug installer CANNOT update a release install, because it does not touch it. It
installs beside it.

Offered anyway, that is not a bad update, it is a silent no-op with a badge that
never clears: the installer runs, reports success, puts a second app on the
machine, and the running build is the version it always was - so the same offer
comes back at the next launch, and the next. That happened, for days, and looked
like the updater was broken rather than like it was working on somebody else's
install.

So the line is settled by what is RUNNING, not by a setting. `BUILD_UNKNOWN` is
the source checkout, where nothing was installed and there is nothing to replace;
there the channel has the last word, as it always did.
"""

DEBUG_SUFFIX = "-debug"
"""What the debug build's command is called, against `naming.COMMAND`.

The NSI writes `${APP_NAME}-debug.exe` for a debug build so both can sit on PATH
without one shadowing the other, which makes the name this process was started
under the one thing on the machine that says which line it is. Read from the exe
rather than from the registry: the registry says what an INSTALLER did, and the
question here is what is running.
"""


def build_kind(command: str) -> str:
    """Which line the running build belongs to, from the name it runs under.

    Empty in, empty out: `sys.executable` is the interpreter under
    `python -m company_tui`, and an interpreter is not a build of anything.
    """
    stem = PurePath(command).stem.lower() if command else ""
    if not stem:
        return BUILD_UNKNOWN
    return BUILD_DEBUG if stem.endswith(DEBUG_SUFFIX) else BUILD_RELEASE

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

    repository: str = DEFAULT_REPOSITORY
    """`owner/name` on the host. Empty means update checking is off.

    Defaulted rather than empty - see `DEFAULT_REPOSITORY`. This is also what
    Advanced's "reset to defaults" restores, since that writes a bare
    `UpdateSource()`, so the default here and the default the interface offers
    cannot drift apart."""

    api_base: str = DEFAULT_API_BASE
    """The API root. Configurable for GitHub Enterprise, and for pointing a test
    at something local without editing code."""

    channel: str = CHANNEL_OFFICIAL
    """Which releases to offer: see `CHANNELS`. Official by default, so a signed
    build is what somebody is offered unless they asked otherwise."""

    asset_pattern: str = DEFAULT_ASSET_PATTERN
    """Which asset of a release is the installer, as a glob."""

    check_on_launch: bool = True
    """Ask the feed as the app starts, as well as when somebody asks.

    On by default and harmless when nothing else is set: `configured` is false
    until a repository is named, so the shipped default checks nothing. What
    this switch is for is the person who has configured a repository and does
    not want their terminal talking to it - and it is a setting rather than a
    build-time constant because that is a preference, not a property of the
    program.
    """

    @property
    def include_prereleases(self) -> bool:
        """Whether a prerelease can be offered at all.

        Derived rather than stored, because it is the question the older settings key
        asked and the answer is now a property of the channel. Kept so nothing that only
        wants the yes/no - a summary line, an exported document - has to learn about
        three values it does not use.
        """
        return self.channel != CHANNEL_OFFICIAL

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
    def kind(self) -> str:
        """Which line this release belongs to. See `CHANNEL_FOR_BUILD`."""
        return BUILD_RELEASE if self.official else BUILD_DEBUG

    def replaces(self, build: str) -> bool:
        """Whether installing this would replace a build of that kind.

        True for `BUILD_UNKNOWN`, which is the source checkout: there is no
        install to replace there, so nothing is ruled out on those grounds.
        """
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


def wanted(release: Release, channel: str, build: str = BUILD_UNKNOWN) -> bool:
    """Whether this release is worth offering to a build of that kind.

    THE LINE COMES FIRST, AND THE CHANNEL CANNOT OVERRULE IT

    A release that cannot replace this build is never offered, whatever the
    channel says - see `CHANNEL_FOR_BUILD` for what that cost when it could. And
    once the line is known there is nothing left for the channel to choose: an
    installed build has exactly one line that can replace it, so `official`,
    `prerelease` and `any` all mean the same thing to it. The setting is not
    ignored so much as answered; what it is still for is the source checkout,
    where nothing was installed, nothing can be replaced, and the question is
    genuinely open.

    `prerelease` asks how it was PUBLISHED and `official` asks that plus how it was
    tagged, which is why the two are not each other's negation: a release marked neither
    - published as a full release but tagged without `-released` - was made by something
    other than the workflow, and belongs to `any` alone. Being conservative there is the
    same reading `Release.official` already takes.
    """
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
    """The newest release worth offering on this source's channel.

    The feed's own order is not trusted. GitHub returns releases by creation
    date, and a patch published for an older branch after a newer release would
    then come first - so this sorts by version and only falls back to feed order
    for releases whose tags do not parse.
    """
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


# ---------------------------------------------------------------- the launch check
#
# The manual capability is somebody asking. This is the app asking on their behalf as it
# starts, and the difference is entirely in what it is allowed to cost: a check nobody
# asked for may not delay the first paint, may not report its own plumbing, and may not
# ask GitHub sixty times an hour because somebody is restarting the app to test a theme.
#
# So there is a memory. `UpdateState` is what the last check found, written down between
# launches: when it looked, which tag it found, and where the installer it fetched is
# sitting. A launch with a downloaded installer already recorded touches the network not
# at all - the badge comes straight back out of the file.


CHECK_INTERVAL_HOURS = 6
"""How stale the last answer has to be before the feed is asked again.

Not per launch. Unauthenticated GitHub allows sixty requests an hour per address, and an
app that asks on every start spends that budget on a person opening a terminal - which is
the same person who then finds the manual check rate-limited when they actually want it.

Six hours rather than a day because the thing being offered is a build of this toolbox,
and the people running it are the people releasing it.
"""

UPDATE_NOTICE = "{mark} {version} ready"
"""The badge, when an installer is sitting on disk waiting to be run.

`ready` rather than `available`: by the time this is shown the bytes are already here,
and telling somebody an update is available when it is actually downloaded understates
what pressing the key will do. The mark is passed in rather than written here - the
interface owns its glyphs, and this module has no business holding one.
"""


@dataclass(frozen=True, slots=True)
class UpdateState:
    """What the last launch check found, as it survives a restart.

    Deliberately four strings and nothing else: no `Release`, no `Version`, nothing that
    would have to be reconstructed from a file written by an older build. What cannot be
    rebuilt from the tag and the path is not worth keeping.
    """

    checked_at: str = ""
    """When the feed last answered, ISO 8601. Empty means it never has."""

    tag: str = ""
    """The tag of the newer release that was found, or empty for none."""

    installer: str = ""
    """Where the installer for that tag was downloaded to, or empty."""

    @property
    def fetched(self) -> bool:
        """Whether this state names an installer that was actually downloaded.

        Whether that file is still THERE is a question for the filesystem, and so is
        asked by the thing that has one.
        """
        return bool(self.tag and self.installer)


def due(
    state: UpdateState,
    now: datetime,
    interval_hours: int = CHECK_INTERVAL_HOURS,
) -> bool:
    """Whether enough time has passed to ask the feed again.

    `now` is passed in rather than read here, so the whole throttle is testable without
    waiting six hours or monkeypatching a clock.

    A timestamp in the FUTURE means asking again. That is not paranoia: the file is
    written on one machine and read after the clock has been corrected, or after a
    timezone-naive value from an older build has been read back as UTC. Waiting for the
    calendar to catch up would suppress the check for hours with nothing on screen to say
    why - and asking once more costs one request.
    """
    if not state.checked_at:
        return True
    try:
        last = datetime.fromisoformat(state.checked_at)
    except ValueError:
        # Unreadable is the same as never, for the same reason the store swallows a
        # broken file: the cost is one extra request, and the alternative is an update
        # check that stays off until somebody deletes a file they do not know about.
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last > now:
        return True
    return (now - last) >= timedelta(hours=interval_hours)


@dataclass(frozen=True, slots=True)
class UpdateReport:
    """What the launch check concluded. Empty when there is nothing to say.

    `problem` is filled in for the benefit of anything that wants to explain itself -
    Doctor, a log, a future screen - and is NOT what the badge shows. A check nobody
    asked for reports a result or nothing at all; a courtesy that narrates its own
    plumbing is noise, which is the same rule the script-store version check follows.
    """

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
        """Download `url` to `target`, returning the bytes written.

        Raises `OSError` or `urllib.error.URLError` for anything that stops it. The
        target must not exist as a partial file afterwards - a half-downloaded installer
        that looks finished is the one failure this must not have.
        """
        raise NotImplementedError


class UpdateStatePort(ABC):
    """Remembers what the last check found, between launches."""

    @abstractmethod
    def load(self) -> UpdateState:
        """The last state, or an empty one. Never raises: unreadable is empty."""
        raise NotImplementedError

    @abstractmethod
    def save(self, state: UpdateState) -> None:
        """Write it down. Never raises: a state that cannot be saved costs one
        redundant check next launch, which is not worth taking a launch down for."""
        raise NotImplementedError


class HandoverPort(ABC):
    """Starts an installer in such a way that it runs AFTER this process is gone.

    The whole feature is this one method being correct. The installer removes the
    directory it is replacing, and that directory holds the executable running this
    code - so an installer started as a child of a process that is still alive reaches
    its first `File` instruction, finds the exe locked, and stops with a file-in-use
    error over a half-removed install.

    Which is why this is not `ProcessRunner`. Every method there is about a subprocess
    whose output and exit code are the point, and whose lifetime is bounded by the run
    that started it. This one is the opposite on both counts: nothing it prints is ever
    read, and it must outlive its parent deliberately.
    """

    @abstractmethod
    def hand_over(self, installer: Path) -> str:
        """Arrange for `installer` to run once this process has exited.

        Returns a problem to report, or `""` when the handover is armed. The caller
        quits immediately afterwards - and must, because what has been armed is
        something waiting for exactly that.
        """
        raise NotImplementedError
