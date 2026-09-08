"""The update check: version comparison, which release gets offered, and reporting.

Version comparison is the part worth testing hardest. It is four numbers with one
of them allowed to be unknown, and every wrong answer is silent: too eager and
people are offered a downgrade, too shy and a real update is never mentioned.
"""

import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from company_tui.capabilities.updates import UpdatesCapability
from company_tui.domain import naming
from company_tui.domain.config import ConfigPort, ConfigScope, Settings
from company_tui.domain.updates import (
    DEFAULT_API_BASE,
    DEFAULT_REPOSITORY,
    UNKNOWN_BUILD,
    AssetDownloadPort,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateSource,
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
        # A distinct value from any real build number, so "absent" and "+0" are
        # not the same answer - see test_build_zero_is_a_real_build_number.
        self.assertEqual(UNKNOWN_BUILD, parse_version("v2.0.0").build)
        self.assertEqual("2.0.0", parse_version("v2.0.0").text)

    def test_nonsense_is_invalid_rather_than_zero(self):
        for raw in ("", "latest", "v", "1.2", "release-3"):
            self.assertFalse(parse_version(raw).valid, raw)


class ComparingVersions(unittest.TestCase):
    def test_a_higher_name_wins_whatever_the_build_numbers_say(self):
        # The build number rises globally, so this pairing cannot happen from the
        # release workflow - but a hand-made tag can produce it, and the name is
        # what a person reads.
        self.assertTrue(parse_version("1.2.0+3").newer_than(parse_version("1.1.9+7")))

    def test_the_build_number_settles_the_same_name(self):
        self.assertTrue(parse_version("1.0.0+8").newer_than(parse_version("1.0.0+7")))
        self.assertFalse(parse_version("1.0.0+7").newer_than(parse_version("1.0.0+8")))

    def test_identical_versions_are_not_newer(self):
        self.assertFalse(parse_version("1.0.0+7").newer_than(parse_version("1.0.0+7")))

    def test_an_unknown_build_number_abstains_rather_than_counting_as_zero(self):
        # THE REGRESSION THIS GUARDS is `newer_than`'s short-circuit, not the
        # sentinel's value. Without it, an installed 1.0.0+2 compares NEWER than a
        # release tagged v1.0.0, so re-offering the same version reads as a
        # downgrade - and comparing the other way, a real update goes unmentioned.
        installed = parse_version("1.0.0+2")
        offered = parse_version("v1.0.0")
        self.assertFalse(offered.newer_than(installed))
        self.assertFalse(installed.newer_than(offered))

    def test_build_zero_is_a_real_build_number_not_a_missing_one(self):
        # WHY THE SENTINEL IS NEGATIVE. With 0 as "unknown", `1.0.0+0` - the first
        # build of a version, which the release workflow does produce - is
        # indistinguishable from a tag that published no build number, so the
        # short-circuit fires and +1 stops counting as newer than +0.
        self.assertTrue(parse_version("1.0.0+1").newer_than(parse_version("1.0.0+0")))
        self.assertFalse(parse_version("1.0.0+0").newer_than(parse_version("1.0.0+1")))
        self.assertEqual("1.0.0+0", parse_version("1.0.0+0").text)

    def test_an_unknown_build_still_loses_to_a_higher_name(self):
        self.assertTrue(parse_version("v1.1.0").newer_than(parse_version("1.0.0+9")))

    def test_an_invalid_version_never_wins(self):
        self.assertFalse(parse_version("nonsense").newer_than(parse_version("0.0.1")))
        self.assertFalse(parse_version("9.9.9").newer_than(parse_version("nonsense")))

    def test_patch_ordering_is_numeric_not_lexical(self):
        # "10" < "9" as strings, which is the classic way this breaks.
        self.assertTrue(parse_version("1.0.10").newer_than(parse_version("1.0.9")))


class DecidingWhatIsOfficial(unittest.TestCase):
    def test_both_signals_have_to_agree(self):
        self.assertTrue(Release(tag="v1.0.0-released", prerelease=False).official)
        # Tagged official but published as a prerelease.
        self.assertFalse(Release(tag="v1.0.0-released", prerelease=True).official)
        # Published as a release but tagged as a debug build.
        self.assertFalse(Release(tag="v1.0.0", prerelease=False).official)

    def test_a_build_number_in_the_tag_does_not_hide_the_suffix(self):
        # The release workflow tags `v<x.y.z>+<n>-released`, so the suffix is no
        # longer the end of a bare name.
        release = Release(tag="v1.0.0+8-released", prerelease=False)
        self.assertTrue(release.official)
        self.assertEqual(8, release.version.build)

    def test_the_suffix_has_to_come_after_the_build_number(self):
        # WHY THE TAG IS `v1.0.0+8-released` AND NOT `v1.0.0-released+8`, which is
        # semver's ordering and would be the obvious way to write it. `official`
        # asks what the tag ENDS WITH, so the semver spelling reads as a debug
        # build - and `include_prereleases` is off, so it would never be offered
        # at all. Nothing would report an error; the update would just never come.
        wrong = Release(tag="v1.0.0-released+8", prerelease=False)
        self.assertFalse(wrong.official)


class OfferingABuildOfTheSameVersion(unittest.TestCase):
    """What putting the build number in the tag is actually for.

    Before it, both sides of this comparison were the same three numbers and the
    build abstained, so a rebuild of the installed version could never be offered
    - which is the whole reason the number rises globally.
    """

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
            self.RELEASES, UpdateSource(repository="a/b", include_prereleases=True)
        )
        self.assertEqual("v3.0.0", chosen.tag)

    def test_the_feeds_own_order_is_not_trusted(self):
        # GitHub returns releases by creation date. A patch published for an old
        # branch after a newer release comes back first, and taking the head of
        # the list would offer a downgrade.
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
        chosen = choose(odd, UpdateSource(repository="a/b", include_prereleases=True))
        self.assertEqual("nightly", chosen.tag)


