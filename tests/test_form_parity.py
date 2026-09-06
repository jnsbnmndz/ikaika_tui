"""The run panel answers a form the way the WPF dialog does.

Two front ends over the same commands only works if they mean the same thing by
the same form. These are the rules where "nearly" is a different program:

  An untouched field binds NOTHING. Not an empty string, not the default made
  explicit - nothing. `flutter/build-release` refuses a run outright when an
  argument that does not apply to the chosen platform is bound, and its
  remembered choices key off which arguments were bound at all, so a form that
  always passed `-Platform` would defeat the memory it exists to use.

  A dropdown opens on a row that NAMES its default and binds nothing. Showing
  the default and passing it look identical and are not.

  The preview says exactly what will run, by the same rules, because a preview
  that disagrees with the run is worse than none.

The WPF side of each is pinned in the toolkit's own `manifest.Tests.ps1`.
"""

import unittest

from company_tui.domain.options import OptionKind
from company_tui.domain.script_config import (
    actions_from,
    action_options,
    command_preview,
)
from company_tui.presentation.session import RunSession

DOCUMENT = {
    "version": "1.0.0+1",
    "name": "demo",
    "title": "Demo",
    "description": "A demo",
    "rules": {
        "global": ["flag", "type", "required", "description", "default"],
        "string": ["allowed_values"],
        "array": ["allowed_values"],
        "number": ["min", "max"],
    },
    "config": {
        "git": {
            "pull-updates": {
                "description": "Pulls updates.",
                "args": [
                    {"flag": "Branch", "type": "string", "default": "development",
                     "allowed_values": ["development", "main"]},
                    {"flag": "Targets", "type": "array", "default": "",
                     "allowed_values": ["windows", "web"]},
                    {"flag": "Message", "type": "string", "default": ""},
                    {"flag": "Prune", "type": "boolean", "default": "false"},
                    {"flag": "Preview", "type": "boolean", "default": "false"},
                ],
                "command-after-success": ["pwsh -File ${root}/script.ps1 git/pull-updates"],
            }
        }
    },
}


def the_action():
    return actions_from(DOCUMENT)[0]


def opened_form() -> RunSession:
    """A session with the form loaded and nothing touched."""
    session = RunSession(1, "Pull Updates", workflow=lambda: None)
    session.load("Pull Updates", action_options(the_action(), "/proj"))
    return session


class UntouchedFormTest(unittest.TestCase):
    def test_a_dropdown_binds_nothing_until_it_is_answered(self):
        self.assertEqual("", opened_form().values["Branch"])

    def test_a_checklist_binds_nothing_until_something_is_ticked(self):
        self.assertEqual("", opened_form().values["Targets"])

    def test_a_text_field_binds_nothing(self):
        self.assertEqual("", opened_form().values["Message"])

    def test_a_switch_is_off(self):
        values = opened_form().values
        self.assertFalse(values["Prune"])
        self.assertFalse(values["Preview"])

    def test_the_whole_form_adds_up_to_the_bare_command(self):
        # The point of every rule above, in one assertion: opening the form and
        # pressing Run is the same as typing the command with no arguments.
        session = opened_form()
        self.assertEqual(
            ".\\script.ps1 git/pull-updates",
            command_preview(the_action(), session.values),
        )


class DefaultIsShownNotBoundTest(unittest.TestCase):
    def test_the_option_still_carries_the_default_to_name_the_row_with(self):
        # Dropped from the VALUES, kept on the option: the row has to say
        # "(default: development)" while binding nothing.
        option = next(
            o for o in action_options(the_action(), "/proj") if o.key == "Branch"
        )
        self.assertEqual("development", option.default)
        self.assertEqual("", opened_form().values["Branch"])


class PreviewTest(unittest.TestCase):
    def test_it_omits_an_unanswered_field_rather_than_passing_it_empty(self):
        line = command_preview(the_action(), {"Branch": "main", "Message": ""})
        self.assertIn("-Branch main", line)
        self.assertNotIn("-Message", line)

    def test_a_switch_appears_only_when_it_is_on(self):
        line = command_preview(the_action(), {"Prune": True, "Preview": False})
        self.assertIn("-Prune", line)
        self.assertNotIn("-Preview", line)

    def test_a_value_with_a_space_is_quoted(self):
        line = command_preview(the_action(), {"Message": "two words"})
        self.assertIn("-Message 'two words'", line)

    def test_a_multi_select_is_comma_joined(self):
        line = command_preview(the_action(), {"Targets": "windows,web"})
        self.assertIn("-Targets windows,web", line)

    def test_it_names_the_command_the_way_it_would_be_typed(self):
        self.assertTrue(
            command_preview(the_action(), {}).startswith(".\\script.ps1 git/pull-updates")
        )


class StaleAnswerTest(unittest.TestCase):
    def test_an_answer_no_longer_offered_is_dropped_rather_than_restored(self):
        # A fetched list changes between runs - the branch answered last time is
        # exactly the one somebody has since deleted - and a Select built with a
        # value outside its own options raises on mount and takes the app down.
        session = opened_form()
        session.values["Branch"] = "a-branch-that-went-away"
        session.load("Pull Updates", action_options(the_action(), "/proj"))
        self.assertEqual("", session.values["Branch"])

    def test_an_answer_still_offered_survives(self):
        session = opened_form()
        session.values["Branch"] = "main"
        session.load("Pull Updates", action_options(the_action(), "/proj"))
        self.assertEqual("main", session.values["Branch"])

    def test_a_multi_select_keeps_only_the_members_that_survived(self):
        session = opened_form()
        session.values["Targets"] = "windows,gone,web"
        session.load("Pull Updates", action_options(the_action(), "/proj"))
        self.assertEqual("windows,web", session.values["Targets"])

    def test_a_free_text_answer_is_left_alone(self):
        session = opened_form()
        session.values["Message"] = "anything at all"
        session.load("Pull Updates", action_options(the_action(), "/proj"))
        self.assertEqual("anything at all", session.values["Message"])


