"""Editing the commands a project declares, without disturbing the rest of its file."""

import json
import tempfile
import unittest
from pathlib import Path

from company_tui.domain import json_document, naming
from company_tui.domain.commands import (
    Command,
    commands_from,
    is_key,
    still_reads,
    write_commands,
)
from company_tui.domain.config import ConfigScope
from company_tui.domain.script_config import actions_from
from company_tui.infrastructure.config import FileConfig

MANIFEST = {
    "version": "1.0.0",
    "name": "acme",
    "title": "Acme",
    "rules": {"string": {"allowed_regex": "^[a-z]+$"}},
    "config": {
        "build": {
            "description": "Build it",
            "command-after-success": ["npm run build"],
            "messages": {"success": "done"},
        },
        "scaffold": {
            "screen": {
                "template": "templates/screen.tsx",
                "path": "${root}/src",
                "filename": "${screen.args.name}.tsx",
                "args": {"name": {"type": "string"}},
                "command-after-success": ["node finish.mjs"],
            },
            "service": {
                "template": "templates/service.ts",
                "command-after-success": ["node service.mjs"],
            },
        },
    },
}


def _document(source=None):
    return json_document.load(json.dumps(source or MANIFEST, indent=2))


class ReadingThem(unittest.TestCase):
    def test_a_section_that_is_itself_an_action_has_no_key(self):
        build = commands_from(_document())[0]
        self.assertEqual("build", build.section)
        self.assertEqual("", build.key)
        self.assertEqual("build", build.identifier)

    def test_a_group_gives_each_of_its_own_a_key(self):
        read = commands_from(_document())
        self.assertEqual(
            ["build", "scaffold.screen", "scaffold.service"],
            [one.identifier for one in read],
        )

    def test_what_it_edits_comes_back_read(self):
        build = commands_from(_document())[0]
        self.assertEqual("Build it", build.description)
        self.assertEqual(("npm run build",), build.commands)
        self.assertFalse(build.interactive)
        self.assertEqual("", build.view)

    def test_what_it_does_not_edit_is_named_rather_than_dropped(self):
        # So the page can say what it is keeping rather than leaving somebody to
        # wonder where their template went.
        read = {one.identifier: one for one in commands_from(_document())}
        self.assertEqual(("messages",), read["build"].kept)
        self.assertEqual(
            ("template", "path", "filename", "args"), read["scaffold.screen"].kept
        )

    def test_each_remembers_where_it_came_from(self):
        for one in commands_from(_document()):
            self.assertEqual(one.identifier, one.was)

    def test_a_document_declaring_none_reads_as_none(self):
        self.assertEqual((), commands_from({}))
        self.assertEqual((), commands_from({"config": "build"}))

    def test_a_name_that_could_not_be_addressed_is_not_a_name(self):
        # `section.key` is how an action is addressed and how its arguments are
        # written, so a dot or a space in one is two names.
        for value in ("build", "react_native", "a-b"):
            self.assertTrue(is_key(value), value)
        for value in ("", "a b", "a.b", "a/b", "${x}", None, 7):
            self.assertFalse(is_key(value), repr(value))


