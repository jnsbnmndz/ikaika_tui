"""The update check: version comparison, which release gets offered, and reporting."""

import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from company_tui.capabilities.updates import (
    INSTALLER_KEY,
    LOCAL_KEY,
    UpdatesCapability,
)
from company_tui.domain import naming
from company_tui.domain.config import ConfigPort, ConfigScope, Settings
from company_tui.domain.updates import (
    BUILD_DEBUG,
    BUILD_RELEASE,
    BUILD_UNKNOWN,
    CHANNEL_ANY,
    CHANNEL_OFFICIAL,
    CHANNEL_PRERELEASE,
    DEFAULT_API_BASE,
    DEFAULT_REPOSITORY,
    UNKNOWN_BUILD,
    AssetDownloadPort,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateSource,
    build_kind,
    choose,
    parse_version,
)
from company_tui.infrastructure.config import FileConfig


class ParsingVersions(unittest.TestCase):
    def test_it_reads_the_four_numbers(self):
        version = parse_version("1.2.3+4")
        self.assertEqual((1, 2, 3, 4), (version.major, version.minor, version.patch, version.build))

    def test_a_leading_v_and_a_released_suffix_are_decoration(self):
        for raw in ("v1.2.3+4", "1.2.3+4", "v1.2.3+4-released"):
            self.assertEqual("1.2.3+4", parse_version(raw).text, raw)

    def test_a_tag_without_a_build_number_reports_it_as_unknown(self):
        self.assertEqual(UNKNOWN_BUILD, parse_version("v2.0.0").build)
        self.assertEqual("2.0.0", parse_version("v2.0.0").text)

    def test_nonsense_is_invalid_rather_than_zero(self):
        for raw in ("", "latest", "v", "1.2", "release-3"):
            self.assertFalse(parse_version(raw).valid, raw)


class ComparingVersions(unittest.TestCase):
    def test_a_higher_name_wins_whatever_the_build_numbers_say(self):
        self.assertTrue(parse_version("1.2.0+3").newer_than(parse_version("1.1.9+7")))

    def test_the_build_number_settles_the_same_name(self):
        self.assertTrue(parse_version("1.0.0+8").newer_than(parse_version("1.0.0+7")))
        self.assertFalse(parse_version("1.0.0+7").newer_than(parse_version("1.0.0+8")))

    def test_identical_versions_are_not_newer(self):
        self.assertFalse(parse_version("1.0.0+7").newer_than(parse_version("1.0.0+7")))

    def test_an_unknown_build_number_abstains_rather_than_counting_as_zero(self):
        installed = parse_version("1.0.0+2")
        offered = parse_version("v1.0.0")
        self.assertFalse(offered.newer_than(installed))
        self.assertFalse(installed.newer_than(offered))

    def test_build_zero_is_a_real_build_number_not_a_missing_one(self):
        self.assertTrue(parse_version("1.0.0+1").newer_than(parse_version("1.0.0+0")))
        self.assertFalse(parse_version("1.0.0+0").newer_than(parse_version("1.0.0+1")))
        self.assertEqual("1.0.0+0", parse_version("1.0.0+0").text)

    def test_an_unknown_build_still_loses_to_a_higher_name(self):
        self.assertTrue(parse_version("v1.1.0").newer_than(parse_version("1.0.0+9")))

    def test_an_invalid_version_never_wins(self):
        self.assertFalse(parse_version("nonsense").newer_than(parse_version("0.0.1")))
        self.assertFalse(parse_version("9.9.9").newer_than(parse_version("nonsense")))

    def test_patch_ordering_is_numeric_not_lexical(self):
        self.assertTrue(parse_version("1.0.10").newer_than(parse_version("1.0.9")))


