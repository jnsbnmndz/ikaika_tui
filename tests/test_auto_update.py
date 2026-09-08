"""The launch-time update check, and the handover that runs the installer.

Two things here are worth testing hardest, and neither is the happy path.

The THROTTLE, because both ways of getting it wrong are invisible. Too eager and the app
spends a sixty-an-hour budget on somebody restarting it to look at a theme, so the manual
check is rate-limited when they actually want it. Too shy and an update sits unmentioned.

The REMEMBERED STATE, because it is a path this build reads out of a file written by a
previous build and then asks Windows to execute. Every branch that decides to trust it is
in here: the file has to still exist, and what it holds has to still be newer than what
is running - or the badge survives the install it was offering and the app spends every
launch proposing the version it already is.
"""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.app import App
from textual.widgets import Static

from company_tui.application.updates import CACHE_DIRECTORY, UpdateWatch, _safe_name
from company_tui.domain.config import ConfigPort, ConfigScope, Settings
from company_tui.domain.updates import (
    CHECK_INTERVAL_HOURS,
    AssetDownloadPort,
    HandoverPort,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateReport,
    UpdateSource,
    UpdateState,
    UpdateStatePort,
    due,
    parse_version,
)
from company_tui.infrastructure.handover import (
    RELAUNCH,
    SILENT,
    WAITER,
    WindowsHandover,
    quote,
)
from company_tui.infrastructure.update_state import FileUpdateState
from company_tui.presentation.chrome import AppHeader

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _stamp(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


class _Config(ConfigPort):
    """Only `update_source` is reached; the rest is the port's shape."""

    def __init__(self, source: UpdateSource) -> None:
        self._source = source

    def update_source(self) -> UpdateSource:
        return self._source

    def template_source(self, pack: str):
        return None

    def script_source(self, pack: str):
        return None

    def bundle_prefix(self) -> str:
        return ""

    def workspace_root(self) -> str:
        return ""

    def scripts_root(self) -> str:
        return ""

    def script_check(self, pack: str) -> bool:
        return True

    def settings(self) -> Settings:
        raise NotImplementedError

    def location(self, scope: ConfigScope):
        return Path("settings.toml")

    def active_location(self):
        return None

    def save(self, settings: Settings, scope: ConfigScope):
        return Path("settings.toml")


class _Feed(ReleaseFeedPort):
    def __init__(self, releases=(), error=""):
        self._releases = releases
        self._error = error
        self.asked = 0

    async def releases(self, source: UpdateSource):
        self.asked += 1
        if self._error:
            raise ReleaseFeedError(self._error)
        return self._releases


class _Downloads(AssetDownloadPort):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.fetched: list[str] = []

    async def fetch(self, url: str, target: Path) -> int:
        self.fetched.append(url)
        if self.fail:
            raise OSError("the disk is full")
        target.write_bytes(b"installer")
        return 9


class _State(UpdateStatePort):
    def __init__(self, state: UpdateState | None = None) -> None:
        self.state = state if state is not None else UpdateState()
        self.saves: list[UpdateState] = []

    def load(self) -> UpdateState:
        return self.state

    def save(self, state: UpdateState) -> None:
        self.state = state
        self.saves.append(state)


class _Handover(HandoverPort):
    def __init__(self, problem: str = "") -> None:
        self.problem = problem
        self.armed: list[Path] = []

    def hand_over(self, installer: Path) -> str:
        self.armed.append(installer)
        return self.problem


def _scratch_cache(case: unittest.TestCase) -> Path:
    """A real, empty cache directory that goes away with the test.

    NEVER `Path(".")`. That was the placeholder here while the cache was only ever read
    from, and it stopped being harmless the moment `_discard` learned to delete: the
    sweep emptied the repository root, every file of it. `_discard` now refuses any
    directory not named `updates`, and this makes sure no test ever asks it to.
    docs/pitfalls.md 6.3.
    """
    folder = TemporaryDirectory()
    case.addCleanup(folder.cleanup)
    cache = Path(folder.name) / CACHE_DIRECTORY
    cache.mkdir()
    return cache


def _release(tag: str, *, asset: str = "dti-setup.exe", url: str = "https://x/i.exe"):
    return Release(
        tag=tag,
        prerelease=False,
        asset_name=asset,
        asset_url=url,
        asset_size=1024,
    )


class Throttling(unittest.TestCase):
    def test_never_checked_is_due(self):
        self.assertTrue(due(UpdateState(), NOW))

    def test_inside_the_interval_is_not_due(self):
        self.assertFalse(due(UpdateState(checked_at=_stamp(1)), NOW))

    def test_outside_the_interval_is_due(self):
        self.assertTrue(due(UpdateState(checked_at=_stamp(CHECK_INTERVAL_HOURS + 1)), NOW))

    def test_exactly_the_interval_is_due(self):
        # >= rather than >, so a value landing on the boundary asks rather than
        # waiting for a whole further interval.
        self.assertTrue(due(UpdateState(checked_at=_stamp(CHECK_INTERVAL_HOURS)), NOW))

    def test_a_timestamp_in_the_future_is_due(self):
        # A corrected clock, or a file from another machine. Waiting for the calendar
        # to catch up would suppress the check with nothing on screen to say why.
        ahead = (NOW + timedelta(hours=5)).isoformat()
        self.assertTrue(due(UpdateState(checked_at=ahead), NOW))

    def test_an_unreadable_timestamp_is_due(self):
        self.assertTrue(due(UpdateState(checked_at="tuesday"), NOW))

    def test_a_naive_timestamp_is_read_as_utc_rather_than_rejected(self):
        naive = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        self.assertFalse(due(UpdateState(checked_at=naive), NOW))


class Looking(unittest.TestCase):
    def _watch(self, source, feed, *, state=None, downloads=None, handover=None,
               version="0.0.1+1", cache=None):
        return UpdateWatch(
            config=_Config(source),
            feed=feed,
            downloads=downloads or _Downloads(),
            state=state or _State(),
            handover=handover or _Handover(),
            version=version,
            cache=cache if cache is not None else _scratch_cache(self),
        )

    def test_an_unconfigured_source_asks_nothing_and_says_nothing(self):
        # Spelled out, because a bare UpdateSource is CONFIGURED now - it carries
        # DEFAULT_REPOSITORY. Empty is somebody having turned checking off, and it is
        # still the one thing that stops this asking.
        feed = _Feed()
        report = asyncio.run(self._watch(UpdateSource(repository=""), feed).look())
        self.assertEqual(0, feed.asked)
        self.assertFalse(report.waiting)
        self.assertEqual("", report.notice("^"))

    def test_the_shipped_default_does_get_asked(self):
        # The other side of it: out of the box, with nothing configured, the check runs.
        # That is what making the repository a default was for.
        feed = _Feed()
        report = asyncio.run(self._watch(UpdateSource(), feed).look())
        self.assertEqual(1, feed.asked)
        self.assertFalse(report.waiting, "the fake feed published nothing")

    def test_check_on_launch_off_asks_nothing(self):
        feed = _Feed((_release("v9.9.9+9-released"),))
        source = UpdateSource(repository="a/b", check_on_launch=False)
        report = asyncio.run(self._watch(source, feed).look())
        self.assertEqual(0, feed.asked, "the switch has to be read before the request")
        self.assertFalse(report.waiting)

    def test_a_bad_repository_name_asks_nothing_and_stays_silent(self):
        feed = _Feed()
        report = asyncio.run(self._watch(UpdateSource(repository="not a repo"), feed).look())
        self.assertEqual(0, feed.asked)
        self.assertEqual("", report.notice("^"))

    def test_inside_the_interval_nothing_is_asked(self):
        feed = _Feed((_release("v9.9.9+9-released"),))
        state = _State(UpdateState(checked_at=datetime.now(UTC).isoformat()))
        source = UpdateSource(repository="a/b")
        report = asyncio.run(self._watch(source, feed, state=state).look())
        self.assertEqual(0, feed.asked)
        self.assertFalse(report.waiting)

    def test_a_newer_release_is_downloaded_and_remembered(self):
        with TemporaryDirectory() as folder:
            cache = Path(folder) / "updates"
            feed = _Feed((_release("v0.0.2+4-released"),))
            state = _State()
            downloads = _Downloads()
            report = asyncio.run(
                self._watch(
                    UpdateSource(repository="a/b"),
                    feed,
                    state=state,
                    downloads=downloads,
                    cache=cache,
                ).look()
            )
            self.assertTrue(report.waiting)
            self.assertEqual("v0.0.2+4-released", report.tag)
            self.assertEqual(1, len(downloads.fetched))
            self.assertTrue(Path(report.installer).is_file())
            self.assertEqual("^ 0.0.2+4 ready", report.notice("^"))
            self.assertEqual(report.installer, state.state.installer)
            self.assertTrue(state.state.checked_at)

    def test_nothing_newer_records_the_check_and_forgets_the_old_installer(self):
        # THE REGRESSION THIS GUARDS: the app comes back up as the version that
        # installer held. A state file that kept it would offer the install again,
        # every launch, forever.
        feed = _Feed((_release("v0.0.1+1-released"),))
        state = _State(UpdateState(checked_at=_stamp(9), tag="v0.0.1+1", installer="x"))
        report = asyncio.run(
            self._watch(UpdateSource(repository="a/b"), feed, state=state).look()
        )
        self.assertFalse(report.waiting)
        self.assertEqual(1, feed.asked)
        self.assertTrue(state.state.checked_at)
        self.assertEqual("", state.state.tag)
        self.assertEqual("", state.state.installer)

    def test_a_feed_error_is_silent_and_does_not_record_a_check(self):
        # Not recording is the point: an offline launch must not hold the check off
        # for six hours after the network comes back.
        feed = _Feed(error="could not reach api.github.com")
        state = _State()
        report = asyncio.run(
            self._watch(UpdateSource(repository="a/b"), feed, state=state).look()
        )
        self.assertEqual("", report.notice("^"))
        self.assertIn("could not reach", report.problem)
        self.assertEqual([], state.saves)

    def test_a_failed_download_records_the_check_and_offers_nothing(self):
        feed = _Feed((_release("v0.0.2+4-released"),))
        state = _State()
        report = asyncio.run(
            self._watch(
                UpdateSource(repository="a/b"),
                feed,
                state=state,
                downloads=_Downloads(fail=True),
            ).look()
        )
        self.assertFalse(report.waiting)
        self.assertIn("could not be downloaded", report.problem)
        self.assertTrue(state.state.checked_at, "the feed answered; only the disk failed")
        self.assertEqual("", state.state.installer)

    def test_a_release_with_no_asset_offers_nothing(self):
        feed = _Feed((_release("v0.0.2+4-released", asset="", url=""),))
        report = asyncio.run(
            self._watch(UpdateSource(repository="a/b"), feed).look()
        )
        self.assertFalse(report.waiting)


class RememberingWhatWasFetched(unittest.TestCase):
    def _watch(self, feed, state, *, version="0.0.1+1"):
        return UpdateWatch(
            config=_Config(UpdateSource(repository="a/b")),
            feed=feed,
            downloads=_Downloads(),
            state=state,
            handover=_Handover(),
            version=version,
            cache=_scratch_cache(self),
        )

    def test_an_installer_already_here_needs_no_request_at_all(self):
        with TemporaryDirectory() as folder:
            installer = Path(folder) / "dti-setup.exe"
            installer.write_bytes(b"installer")
            feed = _Feed((_release("v9.9.9+9-released"),))
            state = _State(
                UpdateState(
                    checked_at=_stamp(99), tag="v0.0.2+4", installer=str(installer)
                )
            )
            report = asyncio.run(self._watch(feed, state).look())
            self.assertTrue(report.waiting)
            self.assertEqual(0, feed.asked, "the bytes are already here")
            self.assertEqual("^ 0.0.2+4 ready", report.notice("^"))

    def test_a_remembered_installer_that_is_gone_falls_through_to_a_fresh_check(self):
        feed = _Feed((_release("v0.0.3+5-released"),))
        state = _State(
            UpdateState(
                checked_at=_stamp(99), tag="v0.0.2+4", installer="C:/gone/dti-setup.exe"
            )
        )
        with TemporaryDirectory() as folder:
            watch = UpdateWatch(
                config=_Config(UpdateSource(repository="a/b")),
                feed=feed,
                downloads=_Downloads(),
                state=state,
                handover=_Handover(),
                version="0.0.1+1",
                cache=Path(folder),
            )
            report = asyncio.run(watch.look())
        self.assertEqual(1, feed.asked, "%TEMP% cleaners and users both exist")
        self.assertEqual("v0.0.3+5-released", report.tag)

    def test_a_remembered_installer_for_this_very_version_is_dropped(self):
        with TemporaryDirectory() as folder:
            installer = Path(folder) / "dti-setup.exe"
            installer.write_bytes(b"installer")
            feed = _Feed()
            state = _State(
                UpdateState(
                    checked_at=datetime.now(UTC).isoformat(),
                    tag="v0.0.1+1",
                    installer=str(installer),
                )
            )
            # Installed IS what the installer holds - the update already happened.
            report = asyncio.run(self._watch(feed, state, version="0.0.1+1").look())
            self.assertFalse(report.waiting)
            self.assertEqual("", state.state.installer)


class HandingOver(unittest.TestCase):
    def test_nothing_to_run_is_refused_rather_than_armed(self):
        handover = _Handover()
        watch = UpdateWatch(
            config=_Config(UpdateSource()),
            feed=_Feed(),
            downloads=_Downloads(),
            state=_State(),
            handover=handover,
            version="0.0.1+1",
            cache=_scratch_cache(self),
        )
        self.assertIn("no installer", watch.hand_over(UpdateReport()))
        self.assertEqual([], handover.armed)

    def test_an_installer_that_is_waiting_is_armed(self):
        handover = _Handover()
        watch = UpdateWatch(
            config=_Config(UpdateSource()),
            feed=_Feed(),
            downloads=_Downloads(),
            state=_State(),
            handover=handover,
            version="0.0.1+1",
            cache=_scratch_cache(self),
        )
        report = UpdateReport(
            tag="v0.0.2+4",
            available=parse_version("0.0.2+4"),
            installer="C:/cache/dti-setup.exe",
        )
        self.assertEqual("", watch.hand_over(report))
        self.assertEqual([Path("C:/cache/dti-setup.exe")], handover.armed)


class TheWaiterCommand(unittest.TestCase):
    """The one line that decides whether an upgrade corrupts the install.

    It has to wait for THIS process and then start the installer, in that order. The
    installer runs `RMDir /r` over the directory holding the running executable, so a
    command that starts it without waiting is the bug the whole file exists to avoid.
    """

    def _command(self, relaunch: str = "") -> str:
        return WAITER.format(
            pid=4321,
            timeout=120,
            silent=SILENT,
            installer="C:/x/setup.exe",
            relaunch=relaunch,
        )

    def test_it_waits_before_it_starts(self):
        command = self._command()
        self.assertLess(
            command.index("Wait-Process"),
            command.index("Start-Process"),
            "starting the installer before this process exits is the corrupting order",
        )
        self.assertIn("-Id 4321", command)
        self.assertIn("-Timeout 120", command)

    def test_it_installs_silently_and_waits_for_the_installer(self):
        # The whole point of an in-app update: no wizard, and -Wait so what follows
        # happens after the install rather than alongside it.
        command = self._command()
        self.assertIn(f"-ArgumentList '{SILENT}'", command)
        self.assertIn("-Wait", command)

    def test_a_silent_failure_reruns_the_installer_visibly(self):
        # A SILENT FAILURE IS WORSE THAN A WIZARD: the user sees the app close and
        # nothing come back. A non-zero exit runs it again without /S so its own error
        # dialog explains itself.
        command = self._command()
        self.assertIn("$done.ExitCode -ne 0", command)
        visible = command.rindex("Start-Process -FilePath 'C:/x/setup.exe' }")
        self.assertGreater(visible, command.index(SILENT), "the retry must drop /S")

    def test_a_frozen_build_is_restarted_afterwards(self):
        command = self._command(RELAUNCH.format(exe="C:/Programs/dti/dti.exe"))
        self.assertIn("C:/Programs/dti/dti.exe", command)
        self.assertGreater(
            command.index("dti.exe"),
            command.index("setup.exe"),
            "the new build starts after the installer, not before",
        )

    def test_running_from_source_restarts_nothing(self):
        # sys.executable is the interpreter there, and relaunching it would open a bare
        # Python prompt over somebody's terminal.
        self.assertNotIn("elseif", self._command())

    def test_a_quote_in_the_path_cannot_end_the_string(self):
        # Doubling is how a literal quote survives a PowerShell single-quoted string.
        # Unescaped, a path holding one ends the argument and the rest becomes code.
        self.assertEqual("it''s", quote("it's"))

    def test_a_path_with_shell_metacharacters_is_left_alone(self):
        # Single quotes mean no expansion, so `$` and a backtick are literal - and this
        # repository lives under a folder named "GitHub(jnsbnmndz)".
        awkward = "C:/GitHub(jnsbnmndz)/$env/a`b/setup.exe"
        self.assertEqual(awkward, quote(awkward))

    def test_a_missing_installer_is_refused_rather_than_armed(self):
        problem = WindowsHandover().hand_over(Path("C:/nowhere/setup.exe"))
        self.assertTrue(problem, "arming a waiter for a file that is gone quits for nothing")


class AssetNames(unittest.TestCase):
    """The asset name comes off a server and is joined to a directory, then executed."""

    def test_a_traversal_cannot_leave_the_cache(self):
        self.assertEqual("dti.exe", _safe_name("../../dti.exe"))
        self.assertEqual("dti.exe", _safe_name("..\\..\\dti.exe"))

    def test_an_empty_name_still_produces_a_filename(self):
        self.assertEqual("update-setup.exe", _safe_name("   "))

    def test_an_ordinary_name_is_untouched(self):
        self.assertEqual("dti-0.0.2-setup.exe", _safe_name("dti-0.0.2-setup.exe"))


class TheStateFile(unittest.TestCase):
    def test_it_round_trips(self):
        with TemporaryDirectory() as folder:
            store = FileUpdateState(Path(folder) / "updates.json")
            store.save(UpdateState(checked_at="2026-09-08T12:00:00+00:00", tag="v1", installer="p"))
            back = store.load()
            self.assertEqual("2026-09-08T12:00:00+00:00", back.checked_at)
            self.assertEqual("v1", back.tag)
            self.assertEqual("p", back.installer)

    def test_a_missing_file_is_an_empty_state(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(UpdateState(), FileUpdateState(Path(folder) / "no.json").load())

    def test_rubbish_is_an_empty_state_rather_than_a_crash(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "updates.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(UpdateState(), FileUpdateState(path).load())

    def test_a_future_version_is_not_guessed_at(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "updates.json"
            path.write_text('{"version": 99, "installer": "C:/evil.exe"}', encoding="utf-8")
            self.assertEqual(UpdateState(), FileUpdateState(path).load())


class SweepingTheCache(unittest.TestCase):
    """Thirty megabytes per version, and nothing else is in a position to remove it.

    The installer never touches the user's home; the uninstaller must not, because that
    directory also holds settings and the script repositories somebody edits. So the only
    thing that can tell a stale installer from the one being offered is the check that
    knows which version is running.
    """

    def _watch(self, feed, state, cache, *, version="0.0.1+1"):
        return UpdateWatch(
        config=_Config(UpdateSource(repository="a/b")),
        feed=feed,
        downloads=_Downloads(),
        state=state,
        handover=_Handover(),
        version=version,
        cache=cache,
        )

    def test_the_installer_for_the_running_version_is_deleted(self):
        # THE RESIDUE THIS EXISTS FOR: the update happened, so this file produced the
        # version doing the asking. Nothing else will ever come back for it.
        cache = _scratch_cache(self)
        installer = cache / "dti-0.0.1-setup.exe"
        installer.write_bytes(b"installer")
        state = _State(
            UpdateState(
                checked_at=datetime.now(UTC).isoformat(),
                tag="v0.0.1+1",
                installer=str(installer),
            )
        )
        asyncio.run(self._watch(_Feed(), state, cache, version="0.0.1+1").look())
        self.assertFalse(installer.exists(), "the update happened; this is rubbish")

    def test_a_part_file_from_an_interrupted_download_goes_too(self):
        cache = _scratch_cache(self)
        partial = cache / "dti-setup.exe.part"
        partial.write_bytes(b"half")
        state = _State(UpdateState(checked_at=_stamp(9)))
        asyncio.run(self._watch(_Feed(), state, cache).look())
        self.assertFalse(partial.exists())

    def test_a_fresh_download_survives_its_own_sweep(self):
        # The sweep runs after a successful download, to clear the PREVIOUS version's
        # installer. Without the exception it would delete what it just fetched.
        cache = _scratch_cache(self)
        stale = cache / "dti-0.0.1-setup.exe"
        stale.write_bytes(b"old")
        feed = _Feed((_release("v0.0.2+4-released"),))
        report = asyncio.run(self._watch(feed, _State(), cache).look())
        self.assertTrue(report.waiting)
        self.assertTrue(Path(report.installer).is_file(), "it must keep what it fetched")
        self.assertFalse(stale.exists(), "and drop what it replaced")

    def test_a_directory_in_the_cache_is_left_alone(self):
        # "Remove everything under a path built from configuration" is not a line worth
        # having, so the sweep skips directories rather than recursing.
        cache = _scratch_cache(self)
        nested = cache / "somebody-elses-folder"
        nested.mkdir()
        (nested / "keep.txt").write_text("keep", encoding="utf-8")
        state = _State(UpdateState(checked_at=_stamp(9)))
        asyncio.run(self._watch(_Feed(), state, cache).look())
        self.assertTrue((nested / "keep.txt").exists())

    def test_a_missing_cache_directory_is_not_an_error(self):
        # Named `updates`, so the name guard is not what makes this pass.
        cache = _scratch_cache(self) / "gone" / CACHE_DIRECTORY
        state = _State(UpdateState(checked_at=_stamp(9)))
        asyncio.run(self._watch(_Feed(), state, cache).look())
        self.assertFalse(cache.exists())

    def test_an_installer_still_being_offered_is_not_swept(self):
        # Nothing newer was found, but the remembered installer IS newer than what is
        # running — so the remembered path short-circuits before any sweep.
        cache = _scratch_cache(self)
        installer = cache / "dti-0.0.2-setup.exe"
        installer.write_bytes(b"installer")
        state = _State(
            UpdateState(
                checked_at=datetime.now(UTC).isoformat(),
                tag="v0.0.2+4",
                installer=str(installer),
            )
        )
        report = asyncio.run(self._watch(_Feed(), state, cache).look())
        self.assertTrue(report.waiting)
        self.assertTrue(installer.exists(), "it is the thing being offered")


class TheSweepDoesNotTrustItsPath(unittest.TestCase):
    """The regression that ate this repository's root, twice.

    `_discard` is a loop that deletes files in a directory handed to the constructor. A
    test passed `Path(".")` as a placeholder - harmless when it was written, because the
    cache was only ever read from - and the sweep emptied every file at the repository
    root. `.gitignore` with it, which then unmasked the signing keys.

    Both guards are asserted here, either of which would have prevented it. The tests
    above no longer point the cache anywhere real, but "no test does that any more" is a
    promise about the tests; this is a property of the code.
    """

    def _watch(self, cache: Path) -> UpdateWatch:
        return UpdateWatch(
            config=_Config(UpdateSource(repository="a/b")),
            feed=_Feed(),
            downloads=_Downloads(),
            state=_State(),
            handover=_Handover(),
            version="0.0.1+1",
            cache=cache,
        )

    def test_a_directory_that_is_not_the_cache_is_left_completely_alone(self):
        with TemporaryDirectory() as folder:
            # Shaped like the thing that actually got deleted.
            root = Path(folder)
            (root / "VERSION").write_text("0.0.1+1", encoding="utf-8")
            (root / ".gitignore").write_text("certs/", encoding="utf-8")
            (root / "dti-setup.exe").write_bytes(b"even this")

            self._watch(root)._discard()

            self.assertTrue((root / "VERSION").exists())
            self.assertTrue((root / ".gitignore").exists())
            self.assertTrue(
                (root / "dti-setup.exe").exists(),
                "the name of the directory decides it, before the name of the file",
            )

    def test_inside_the_cache_only_installers_go(self):
        with TemporaryDirectory() as folder:
            cache = Path(folder) / CACHE_DIRECTORY
            cache.mkdir()
            (cache / "dti-setup.exe").write_bytes(b"installer")
            (cache / "dti-setup.exe.part").write_bytes(b"half")
            (cache / "notes.txt").write_text("mine", encoding="utf-8")

            self._watch(cache)._discard()

            self.assertFalse((cache / "dti-setup.exe").exists())
            self.assertFalse((cache / "dti-setup.exe.part").exists())
            self.assertTrue(
                (cache / "notes.txt").exists(),
                "the suffix guard is the second half, and costs nothing",
            )


class TheBadge(unittest.IsolatedAsyncioTestCase):
    """The header, mounted for real rather than reasoned about.

    Only the header: booting `TuiConsole` would start the menu loop, and the thing
    worth checking here is that the badge reads the notice off the app the way the
    window notice does — compose-time as well as on change, because every step of a
    workflow composes a fresh header and an update found once at launch would
    otherwise vanish at the first menu.

    Read back with `render()`, not `renderable`, which does not exist on this
    version of Textual — docs/pitfalls.md 5.2, walked into once more while writing
    this very test.
    """

    class _App(App):
        def __init__(self, notice: str = "") -> None:
            super().__init__()
            self.update_notice = notice
            self.window_notice = ""
            self.runs_summary = ""
            self.workspace_label = "here"

        def compose(self):
            yield AppHeader()

    async def test_a_notice_present_at_compose_time_is_shown(self):
        app = self._App("^ 0.0.2+4 ready")
        async with app.run_test():
            badge = app.query_one("#header-update", Static)
            self.assertIn("0.0.2+4", str(badge.render()))
            self.assertIn("Ctrl+U", str(badge.render()))
            self.assertFalse(badge.has_class("-empty"))

    async def test_no_notice_is_no_badge(self):
        app = self._App()
        async with app.run_test():
            badge = app.query_one("#header-update", Static)
            self.assertTrue(badge.has_class("-empty"))
            self.assertEqual("", str(badge.render()))

    async def test_show_update_puts_one_up_and_takes_it_away_again(self):
        app = self._App()
        async with app.run_test():
            header = app.query_one(AppHeader)
            header.show_update("^ 1.0.0+9 ready")
            badge = app.query_one("#header-update", Static)
            self.assertFalse(badge.has_class("-empty"))
            self.assertIn("1.0.0+9", str(badge.render()))
            header.show_update("")
            self.assertTrue(badge.has_class("-empty"))


if __name__ == "__main__":
    unittest.main()