class WritingThem(unittest.TestCase):
    def _after(self, wanted, source=None):
        document = _document(source)
        problems = write_commands(document, wanted)
        return document, problems

    def test_a_command_can_be_changed(self):
        held = list(commands_from(_document()))
        held[0] = Command(
            section="build",
            description="Build it",
            commands=("npm ci", "npm run build"),
            view="browser",
            was="build",
        )
        document, problems = self._after(held)
        self.assertEqual((), problems)
        build = json_document.read(document, ("config", "build"))
        self.assertEqual(["npm ci", "npm run build"], build["command-after-success"])
        self.assertEqual("browser", build["view"])

    def test_one_can_be_added(self):
        held = [*commands_from(_document()),
                Command(section="generate", key="hook", commands=("node hook.mjs",))]
        document, problems = self._after(held)
        self.assertEqual((), problems)
        self.assertIn("generate.hook", [one.identifier for one in commands_from(document)])

    def test_one_can_be_deleted(self):
        held = [one for one in commands_from(_document()) if one.identifier != "build"]
        document, _ = self._after(held)
        self.assertNotIn("build", [one.identifier for one in commands_from(document)])

    def test_a_group_emptied_by_a_delete_goes_with_it(self):
        held = [one for one in commands_from(_document()) if one.section != "scaffold"]
        document, _ = self._after(held)
        self.assertNotIn("scaffold", document["config"])

    def test_a_rename_keeps_everything_the_builder_does_not_edit(self):
        # The whole reason `was` travels: rebuilding it instead of moving it would
        # lose the template and the arguments, silently.
        held = [
            one
            for one in commands_from(_document())
            if one.identifier != "scaffold.screen"
        ]
        held.append(
            Command(
                section="generate",
                key="page",
                commands=("node finish.mjs",),
                was="scaffold.screen",
            )
        )
        document, _ = self._after(held)
        moved = json_document.read(document, ("config", "generate", "page"))
        self.assertEqual("templates/screen.tsx", moved["template"])
        self.assertEqual({"name": {"type": "string"}}, moved["args"])
        self.assertIsNone(json_document.read(document, ("config", "scaffold", "screen")))

    def test_a_rename_says_what_it_broke(self):
        # An action's arguments are written `${<its own name>.args.<flag>}`, and an
        # unanswered reference is left in place rather than blanked - so what fails
        # is the run, with the text still in it.
        held = [
            Command(
                section="generate",
                key="page",
                commands=("node finish.mjs",),
                was="scaffold.screen",
            )
        ]
        _, problems = self._after(held)
        self.assertTrue(any("${screen." in one for one in problems))
        self.assertTrue(any("by hand" in one for one in problems))

    def test_a_rename_with_nothing_pointing_at_itself_says_nothing(self):
        held = [
            Command(
                section="generate",
                key="thing",
                commands=("node service.mjs",),
                was="scaffold.service",
            )
        ]
        _, problems = self._after(held)
        self.assertEqual((), problems)

    def test_a_name_it_cannot_address_is_refused_and_said(self):
        _, problems = self._after([Command(section="a b", commands=("x",))])
        self.assertTrue(any("not a usable name" in one for one in problems))

    def test_the_same_name_twice_is_one_of_them(self):
        held = [Command(section="build", commands=("a",)),
                Command(section="build", commands=("b",))]
        _, problems = self._after(held)
        self.assertTrue(any("named twice" in one for one in problems))

    def test_nothing_it_does_not_edit_is_touched(self):
        document, _ = self._after(list(commands_from(_document())))
        self.assertEqual("1.0.0", document["version"])
        self.assertEqual("Acme", document["title"])
        self.assertEqual(MANIFEST["rules"], document["rules"])
        self.assertEqual({"success": "done"}, document["config"]["build"]["messages"])

    def test_an_empty_description_is_not_written_as_an_empty_string(self):
        held = [Command(section="build", commands=("npm run build",), was="build")]
        document, _ = self._after(held)
        self.assertNotIn("description", document["config"]["build"])

    def test_a_flag_turned_off_is_removed_rather_than_written_false(self):
        source = json.loads(json.dumps(MANIFEST))
        source["config"]["build"]["interactive"] = True
        source["config"]["build"]["view"] = "browser"
        held = [Command(section="build", commands=("npm run build",), was="build")]
        document, _ = self._after(held, source)
        self.assertNotIn("interactive", document["config"]["build"])
        self.assertNotIn("view", document["config"]["build"])


class TheRunnerStillReadsIt(unittest.TestCase):
    """The reader the menus are built from, asked about what was just written."""

    def test_what_was_written_is_what_runs(self):
        held = [
            Command(section="build", commands=("npm ci", "npm run build"), was="build"),
            Command(section="generate", key="hook", commands=("node hook.mjs",),
                    interactive=True),
        ]
        document = _document()
        write_commands(document, held)
        read = actions_from(document)
        self.assertEqual(
            ["build", "generate.hook"], [one.identifier for one in read]
        )
        self.assertEqual(("npm ci", "npm run build"), read[0].after_success)
        self.assertTrue(read[1].interactive)

    def test_it_says_so_when_it_can_still_be_read(self):
        document = _document()
        write_commands(document, list(commands_from(document)))
        self.assertTrue(still_reads(document))

    def test_a_document_with_no_commands_at_all_is_not_a_failure(self):
        self.assertTrue(still_reads({}))