class DecidingWhatIsOfficial(unittest.TestCase):
    def test_both_signals_have_to_agree(self):
        self.assertTrue(Release(tag="v1.0.0-released", prerelease=False).official)
        self.assertFalse(Release(tag="v1.0.0-released", prerelease=True).official)
        self.assertFalse(Release(tag="v1.0.0", prerelease=False).official)

    def test_a_build_number_in_the_tag_does_not_hide_the_suffix(self):
        release = Release(tag="v1.0.0+8-released", prerelease=False)
        self.assertTrue(release.official)
        self.assertEqual(8, release.version.build)

    def test_the_suffix_has_to_come_after_the_build_number(self):
        wrong = Release(tag="v1.0.0-released+8", prerelease=False)
        self.assertFalse(wrong.official)


class OfferingABuildOfTheSameVersion(unittest.TestCase):
    """What putting the build number in the tag is actually for."""

    def test_a_higher_build_of_the_installed_version_is_newer(self):
        installed = parse_version("1.0.0+2")
        offered = Release(tag="v1.0.0+3-released", prerelease=False).version
        self.assertTrue(offered.newer_than(installed))

    def test_the_same_build_of_the_installed_version_is_not(self):
        installed = parse_version("1.0.0+3")
        offered = Release(tag="v1.0.0+3-released", prerelease=False).version
        self.assertFalse(offered.newer_than(installed))

    def test_an_older_build_of_the_installed_version_is_not(self):
        installed = parse_version("1.0.0+4")
        offered = Release(tag="v1.0.0+3-released", prerelease=False).version
        self.assertFalse(offered.newer_than(installed))


class ChoosingARelease(unittest.TestCase):
    RELEASES = (
        Release(tag="v1.0.0", prerelease=True),
        Release(tag="v2.0.0-released", prerelease=False),
        Release(tag="v1.5.0-released", prerelease=False),
        Release(tag="v3.0.0", prerelease=True),
    )

    def test_by_default_only_official_releases_are_offered(self):
        chosen = choose(self.RELEASES, UpdateSource(repository="a/b"))
        self.assertEqual("v2.0.0-released", chosen.tag)

    def test_prereleases_are_included_when_asked_for(self):
        chosen = choose(
            self.RELEASES, UpdateSource(repository="a/b", channel=CHANNEL_ANY)
        )
        self.assertEqual("v3.0.0", chosen.tag)

    def test_the_feeds_own_order_is_not_trusted(self):
        by_date = (
            Release(tag="v1.0.1-released", prerelease=False),
            Release(tag="v2.0.0-released", prerelease=False),
        )
        self.assertEqual("v2.0.0-released", choose(by_date, UpdateSource(repository="a/b")).tag)

    def test_nothing_official_means_nothing_is_offered(self):
        only_debug = (Release(tag="v1.0.0", prerelease=True),)
        self.assertIsNone(choose(only_debug, UpdateSource(repository="a/b")))

    def test_an_unparseable_tag_is_a_last_resort_not_a_crash(self):
        odd = (Release(tag="nightly", prerelease=False),)
        chosen = choose(odd, UpdateSource(repository="a/b", channel=CHANNEL_ANY))
        self.assertEqual("nightly", chosen.tag)


class ValidatingTheSource(unittest.TestCase):
    def test_a_url_pasted_into_the_repository_field_is_refused(self):
        source = UpdateSource(repository="https://github.com/owner/name")
        self.assertIn("is not owner/name", source.problem)

    def test_owner_name_is_accepted(self):
        self.assertEqual("", UpdateSource(repository="owner/name").problem)

    def test_empty_is_reported_as_unconfigured(self):
        self.assertIn("no repository", UpdateSource(repository="").problem)
        self.assertFalse(UpdateSource(repository="").configured)

    def test_the_shipped_default_is_configured(self):
        self.assertEqual(DEFAULT_REPOSITORY, UpdateSource().repository)
        self.assertTrue(UpdateSource().configured)
        self.assertEqual("", UpdateSource().problem)

    def test_a_non_url_api_base_is_refused(self):
        source = UpdateSource(repository="owner/name", api_base="api.github.com")
        self.assertIn("not an http", source.problem)

    def test_the_url_it_would_ask_is_the_releases_list(self):
        source = UpdateSource(repository="owner/name")
        self.assertEqual(
            f"{DEFAULT_API_BASE}/repos/owner/name/releases", source.releases_url
        )

    def test_a_trailing_slash_on_the_api_base_does_not_double_up(self):
        source = UpdateSource(repository="owner/name", api_base="https://host/api/v3/")
        self.assertEqual("https://host/api/v3/repos/owner/name/releases", source.releases_url)


