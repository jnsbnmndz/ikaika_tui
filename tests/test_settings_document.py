"""Exporting settings as JSON and reading one back.

The round trip is the whole promise: a document written on one machine and read
on another has to produce the same settings. What is tested hardest is the
FORGIVING half - an import that quietly drops half a document while reporting
success is the failure this shape exists to prevent, so every recovery path also
has to report.
"""

import json
import tempfile
import unittest
from pathlib import Path

from company_tui.domain.config import Settings, TemplateSource
from company_tui.domain.settings_document import (
    KIND,
    KNOWN_KINDS,
    SCHEMA,
    read_document,
    write_document,
)
from company_tui.domain.updates import (
    CHANNEL_ANY,
    DEFAULT_API_BASE,
    DEFAULT_ASSET_PATTERN,
    UpdateSource,
)

FULL = Settings(
    workspace_root="~/work",
    bundle_prefix="com.example",
    scripts_root="~/.dti/scripts",
    templates={"python": TemplateSource(url="https://host/py.git", ref="v1.0.0")},
    scripts={"react": TemplateSource(url="https://host/react.git")},
    script_checks={"react": False},
    updates=UpdateSource(
        repository="owner/name",
        api_base="https://host/api/v3",
        channel=CHANNEL_ANY,
        asset_pattern="*.msi",
    ),
)


class TheRoundTrip(unittest.TestCase):
    def test_everything_survives(self):
        restored, problems = read_document(write_document(FULL), Settings())
        self.assertEqual((), problems)
        self.assertEqual(FULL.workspace_root, restored.workspace_root)
        self.assertEqual(FULL.bundle_prefix, restored.bundle_prefix)
        self.assertEqual(FULL.scripts_root, restored.scripts_root)
        self.assertEqual(dict(FULL.templates), dict(restored.templates))
        self.assertEqual(dict(FULL.scripts), dict(restored.scripts))
        self.assertEqual(dict(FULL.script_checks), dict(restored.script_checks))
        self.assertEqual(FULL.updates, restored.updates)

    def test_it_survives_actual_json(self):
        # dataclasses and Mappings are not JSON; the document has to be encodable
        # as it stands, or export works in a test and fails on a real file.
        raw = json.dumps(write_document(FULL), indent=2)
        restored, problems = read_document(json.loads(raw), Settings())
        self.assertEqual((), problems)
        self.assertEqual(FULL.updates, restored.updates)

    def test_defaults_are_written_out_rather_than_omitted(self):
        # Unlike the TOML writer. A reader cannot tell an omitted key from one
        # deliberately set to today's default, and a default that changes between
        # versions would silently rewrite the setting the file exists to preserve.
        document = write_document(Settings())
        self.assertEqual(DEFAULT_API_BASE, document["updates"]["api_base"])
        self.assertEqual(DEFAULT_ASSET_PATTERN, document["updates"]["asset_pattern"])
        self.assertIn("workspace_root", document["scaffold"])

    def test_it_says_what_it_is(self):
        document = write_document(Settings())
        self.assertEqual(KIND, document["kind"])
        self.assertEqual(SCHEMA, document["schema"])

    def test_a_document_written_under_a_former_name_is_not_complained_about(self):
        # The kind is a wire format. A document exported before a rename still says
        # the old thing, and a warning about the product's own former name is one
        # nobody can act on.
        for legacy in KNOWN_KINDS:
            with self.subTest(kind=legacy):
                document = write_document(FULL)
                document["kind"] = legacy
                settings, problems = read_document(document, Settings())
                self.assertEqual((), problems)
                self.assertEqual(FULL.bundle_prefix, settings.bundle_prefix)


class ReadingSomethingOdd(unittest.TestCase):
    def test_a_list_is_not_a_settings_document(self):
        settings, problems = read_document([1, 2, 3], FULL)
        self.assertEqual(FULL, settings)
        self.assertEqual(1, len(problems))
        self.assertIn("not a settings document", problems[0])

    def test_a_missing_section_keeps_what_is_already_set(self):
        # NOT the built-in defaults. A document silent about a setting is not
        # asking for it to be reset, and importing one written before a field
        # existed must not clear that field.
        settings, problems = read_document({"schema": SCHEMA, "kind": KIND}, FULL)
        self.assertEqual(FULL.bundle_prefix, settings.bundle_prefix)
        self.assertEqual(FULL.updates, settings.updates)
        self.assertEqual((), problems)

    def test_a_newer_schema_is_a_warning_and_the_rest_is_still_read(self):
        document = write_document(FULL)
        document["schema"] = SCHEMA + 99
        settings, problems = read_document(document, Settings())
        self.assertEqual(FULL.bundle_prefix, settings.bundle_prefix)
        self.assertTrue(any("schema" in problem for problem in problems))

    def test_the_wrong_kind_is_reported_but_not_fatal(self):
        document = write_document(FULL)
        document["kind"] = "something-else"
        settings, problems = read_document(document, Settings())
        self.assertEqual(FULL.bundle_prefix, settings.bundle_prefix)
        self.assertTrue(any("something-else" in problem for problem in problems))

    def test_a_section_of_the_wrong_type_is_reported_not_swallowed(self):
        for key in ("scaffold", "templates", "scripts", "script_checks", "updates"):
            with self.subTest(key=key):
                document = write_document(FULL)
                document[key] = "not an object"
                _, problems = read_document(document, FULL)
                self.assertTrue(
                    any(key in problem for problem in problems),
                    f"{key} was ignored without saying so: {problems}",
                )

    def test_a_non_boolean_check_is_reported(self):
        document = write_document(FULL)
        document["script_checks"] = {"react": "no"}
        settings, problems = read_document(document, Settings())
        self.assertNotIn("react", settings.script_checks)
        self.assertTrue(any("script_checks.react" in problem for problem in problems))

    def test_a_non_boolean_prerelease_flag_falls_back_and_reports(self):
        document = write_document(FULL)
        document["updates"].pop("channel", None)
        document["updates"]["include_prereleases"] = "yes"
        settings, problems = read_document(document, Settings())
        self.assertFalse(settings.updates.include_prereleases)
        self.assertTrue(any("include_prereleases" in problem for problem in problems))

    def test_a_pin_with_no_url_is_dropped_rather_than_saved_as_empty(self):
        # The TOML writer drops these, so keeping one here would produce a
        # document that does not survive being saved and re-read.
        document = write_document(FULL)
        document["templates"]["ghost"] = {"url": "", "ref": "v1"}
        settings, _ = read_document(document, Settings())
        self.assertNotIn("ghost", settings.templates)

    def test_an_empty_value_falls_back_to_the_built_in_default(self):
        document = write_document(FULL)
        document["scaffold"]["workspace_root"] = ""
        settings, _ = read_document(document, Settings())
        self.assertEqual(".", settings.workspace_root)


class ThroughARealFile(unittest.TestCase):
    def test_written_and_read_from_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(
                json.dumps(write_document(FULL), indent=2) + "\n", encoding="utf-8"
            )
            restored, problems = read_document(
                json.loads(path.read_text(encoding="utf-8")), Settings()
            )
        self.assertEqual((), problems)
        self.assertEqual(FULL.updates, restored.updates)
        self.assertEqual(dict(FULL.templates), dict(restored.templates))


if __name__ == "__main__":
    unittest.main()