class TheFileItselfIsLeftAlone(unittest.TestCase):
    def test_the_indent_the_project_chose_is_the_indent_it_keeps(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / naming.SCRIPT_MANIFEST
            path.write_text(json.dumps(MANIFEST, indent=4), encoding="utf-8")
            source = path.read_text(encoding="utf-8")
            document = json_document.load(source)
            write_commands(document, list(commands_from(document)))
            written = json_document.dump(document, json_document.detect_indent(source))
            self.assertIn('\n    "version"', written)
            self.assertNotIn('\n  "version"', written)

    def test_the_manifest_is_found_by_either_of_its_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(naming.manifest_in(root))
            (root / "ikaika.script.json").write_text("{}", encoding="utf-8")
            self.assertIsNotNone(naming.manifest_in(root))


class TheProjectBeingWorkedOnWins(unittest.TestCase):
    """The third settings file, and the one that beats the other two."""

    def _three(self, folder):
        root = Path(folder)
        for name in ("tool", "proj", "home"):
            (root / name).mkdir()
        (root / "home" / "dti.toml").write_text(
            '[scaffold]\nbundle_prefix = "com.user"\n', encoding="utf-8"
        )
        (root / "tool" / "dti.toml").write_text(
            '[scaffold]\nbundle_prefix = "com.tool"\n', encoding="utf-8"
        )
        return root, FileConfig(root / "tool" / "dti.toml", root / "home" / "dti.toml")

    def test_with_nothing_driven_it_is_the_two_it_always_was(self):
        with tempfile.TemporaryDirectory() as folder:
            _, config = self._three(folder)
            self.assertEqual("com.tool", config.bundle_prefix())
            self.assertEqual(
                [ConfigScope.PROJECT, ConfigScope.USER], list(config.scopes())
            )

    def test_the_project_being_worked_on_beats_both(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self._three(folder)
            (root / "proj" / "dti.toml").write_text(
                '[scaffold]\nbundle_prefix = "com.proj"\n', encoding="utf-8"
            )
            config.follow(root / "proj")
            self.assertEqual("com.proj", config.bundle_prefix())
            self.assertEqual(root / "proj" / "dti.toml", config.active_location())

    def test_a_driven_project_with_no_file_changes_nothing(self):
        # Wins outright where it exists, and is simply not there where it does not.
        with tempfile.TemporaryDirectory() as folder:
            root, config = self._three(folder)
            config.follow(root / "proj")
            self.assertEqual("com.tool", config.bundle_prefix())

    def test_it_is_offered_as_a_place_to_save_only_while_there_is_one(self):
        # A "save to" naming a file that does not apply is a control that lies.
        with tempfile.TemporaryDirectory() as folder:
            root, config = self._three(folder)
            config.follow(root / "proj")
            self.assertIn(ConfigScope.DRIVEN, config.scopes())
            self.assertEqual(root / "proj" / "dti.toml", config.location(ConfigScope.DRIVEN))
            config.follow(None)
            self.assertNotIn(ConfigScope.DRIVEN, config.scopes())

    def test_walking_into_another_project_changes_the_answer_without_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root, config = self._three(folder)
            (root / "proj" / "dti.toml").write_text(
                '[scaffold]\nbundle_prefix = "com.proj"\n', encoding="utf-8"
            )
            (root / "other").mkdir()
            (root / "other" / "dti.toml").write_text(
                '[scaffold]\nbundle_prefix = "com.other"\n', encoding="utf-8"
            )
            config.follow(root / "proj")
            self.assertEqual("com.proj", config.bundle_prefix())
            config.follow(root / "other")
            self.assertEqual("com.other", config.bundle_prefix())

    def test_a_port_that_never_heard_of_it_can_still_be_told(self):
        from company_tui.domain.config import ConfigPort

        self.assertIsNone(ConfigPort.follow(object(), Path(".")))
        self.assertEqual(
            (ConfigScope.PROJECT, ConfigScope.USER), ConfigPort.scopes(object())
        )
