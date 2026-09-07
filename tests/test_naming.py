"""Every name derives from `APP_SLUG`, and the old ones are still accepted.

Four of these names are a wire format something else on the machine already
speaks - a manifest filename, an environment variable, a store directory, a
settings file - so the rule is that the NEW name is written and EITHER is read.
Getting that backwards is silent in both directions: writing the old name looks
fine because the resolvers accept it, and refusing to read it makes every project
that has one stop being recognised.
"""

import tempfile
import unittest
from pathlib import Path

from company_tui.domain import naming
from company_tui.domain.identity import SCRIPT_MANIFEST, ProjectIdentity
from company_tui.domain.project_name import ProjectName
from company_tui.templates.python.behavior import _project_files


class NamesDeriveFromOneSlug(unittest.TestCase):
    def test_nothing_is_written_out_by_hand(self):
        slug = naming.APP_SLUG
        self.assertEqual(f"{slug}.script.json", naming.SCRIPT_MANIFEST)
        self.assertEqual(f".{slug}", naming.STORE_DIR_NAME)
        self.assertEqual(f"{slug}.toml", naming.CONFIG_NAME)
        self.assertEqual(f"com.{slug}", naming.BUNDLE_PREFIX)
        self.assertEqual(f"{naming.APP_NAME}_PROJECT_ROOT", naming.PROJECT_ROOT_VAR)

    def test_no_name_still_carries_the_old_brand(self):
        for value in (
            naming.APP_SLUG,
            naming.APP_NAME,
            naming.APP_TITLE,
            naming.SCRIPT_MANIFEST,
            naming.STORE_DIR_NAME,
            naming.CONFIG_NAME,
            naming.BUNDLE_PREFIX,
            naming.PROJECT_ROOT_VAR,
        ):
            self.assertNotIn("ikaika", value.lower(), value)


class TheOldNamesAreStillRead(unittest.TestCase):
    def test_both_manifest_names_are_accepted(self):
        self.assertIn(naming.SCRIPT_MANIFEST, naming.manifest_names())
        for legacy in naming.LEGACY_SCRIPT_MANIFESTS:
            self.assertIn(legacy, naming.manifest_names())

    def test_the_preferred_name_wins_when_a_project_carries_both(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / naming.SCRIPT_MANIFEST).write_text("{}", encoding="utf-8")
            for legacy in naming.LEGACY_SCRIPT_MANIFESTS:
                (root / legacy).write_text("{}", encoding="utf-8")
            found = naming.manifest_in(root)
            self.assertEqual(naming.SCRIPT_MANIFEST, found.name)

    def test_a_project_with_only_the_old_name_is_still_found(self):
        for legacy in naming.LEGACY_SCRIPT_MANIFESTS:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / legacy).write_text("{}", encoding="utf-8")
                self.assertEqual(legacy, naming.manifest_in(root).name)
                # And it keeps its name: rewriting the identity must not leave the
                # old file behind holding a stale copy of the same four keys.
                self.assertEqual(legacy, naming.manifest_path(root).name)

    def test_a_directory_with_neither_gets_the_preferred_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(naming.manifest_in(root))
            self.assertEqual(naming.SCRIPT_MANIFEST, naming.manifest_path(root).name)

    def test_the_new_environment_variable_wins_over_the_old(self):
        legacy = naming.LEGACY_PROJECT_ROOT_VARS[0]
        self.assertEqual(
            "new",
            naming.project_root_from_env({naming.PROJECT_ROOT_VAR: "new", legacy: "old"}),
        )
        self.assertEqual("old", naming.project_root_from_env({legacy: "old"}))
        self.assertEqual("", naming.project_root_from_env({}))

    def test_an_existing_store_is_used_where_it_is(self):
        # Preferring the new name and creating it would leave every cloned script
        # repository and every remembered tab behind a directory nothing reads,
        # which looks exactly like the toolbox having lost them.
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            legacy = home / naming.LEGACY_STORE_DIR_NAMES[0]
            legacy.mkdir()
            self.assertEqual(legacy, naming.store_dir(home))

    def test_the_preferred_store_wins_when_both_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / naming.STORE_DIR_NAME).mkdir()
            (home / naming.LEGACY_STORE_DIR_NAMES[0]).mkdir()
            self.assertEqual(home / naming.STORE_DIR_NAME, naming.store_dir(home))


class WhatAScaffoldWrites(unittest.TestCase):
    """THE REGRESSION. The reference pack hardcoded the old filename.

    `ikaika.script.json` was written verbatim into every project the Python pack
    scaffolded, while `domain/identity.py` already exported the right constant.
    Nothing failed: the resolvers accept the old name, so a project created with it
    is read back perfectly - it is only wrong on the way out, which is why it
    survived a whole de-brand. Found by a linter, not by a person.
    """

    def _files(self) -> dict[str, str]:
        identity = ProjectIdentity(
            name=ProjectName("demo_app"),
            title="Demo App",
            description="A Demo App project",
            version="0.1.0",
        )
        return _project_files(identity)

    def test_a_new_project_gets_the_current_manifest_name(self):
        files = self._files()
        self.assertIn(SCRIPT_MANIFEST, files)

    def test_a_new_project_gets_no_legacy_manifest(self):
        files = self._files()
        for legacy in naming.LEGACY_SCRIPT_MANIFESTS:
            self.assertNotIn(legacy, files)

    def test_exactly_one_manifest_is_written(self):
        manifests = [name for name in self._files() if name.endswith(".script.json")]
        self.assertEqual([SCRIPT_MANIFEST], manifests)


if __name__ == "__main__":
    unittest.main()
