"""What a script repository's document is read as.

Focused on what a project's own config added, each of it silent when wrong: a
section grouping that decides the menu depth, an action description that decides
what a card says, and the control each declared type is offered as - a `path`
that is a picker rather than a blank box, an `array` that is tick boxes rather
than a dropdown accepting one where several were meant, and a `number` that is a
numeric field rather than advice printed under a text one.
"""

import unittest

from company_tui.domain.options import OptionKind
from company_tui.domain.script_config import (
    ScriptAction,
    action_options,
    actions_from,
    sections_from,
)

DOCUMENT = {
    "version": "1.0.0+1",
    "name": "demo",
    "title": "Demo",
    "description": "A demo",
    "rules": {
        "global": ["flag", "type", "required", "description", "default"],
        "string": ["allowed_values"],
        "path": ["allowed_values"],
        "boolean": [],
    },
    "config": {
        "git": {
            "pull-updates": {
                "description": "Pulls updates from another branch.",
                "args": [
                    {"flag": "Branch", "type": "string", "default": "development",
                     "allowed_values": ["development", "main"]},
                    {"flag": "Prune", "type": "boolean", "default": "false"},
                ],
                "command-after-success": ["pwsh -File ${root}/script.ps1 git/pull-updates"],
            },
            "check-all": {
                "description": "Runs every check.",
                "args": [],
                "command-after-success": ["pwsh -File ${root}/script.ps1 git/check-all"],
            },
        },
        "windows": {
            "setup-signing": {
                "description": "Sets up the signing certificates.",
                "args": [{"flag": "CertDir", "type": "path", "default": "certs"}],
                "command-after-success": ["pwsh -File ${root}/script.ps1 windows/setup-signing"],
            }
        },
    },
}


class SectionsTest(unittest.TestCase):
    def test_groups_actions_by_the_section_that_declared_them(self):
        sections = sections_from(actions_from(DOCUMENT))
        self.assertEqual(["git", "windows"], [s.key for s in sections])
        self.assertEqual(2, len(sections[0].actions))

    def test_keeps_declaration_order_rather_than_sorting(self):
        # The document's order is the author's order; re-sorting it would put the
        # menu in an order nobody chose and make it move when a section is renamed.
        document = {**DOCUMENT, "config": {
            "windows": DOCUMENT["config"]["windows"],
            "git": DOCUMENT["config"]["git"],
        }}
        self.assertEqual(
            ["windows", "git"], [s.key for s in sections_from(actions_from(document))]
        )

    def test_names_a_section_the_way_a_menu_would(self):
        section = sections_from(actions_from(DOCUMENT))[0]
        self.assertEqual("Git", section.name)

    def test_counts_its_actions_in_words_that_agree_with_the_number(self):
        sections = {s.key: s for s in sections_from(actions_from(DOCUMENT))}
        self.assertEqual("2 commands", sections["git"].summary)
        self.assertEqual("1 command", sections["windows"].summary)

    def test_a_document_with_no_config_offers_nothing(self):
        self.assertEqual((), sections_from(actions_from({"name": "demo"})))


class DescriptionTest(unittest.TestCase):
    def test_an_action_says_what_the_document_says_it_is_for(self):
        action = next(a for a in actions_from(DOCUMENT) if a.key == "pull-updates")
        self.assertEqual("Pulls updates from another branch.", action.summary)
        self.assertEqual("Pulls updates from another branch.", action.detail)

    def test_falls_back_to_the_section_when_the_document_describes_nothing(self):
        # Ten commands in one section would otherwise all read "Runs the git
        # workflow", which is true of each and useful about none.
        action = ScriptAction(section="git", key="check-all")
        self.assertEqual("Runs the git workflow", action.summary)


class PathKindTest(unittest.TestCase):
    def test_a_path_argument_is_offered_as_a_path_and_not_as_text(self):
        action = next(a for a in actions_from(DOCUMENT) if a.key == "setup-signing")
        options = {o.key: o for o in action_options(action, "/proj")}
        self.assertIs(OptionKind.PATH, options["CertDir"].kind)

    def test_a_declared_set_of_paths_is_still_offered_as_the_set(self):
        # A choice is a better control than a picker when the answers are known,
        # and this is the ordering that decides which one wins.
        document = {**DOCUMENT, "config": {"windows": {"setup-signing": {
            "args": [{"flag": "CertDir", "type": "path", "default": "a",
                      "allowed_values": ["a", "b"]}],
        }}}}
        action = actions_from(document)[0]
        options = {o.key: o for o in action_options(action, "/proj")}
        self.assertIs(OptionKind.CHOICE, options["CertDir"].kind)

    def test_the_project_row_is_still_the_first_thing_asked(self):
        action = next(a for a in actions_from(DOCUMENT) if a.key == "pull-updates")
        options = action_options(action, "/proj")
        self.assertEqual("root", options[0].key)
        self.assertEqual("/proj", options[0].default)


