"""What a script repository's document is read as.

Focused on the three things a project's own config added, each of which is
silent when it is wrong: a section grouping that decides the menu depth, an
action description that decides what a card says, and a `path` type that decides
whether a field is a picker or a blank box somebody has to remember the answer to.
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


if __name__ == "__main__":
    unittest.main()