class _Config(ConfigPort):
    """Only what UpdatesCapability asks for."""

    def __init__(self, source: UpdateSource) -> None:
        self._source = source

    def update_source(self) -> UpdateSource:
        return self._source

    def settings(self) -> Settings:
        return Settings(updates=self._source)

    def template_source(self, pack_key, default):
        return default

    def script_source(self, pack_key, default):
        return default

    def bundle_prefix(self) -> str:
        return "com.dti"

    def workspace_root(self):
        from pathlib import Path

        return Path(".")

    def scripts_root(self):
        from pathlib import Path

        return Path(".")

    def script_check(self, pack_key: str) -> bool:
        return True

    def location(self, scope: ConfigScope):
        from pathlib import Path

        return Path("settings.toml")

    def active_location(self):
        return None

    def save(self, settings: Settings, scope: ConfigScope):
        from pathlib import Path

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
    """Never reached by these tests, which stop before the download."""

    async def fetch(self, url: str, target) -> int:
        raise AssertionError("_check must not download unless asked to")


class _Console:
    """Captures what the capability narrates, and whether it was asked to install."""

    def __init__(self, install_problem: str = "") -> None:
        self.lines: list[str] = []
        self.installed: list[tuple[str, str]] = []
        self.install_problem = install_problem

    def write(self, line: str) -> None:
        self.lines.append(line)

    async def install_update(self, installer: str, version: str) -> str:
        self.installed.append((installer, version))
        return self.install_problem