class ArgumentTest(unittest.TestCase):
    def test_a_choice_keeps_the_values_the_document_allowed(self):
        # The bug this guards produced one allowed value that was the whole list
        # printed as a string, and a default that then resolved to nothing.
        action = next(a for a in actions_from(DOCUMENT) if a.key == "pull-updates")
        options = {o.key: o for o in action_options(action, "/proj")}
        self.assertEqual(("development", "main"), options["Branch"].choices)
        self.assertEqual("development", options["Branch"].default)

    def test_a_boolean_reaches_the_command_line_as_a_word_either_way(self):
        action = next(a for a in actions_from(DOCUMENT) if a.key == "pull-updates")
        self.assertEqual(
            "false", action.references_from({"Prune": False})["pull-updates.args.Prune"]
        )
        self.assertEqual(
            "true", action.references_from({"Prune": True})["pull-updates.args.Prune"]
        )



class MultiSelectTest(unittest.TestCase):
    """Several of a known set is not one of a known set."""

    DOC = {
        "version": "1.0.0+1", "name": "d", "title": "D", "description": "d",
        "rules": {"global": ["flag", "type", "required", "description", "default"],
                  "array": ["allowed_values"], "number": ["min", "max"]},
        "config": {"build": {"release": {"args": [
            {"flag": "Targets", "type": "array", "default": "windows",
             "allowed_values": ["windows", "android", "web"]},
            {"flag": "Extra", "type": "array", "default": ""},
            {"flag": "Port", "type": "number", "default": "8080", "min": 1024, "max": 65535},
            {"flag": "Count", "type": "number", "default": "1"},
        ]}}},
    }

    def options(self):
        action = actions_from(self.DOC)[0]
        return {o.key: o for o in action_options(action, "/proj")}

    def test_an_array_with_a_declared_set_is_offered_as_tick_boxes(self):
        # A dropdown here accepts one where two were meant, and says nothing
        # about several being allowed.
        option = self.options()["Targets"]
        self.assertIs(OptionKind.MULTI, option.kind)
        self.assertEqual(("windows", "android", "web"), option.choices)

    def test_an_array_with_no_declared_set_stays_free_text(self):
        # Nothing to tick. Comma-joined text is what a list without a vocabulary is.
        self.assertIs(OptionKind.TEXT, self.options()["Extra"].kind)

    def test_a_number_is_a_number_field_and_not_a_hint_on_a_text_one(self):
        self.assertIs(OptionKind.NUMBER, self.options()["Port"].kind)

    def test_a_declared_range_reaches_the_form(self):
        option = self.options()["Port"]
        self.assertEqual((1024, 65535), (option.minimum, option.maximum))
        self.assertEqual("A number between 1024 and 65535.", option.help)

    def test_a_range_is_said_in_whole_numbers(self):
        # The document wrote 1024, not 1024.0, and the help is read by a person.
        self.assertNotIn(".0", self.options()["Port"].help)

    def test_a_number_with_no_range_still_says_what_it_is(self):
        self.assertEqual("A number.", self.options()["Count"].help)

    def test_a_comma_joined_answer_validates_against_the_declared_set(self):
        # This is what the tick boxes produce, so it has to be what the rules accept.
        argument = actions_from(self.DOC)[0].arguments[0]
        self.assertEqual("", argument.reason_to_refuse("windows,android"))
        self.assertIn("nintendo", argument.reason_to_refuse("windows,nintendo"))

    def test_a_multi_answer_reaches_the_command_line_comma_joined(self):
        action = actions_from(self.DOC)[0]
        refs = action.references_from({"Targets": "windows,web"})
        self.assertEqual("windows,web", refs["release.args.Targets"])

if __name__ == "__main__":
    unittest.main()