class ValidatingTheSource(unittest.TestCase):
    def test_a_url_pasted_into_the_repository_field_is_refused(self):
        # Left to the API this is a 404, which reads as "no releases" rather than
        # "that is not a repository name".
        source = UpdateSource(repository="https://github.com/owner/name")
        self.assertIn("is not owner/name", source.problem)

    def test_owner_name_is_accepted(self):
        self.assertEqual("", UpdateSource(repository="owner/name").problem)

    def test_empty_is_reported_as_unconfigured(self):
        self.assertIn("no repository", UpdateSource(repository="").problem)
        self.assertFalse(UpdateSource(repository="").configured)

    def test_the_shipped_default_is_configured(self):
        # The default is a real repository now, so a bare UpdateSource is usable -
        # which is also what Advanced's "reset to defaults" writes.
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
    """Captures what the capability narrates, and nothing else."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, line: str) -> None:
        self.lines.append(line)


class TheSettingsFileAndTheDefault(unittest.TestCase):
    """Absent and empty are different answers, and the round trip has to keep them apart.

    The default is a real repository, so a settings file that says nothing gets it. A file
    that says `repository = ""` has said OFF, and must keep saying it - which means the
    save path has to write that empty value down rather than omitting it the way it omits
    every other default. Omit it and clearing the field in Advanced switches checking off
    until the next read and then quietly back on.
    """

    def _config(self, body: str = "") -> FileConfig:
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        project = Path(folder.name) / naming.CONFIG_NAME
        project.write_text(body, encoding="utf-8")
        # A user file that does not exist, so only the project one is read.
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
        # THE REGRESSION THIS GUARDS. Saving an empty repository used to write no line
        # at all, which reads back as "nothing said" and hands out the default.
        config = self._config("")
        settings = replace(config.settings(), updates=UpdateSource(repository=""))
        written = config.save(settings, ConfigScope.PROJECT)
        self.assertIn('repository = ""', written.read_text(encoding="utf-8"))
        self.assertFalse(
            FileConfig(project=written, user=written.parent / "absent.toml")
            .update_source()
            .configured
        )

    def test_the_default_itself_is_not_written_back_as_configuration(self):
        # The other half: a settings file repeating the built-in value is noise that
        # reads as a decision, and it pins every existing file to today's default.
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
        self.assertIn("only prereleases", message)

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