class _RealDownloads(AssetDownloadPort):
    """Writes a file, so the paths after a successful download are reachable."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def fetch(self, url: str, target) -> int:
        self.fetched.append(url)
        target.write_bytes(b"installer")
        return 9


class Channels(unittest.TestCase):
    """Three answers, and the middle one is the reason this is not a boolean."""

    OFFICIAL = Release(tag="v2.0.0+9-released", prerelease=False)
    DEBUG = Release(tag="v1.5.0+8", prerelease=True)
    ODD = Release(tag="v3.0.0+7", prerelease=False)
    """Published as a full release but tagged without -released, so `official` says no."""

    def _chosen(self, channel, releases=None):
        source = UpdateSource(repository="a/b", channel=channel)
        return choose(releases or (self.OFFICIAL, self.DEBUG), source)

    def test_official_ignores_a_newer_prerelease(self):
        self.assertEqual(self.OFFICIAL.tag, self._chosen(CHANNEL_OFFICIAL).tag)

    def test_prerelease_ignores_a_newer_official_release(self):
        self.assertEqual(self.DEBUG.tag, self._chosen(CHANNEL_PRERELEASE).tag)

    def test_any_takes_whichever_is_newest(self):
        self.assertEqual(self.OFFICIAL.tag, self._chosen(CHANNEL_ANY).tag)

    def test_prerelease_offers_nothing_when_there_are_none(self):
        self.assertIsNone(self._chosen(CHANNEL_PRERELEASE, (self.OFFICIAL,)))

    def test_a_release_that_is_neither_belongs_to_any_alone(self):
        self.assertIsNone(self._chosen(CHANNEL_OFFICIAL, (self.ODD,)))
        self.assertIsNone(self._chosen(CHANNEL_PRERELEASE, (self.ODD,)))
        self.assertEqual(self.ODD.tag, self._chosen(CHANNEL_ANY, (self.ODD,)).tag)

    def test_include_prereleases_is_derived_from_the_channel(self):
        self.assertFalse(UpdateSource(channel=CHANNEL_OFFICIAL).include_prereleases)
        self.assertTrue(UpdateSource(channel=CHANNEL_PRERELEASE).include_prereleases)
        self.assertTrue(UpdateSource(channel=CHANNEL_ANY).include_prereleases)


class DownloadingAndInstalling(unittest.TestCase):
    """The card's own install path, and the flag that ignores being up to date."""

    def _run(self, values, *, version="0.1.0+2", latest="v0.2.0+3-released",
             install_problem=""):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        console = _Console(install_problem=install_problem)
        downloads = _RealDownloads()
        feed = _Feed((
            Release(
                tag=latest,
                prerelease=False,
                asset_name="dti-setup.exe",
                asset_url="https://x/i.exe",
                asset_size=1024,
            ),
        ))
        capability = UpdatesCapability(
            console=console,
            config=_Config(UpdateSource(repository="a/b")),
            feed=feed,
            version=version,
            downloads=downloads,
        )
        merged = {"folder": folder.name, **values}
        message, ok = asyncio.run(capability._check(merged))
        return message, ok, console, downloads

    def test_up_to_date_stops_unless_asked_anyway(self):
        message, ok, console, downloads = self._run(
            {"download": True}, version="0.2.0+3", latest="v0.2.0+3-released"
        )
        self.assertTrue(ok)
        self.assertIn("Up to date", message)
        self.assertEqual([], downloads.fetched, "nothing to fetch")

    def test_anyway_reinstalls_the_version_already_running(self):
        message, ok, console, downloads = self._run(
            {"anyway": True}, version="0.2.0+3", latest="v0.2.0+3-released"
        )
        self.assertEqual(1, len(downloads.fetched))
        self.assertTrue(any("reinstalling it as asked" in line for line in console.lines))
        self.assertEqual(1, len(console.installed), "anyway installs as well as fetches")

    def test_anyway_downloads_without_the_download_box(self):
        _, _, _, downloads = self._run({"anyway": True})
        self.assertEqual(1, len(downloads.fetched))

    def test_install_hands_the_path_to_the_app(self):
        message, ok, console, _ = self._run({"download": True, "install": True})
        self.assertEqual(1, len(console.installed))
        installer, version = console.installed[0]
        self.assertTrue(installer.endswith("dti-setup.exe"))
        self.assertEqual("0.2.0+3", version)

    def test_download_alone_installs_nothing(self):
        message, ok, console, _ = self._run({"download": True})
        self.assertEqual([], console.installed)
        self.assertIn("Downloaded", message)

    def test_a_refused_install_reports_it_and_says_where_the_file_is(self):
        message, ok, console, _ = self._run(
            {"download": True, "install": True}, install_problem="Left alone"
        )
        self.assertFalse(ok)
        self.assertIn("Left alone", message)
        self.assertTrue(any("Ctrl+U" in line for line in console.lines))