class ControlChoiceTest(unittest.TestCase):
    """Which control each declared type gets, matching Get-ParamControlKind."""

    def test_every_type_lands_on_the_control_the_form_would_use(self):
        options = {o.key: o.kind for o in action_options(the_action(), "/proj")}
        self.assertIs(OptionKind.CHOICE, options["Branch"])
        self.assertIs(OptionKind.MULTI, options["Targets"])
        self.assertIs(OptionKind.TEXT, options["Message"])
        self.assertIs(OptionKind.BOOLEAN, options["Prune"])
        self.assertIs(OptionKind.PATH, options["root"])

    def test_a_secret_never_reaches_the_form(self):
        # The manifest omits it, so there is nothing here to render. Asserted so
        # that emitting one would fail here rather than being noticed on screen.
        flags = {o.key.lower() for o in action_options(the_action(), "/proj")}
        for banned in ("password", "secret", "token", "passphrase"):
            self.assertNotIn(banned, flags)

class FetchedChoicesTest(unittest.TestCase):
    """A list the document does not hold, and where it comes from instead."""

    DOC = {
        "version": "1.0.0+1", "name": "d", "title": "D", "description": "d",
        "rules": {"global": ["flag", "type", "required", "description", "default",
                             "choices"],
                  "string": ["allowed_values"]},
        "config": {"git": {"pull-updates": {"args": [
            {"flag": "Branch", "type": "string", "default": "development",
             "choices": "pwsh -File ${root}/script.ps1 choices git/pull-updates Branch"},
            {"flag": "Message", "type": "string", "default": ""},
        ]}}},
    }

    def argument(self, flag="Branch"):
        action = actions_from(self.DOC)[0]
        return next(a for a in action.arguments if a.flag == flag)

    def test_the_command_is_read_off_the_document(self):
        self.assertIn("choices git/pull-updates Branch", self.argument().choices_command)

    def test_it_holds_no_values_of_its_own(self):
        # The whole point: nothing local is written down.
        self.assertEqual((), self.argument().allowed_values)

    def test_an_argument_with_no_such_command_is_unaffected(self):
        self.assertEqual("", self.argument("Message").choices_command)

    def test_without_values_it_is_a_text_box_until_they_arrive(self):
        # The desktop form falls back the same way when a provider answers nothing,
        # so a fetch that fails costs a picker rather than the whole form.
        options = {o.key: o.kind for o in action_options(actions_from(self.DOC)[0], "/p")}
        self.assertIs(OptionKind.TEXT, options["Branch"])

    def test_with_values_filled_in_it_becomes_the_dropdown(self):
        from dataclasses import replace

        action = actions_from(self.DOC)[0]
        filled = replace(
            action,
            arguments=tuple(
                replace(a, allowed_values=("development", "main"))
                if a.flag == "Branch" else a
                for a in action.arguments
            ),
        )
        options = {o.key: o for o in action_options(filled, "/p")}
        self.assertIs(OptionKind.CHOICE, options["Branch"].kind)
        self.assertEqual(("development", "main"), options["Branch"].choices)
        # And it still opens bound to nothing, naming its default.
        self.assertEqual("development", options["Branch"].default)

class RowLabelTest(unittest.TestCase):
    """`-Branch   [String]`, the way the desktop form prints it."""

    DOC = {
        "version": "1.0.0+1", "name": "d", "title": "D", "description": "d",
        "rules": {"global": ["flag", "type", "required", "description", "default",
                             "label"]},
        "config": {"git": {"manage-tags": {"args": [
            {"flag": "Branch", "type": "string", "label": "-Branch   [String]"},
            {"flag": "apiEndpoint", "type": "string"},
            {"flag": "ManifestPath", "type": "file", "label": "-ManifestPath   [String]"},
            {"flag": "StageDir", "type": "path", "label": "-StageDir   [String]"},
        ]}}},
    }

    def options(self):
        return {o.key: o for o in action_options(actions_from(self.DOC)[0], "/p")}

    def test_the_document_s_own_label_is_used(self):
        # A form whose point is that anything picked can be typed next time should
        # say the thing you would type.
        self.assertEqual("-Branch   [String]", self.options()["Branch"].label)

    def test_a_document_that_names_no_label_still_reads_well(self):
        # React Native's generators write flags for people, not for a shell.
        self.assertEqual("Api Endpoint", self.options()["apiEndpoint"].label)

    def test_a_file_gets_the_file_picker_and_a_directory_the_directory_one(self):
        # Browsing for a manifest in a tree that hides files finds nothing.
        self.assertIs(OptionKind.FILE, self.options()["ManifestPath"].kind)
        self.assertIs(OptionKind.PATH, self.options()["StageDir"].kind)

    def test_both_are_still_typeable(self):
        # Browsing is the shortcut, not the only way in.
        for key in ("ManifestPath", "StageDir"):
            self.assertTrue(self.options()[key].is_input)

if __name__ == "__main__":
    unittest.main()