class EachLineUpdatesItself(unittest.TestCase):
    """A release that cannot replace this build is never offered."""

    OFFICIAL = Release(tag="v1.0.0+9-released", prerelease=False)
    DEBUG = Release(tag="v1.1.0+20", prerelease=True)

    def _choose(self, build, channel=CHANNEL_ANY, releases=None):
        return choose(
            releases if releases is not None else (self.OFFICIAL, self.DEBUG),
            UpdateSource(repository="a/b", channel=channel),
            build,
        )

    def test_a_release_build_is_never_offered_a_debug_build(self):
        self.assertEqual(self.OFFICIAL, self._choose(BUILD_RELEASE))

    def test_a_debug_build_is_never_offered_an_official_release(self):
        self.assertEqual(self.DEBUG, self._choose(BUILD_DEBUG))

    def test_the_channel_cannot_overrule_the_line(self):
        for channel in (CHANNEL_OFFICIAL, CHANNEL_PRERELEASE, CHANNEL_ANY):
            self.assertEqual(self.OFFICIAL, self._choose(BUILD_RELEASE, channel), channel)
            self.assertEqual(self.DEBUG, self._choose(BUILD_DEBUG, channel), channel)

    def test_nothing_on_this_line_is_offered_nothing(self):
        self.assertIsNone(self._choose(BUILD_DEBUG, releases=(self.OFFICIAL,)))
        self.assertIsNone(self._choose(BUILD_RELEASE, releases=(self.DEBUG,)))

    def test_a_source_checkout_still_follows_the_channel(self):
        self.assertEqual(self.DEBUG, self._choose(BUILD_UNKNOWN, CHANNEL_ANY))
        self.assertEqual(self.OFFICIAL, self._choose(BUILD_UNKNOWN, CHANNEL_OFFICIAL))
        self.assertEqual(self.DEBUG, self._choose(BUILD_UNKNOWN, CHANNEL_PRERELEASE))


class ReadingTheLineOffTheCommand(unittest.TestCase):
    """`build_kind`, which is the whole of how the app knows which line it is on."""

    def test_the_debug_command_is_the_debug_line(self):
        self.assertEqual(BUILD_DEBUG, build_kind("dti-debug.exe"))
        self.assertEqual(BUILD_DEBUG, build_kind(r"C:\Programs\dti-debug\dti-debug.exe"))

    def test_the_plain_command_is_the_release_line(self):
        self.assertEqual(BUILD_RELEASE, build_kind("dti.exe"))
        self.assertEqual(BUILD_RELEASE, build_kind(r"C:\Programs\dti\dti.exe"))

    def test_nothing_is_no_line_at_all(self):
        self.assertEqual(BUILD_UNKNOWN, build_kind(""))

    def test_the_case_of_the_name_does_not_decide_it(self):
        self.assertEqual(BUILD_DEBUG, build_kind("DTI-Debug.exe"))


class RunningAnInstallerFromDisk(unittest.TestCase):
    """The file chooser: a setup program picked by hand, with no feed involved."""

    def _run(self, values, *, repository="a/b", install_problem=""):
        console = _Console(install_problem=install_problem)
        feed = _Feed((
            Release(tag="v9.9.9-released", asset_name="x.exe", asset_url="https://x/i.exe"),
        ))
        capability = UpdatesCapability(
            console=console,
            config=_Config(UpdateSource(repository=repository)),
            feed=feed,
            version="0.1.0+2",
            downloads=_RealDownloads(),
        )
        message, ok = asyncio.run(capability._check({LOCAL_KEY: True, **values}))
        return message, ok, console, feed

    def _installer(self, name="dti-0.2.1+15-setup.exe"):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        target = Path(folder.name) / name
        target.write_bytes(b"")
        return target

    def test_the_chosen_file_is_handed_to_the_app(self):
        target = self._installer()
        message, ok, console, _ = self._run({INSTALLER_KEY: str(target)})
        self.assertTrue(ok, message)
        self.assertEqual(1, len(console.installed))
        installer, version = console.installed[0]
        self.assertEqual(str(target), installer)
        self.assertEqual(target.name, version)

    def test_the_feed_is_never_asked(self):
        _, _, _, feed = self._run({INSTALLER_KEY: str(self._installer())})
        self.assertEqual(0, feed.asked)

    def test_it_works_with_no_repository_configured(self):
        target = self._installer()
        message, ok, console, _ = self._run({INSTALLER_KEY: str(target)}, repository="")
        self.assertTrue(ok, message)
        self.assertEqual(1, len(console.installed))

    def test_it_says_it_does_not_know_what_the_file_is(self):
        target = self._installer()
        _, _, console, _ = self._run({INSTALLER_KEY: str(target)})
        self.assertTrue(
            any(str(target) in line for line in console.lines),
            "the path it is about to run is not named",
        )
        self.assertTrue(
            any("installs beside the release one" in line for line in console.lines),
            "nothing warns that this may not replace the running copy",
        )

    def test_no_file_chosen_is_refused(self):
        message, ok, console, _ = self._run({INSTALLER_KEY: "   "})
        self.assertFalse(ok)
        self.assertIn("No installer chosen", message)
        self.assertEqual([], console.installed)

    def test_a_file_that_is_not_there_is_refused(self):
        message, ok, console, _ = self._run({INSTALLER_KEY: "C:/nowhere/setup.exe"})
        self.assertFalse(ok)
        self.assertIn("no file at", message)
        self.assertEqual([], console.installed)

    def test_something_that_is_not_a_setup_program_is_refused(self):
        message, ok, console, _ = self._run({INSTALLER_KEY: str(self._installer("dti.msi"))})
        self.assertFalse(ok)
        self.assertIn("not a setup program", message)
        self.assertEqual([], console.installed)

    def test_a_refused_install_is_reported(self):
        target = self._installer()
        message, ok, _, _ = self._run(
            {INSTALLER_KEY: str(target)}, install_problem="Left alone"
        )
        self.assertFalse(ok)
        self.assertIn("Left alone", message)


class TheSettingsFileAndTheDefault(unittest.TestCase):
    """Absent and empty are different answers, and the round trip has to keep them apart."""

    def _config(self, body: str = "") -> FileConfig:
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        project = Path(folder.name) / naming.CONFIG_NAME
        project.write_text(body, encoding="utf-8")
        return FileConfig(project=project, user=Path(folder.name) / "absent.toml")

    def test_a_file_with_no_updates_section_gets_the_default(self):
        source = self._config("").update_source()
        self.assertEqual(DEFAULT_REPOSITORY, source.repository)
        self.assertTrue(source.configured)

    def test_a_file_with_an_empty_repository_stays_off(self):
        source = self._config('[updates]\nrepository = ""\n').update_source()
        self.assertEqual("", source.repository)
        self.assertFalse(source.configured, "an empty repository is somebody saying off")

    def test_a_file_naming_a_fork_gets_the_fork(self):
        source = self._config('[updates]\nrepository = "someone/else"\n').update_source()
        self.assertEqual("someone/else", source.repository)

    def test_turning_it_off_survives_a_save_and_a_reload(self):
        config = self._config("")
        settings = replace(config.settings(), updates=UpdateSource(repository=""))
        written = config.save(settings, ConfigScope.PROJECT)
        self.assertIn('repository = ""', written.read_text(encoding="utf-8"))
        self.assertFalse(
            FileConfig(project=written, user=written.parent / "absent.toml")
            .update_source()
            .configured
        )

    def test_the_channel_defaults_to_official(self):
        self.assertEqual(CHANNEL_OFFICIAL, self._config("").update_source().channel)

    def test_a_named_channel_is_read(self):
        source = self._config('[updates]\nchannel = "prerelease"\n').update_source()
        self.assertEqual(CHANNEL_PRERELEASE, source.channel)

    def test_the_old_boolean_still_means_what_it_meant(self):
        source = self._config('[updates]\ninclude_prereleases = true\n').update_source()
        self.assertEqual(CHANNEL_ANY, source.channel)

    def test_a_typo_in_the_channel_falls_back_rather_than_failing(self):
        source = self._config('[updates]\nchannel = "beta"\n').update_source()
        self.assertEqual(CHANNEL_OFFICIAL, source.channel)

    def test_a_channel_round_trips(self):
        config = self._config("")
        settings = replace(
            config.settings(), updates=UpdateSource(repository="a/b", channel=CHANNEL_PRERELEASE)
        )
        written = config.save(settings, ConfigScope.PROJECT)
        self.assertIn('channel = "prerelease"', written.read_text(encoding="utf-8"))
        self.assertEqual(
            CHANNEL_PRERELEASE,
            FileConfig(project=written, user=written.parent / "absent.toml")
            .update_source()
            .channel,
        )

    def test_the_default_itself_is_not_written_back_as_configuration(self):
        config = self._config("")
        written = config.save(config.settings(), ConfigScope.PROJECT)
        self.assertNotIn("repository =", written.read_text(encoding="utf-8"))


class TheCheck(unittest.TestCase):
    """`_check` directly - the panel loop around it is the run panel's own test."""

    def _run(self, source, feed, version="0.1.0+2", values=None):
        console = _Console()
        capability = UpdatesCapability(
            console=console,
            config=_Config(source),
            feed=feed,
            version=version,
            downloads=_Downloads(),
        )
        message, ok = asyncio.run(capability._check(values or {}))
        return message, ok, console.lines

    def test_an_unconfigured_source_is_reported_and_nothing_is_asked(self):
        feed = _Feed()
        message, ok, lines = self._run(UpdateSource(repository=""), feed)
        self.assertFalse(ok)
        self.assertEqual(0, feed.asked, "it must not make a request it knows will fail")
        self.assertTrue(any("Advanced" in line for line in lines))

    def test_a_feed_error_becomes_one_sentence(self):
        feed = _Feed(error="GitHub is rate limiting this address")
        message, ok, _ = self._run(UpdateSource(repository="a/b"), feed)
        self.assertFalse(ok)
        self.assertIn("rate limiting", message)

    def test_no_releases_at_all_is_not_a_failure(self):
        message, ok, _ = self._run(UpdateSource(repository="a/b"), _Feed(()))
        self.assertTrue(ok)
        self.assertIn("no releases", message)

    def test_being_up_to_date_is_reported_as_success(self):
        feed = _Feed((Release(tag="v0.1.0-released", prerelease=False),))
        message, ok, _ = self._run(UpdateSource(repository="a/b"), feed, version="0.1.0+2")
        self.assertTrue(ok)
        self.assertIn("Up to date", message)

    def test_a_newer_release_is_offered_without_downloading(self):
        feed = _Feed(
            (
                Release(
                    tag="v0.2.0-released",
                    prerelease=False,
                    asset_name="dti-0.2.0-setup-released.exe",
                    asset_url="https://example.invalid/setup.exe",
                    asset_size=13_000_000,
                ),
            )
        )
        message, ok, lines = self._run(UpdateSource(repository="a/b"), feed)
        self.assertTrue(ok)
        self.assertIn("v0.2.0-released", message)
        self.assertIn("Download the installer", message)
        self.assertTrue(any("dti-0.2.0-setup" in line for line in lines))

    def test_only_prereleases_says_which_switch_would_change_that(self):
        feed = _Feed((Release(tag="v9.9.9", prerelease=True),))
        message, ok, _ = self._run(UpdateSource(repository="a/b"), feed)
        self.assertTrue(ok)
        self.assertIn("published nothing on the", message)
        self.assertIn("Advanced", message)

    def test_a_release_with_no_matching_asset_still_reports_the_version(self):
        feed = _Feed((Release(tag="v0.2.0-released", prerelease=False),))
        message, ok, lines = self._run(UpdateSource(repository="a/b"), feed)
        self.assertTrue(ok)
        self.assertTrue(any("No asset" in line for line in lines))

    def test_asking_to_download_a_release_with_no_asset_fails_rather_than_pretending(self):
        feed = _Feed((Release(tag="v0.2.0-released", prerelease=False),))
        message, ok, _ = self._run(
            UpdateSource(repository="a/b"), feed, values={"download": True}
        )
        self.assertFalse(ok)
        self.assertIn("no installer", message)


if __name__ == "__main__":
    unittest.main()
