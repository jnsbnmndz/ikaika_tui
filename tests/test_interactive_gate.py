"""Two keys turn this on, the setting travels, and the rows are a real list."""

import asyncio
import unittest
from dataclasses import replace
from pathlib import Path

from textual.app import App
from textual.widgets import Static

from company_tui.capabilities.advanced import INTERACTIVE_KEY
from company_tui.domain.config import Settings
from company_tui.domain.interactive import Listing, ListView, Row
from company_tui.domain.ports import ProcessResult
from company_tui.domain.script_config import ScriptAction, actions_from
from company_tui.domain.settings_document import read_document, write_document
from company_tui.infrastructure.config import render
from company_tui.presentation.plain_console import PlainConsole
from company_tui.presentation.screens import PickRow, PickScreen
from company_tui.templates.scripts import _list_view
from company_tui.templates.services import PackServices


class _View(ListView):
    async def show(self, listing):
        return None

    def close(self):
        pass


class _Console:
    def __init__(self, view=None):
        self._view = view

    def list_view(self):
        return self._view


class _Config:
    def __init__(self, on):
        self._on = on

    def interactive_lists(self):
        return self._on


class _Services:
    def __init__(self, on, view):
        self.config = _Config(on)
        self.console = _Console(view)


class BothKeysOrNeither(unittest.TestCase):
    """The gate. `None` is what leaves a run byte for byte as it was."""

    def _view(self, *, setting: bool, declared: bool):
        action = ScriptAction(section="acc", key="browse", interactive=declared)
        return _list_view(action, _Services(setting, _View()))

    def test_setting_off_is_no_view_even_when_the_command_asks(self):
        self.assertIsNone(self._view(setting=False, declared=True))

    def test_setting_on_is_no_view_for_a_command_that_does_not_ask(self):
        self.assertIsNone(self._view(setting=True, declared=False))

    def test_neither_is_no_view(self):
        self.assertIsNone(self._view(setting=False, declared=False))

    def test_both_is_a_view(self):
        self.assertIsNotNone(self._view(setting=True, declared=True))

    def test_a_console_that_cannot_draw_one_still_gets_none(self):
        action = ScriptAction(section="a", key="b", interactive=True)
        self.assertIsNone(_list_view(action, _Services(True, None)))

    def test_plain_stdout_never_offers_one(self):
        self.assertIsNone(PlainConsole().list_view())


class TheManifestHalf(unittest.TestCase):
    def test_a_command_is_not_interactive_unless_it_says_so(self):
        self.assertFalse(ScriptAction(section="x").interactive)

    def test_only_a_real_true_counts(self):
        for value in (True, "true", 1, "yes", None, 0):
            document = {
                "config": {"acc": {"browse": {"command-after-success": ["x"],
                                              "interactive": value}}}
            }
            actions = actions_from(document)
            self.assertEqual(
                value is True, actions[0].interactive, f"interactive: {value!r}"
            )

    def test_a_manifest_that_never_heard_of_it_still_reads(self):
        document = {"config": {"acc": {"browse": {"command-after-success": ["x"]}}}}
        self.assertFalse(actions_from(document)[0].interactive)

    def test_keys_from_a_later_version_are_still_ignored(self):
        document = {
            "config": {"acc": {"browse": {"command-after-success": ["x"],
                                          "interactive": True,
                                          "interactive-columns": ["a", "b"]}}}
        }
        self.assertTrue(actions_from(document)[0].interactive)


class TheSettingTravels(unittest.TestCase):
    def test_it_is_off_out_of_the_box(self):
        self.assertFalse(Settings().interactive_lists)

    def test_the_document_carries_it_both_ways(self):
        for value in (True, False):
            document = write_document(replace(Settings(), interactive_lists=value))
            read, problems = read_document(document, Settings())
            self.assertEqual(value, read.interactive_lists)
            self.assertEqual((), problems)

    def test_a_document_that_predates_it_keeps_what_is_set(self):
        document = write_document(Settings())
        del document["experimental"]
        read, problems = read_document(document, replace(Settings(), interactive_lists=True))
        self.assertTrue(read.interactive_lists)
        self.assertEqual((), problems)

    def test_a_value_that_is_not_a_boolean_is_reported_not_guessed(self):
        document = write_document(Settings())
        document["experimental"]["interactive_lists"] = "yes"
        read, problems = read_document(document, Settings())
        self.assertFalse(read.interactive_lists)
        self.assertTrue(any("interactive_lists" in p for p in problems))

    def test_the_settings_file_only_mentions_it_when_it_is_on(self):
        self.assertNotIn("interactive_lists", render(Settings()))
        self.assertIn(
            "interactive_lists = true",
            render(replace(Settings(), interactive_lists=True)),
        )

    def test_advanced_names_the_same_key_the_settings_do(self):
        self.assertEqual("interactive_lists", INTERACTIVE_KEY)


class TheListIsAList(unittest.IsolatedAsyncioTestCase):
    """Arrow keys and Enter, not log text."""

    class _App(App):
        pass

    LISTING = Listing(
        title="ACC / Project Files",
        hint="Enter opens",
        rows=(
            Row("1", "00_BIM Coordination", "folder"),
            Row("10", "Deck.pptx", "file", "v1  97 MB"),
        ),
    )

    async def test_every_row_is_rendered_and_says_what_it_is(self):
        app = self._App()
        async with app.run_test() as pilot:
            screen = PickScreen(self.LISTING)
            await app.push_screen(screen)
            await pilot.pause()
            rows = list(screen.query(PickRow))
            self.assertEqual(["1", "10"], [row.row.id for row in rows])
            labels = [str(s.render()) for s in screen.query(Static)]
            self.assertTrue(any("00_BIM Coordination" in line for line in labels))
            self.assertTrue(any("v1  97 MB" in line for line in labels))
            self.assertTrue(any("Enter opens" in line for line in labels))

    async def test_enter_answers_with_that_row_s_own_id(self):
        app = self._App()
        answer = {}
        async with app.run_test() as pilot:
            async def ask():
                answer["picked"] = await app.push_screen_wait(PickScreen(self.LISTING))

            app.run_worker(ask())
            for _ in range(4):
                await pilot.pause()
            await pilot.press("down")       # the second row
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
        self.assertEqual("10", answer.get("picked"))

    async def test_escape_answers_with_nothing(self):
        app = self._App()
        answer = {}
        async with app.run_test() as pilot:
            async def ask():
                answer["picked"] = await app.push_screen_wait(PickScreen(self.LISTING))

            app.run_worker(ask())
            for _ in range(4):
                await pilot.pause()
            await pilot.press("escape")
            for _ in range(4):
                await pilot.pause()
        self.assertIn("picked", answer)
        self.assertIsNone(answer["picked"])

    async def test_a_listing_with_no_rows_says_so_rather_than_drawing_nothing(self):
        app = self._App()
        async with app.run_test() as pilot:
            screen = PickScreen(Listing(title="Empty"))
            await app.push_screen(screen)
            await pilot.pause()
            self.assertEqual([], list(screen.query(PickRow)))
            shown = [str(s.render()) for s in screen.query(Static)]
            self.assertTrue(any("Nothing to choose" in line for line in shown))

    async def test_a_kind_this_build_never_heard_of_still_draws(self):
        app = self._App()
        async with app.run_test() as pilot:
            screen = PickScreen(Listing(rows=(Row("1", "A", "hologram"),)))
            await app.push_screen(screen)
            await pilot.pause()
            glyphs = [
                str(s.render())
                for s in screen.query(Static)
                if "pick--glyph" in s.classes
            ]
            self.assertTrue(glyphs and glyphs[0].strip())


class TheSameCommandOutsideTheToolbox(unittest.TestCase):
    """A command run by hand sees nothing set and prints for a person."""

    def test_a_command_branches_on_the_variable_not_on_a_flag(self):
        # The whole contract for a command author: one environment variable, and
        # absent means print the ordinary thing. Nothing about the toolbox leaks
        # into how it is invoked.
        import os
        import subprocess
        import sys
        from tempfile import TemporaryDirectory

        body = (
            "import json, os, sys\n"
            "if os.environ.get('DTI_INTERACTIVE') == '1':\n"
            "    print('@dti:rows ' + json.dumps({'rows': [{'id': '1', 'label': 'A'}]}))\n"
            "else:\n"
            "    print('  1  A')\n"
        )
        with TemporaryDirectory() as folder:
            script = Path(folder) / "cmd.py"
            script.write_text(body, encoding="utf-8")
            plain = subprocess.run(
                [sys.executable, str(script)], capture_output=True, text=True,
                env={k: v for k, v in os.environ.items() if k != "DTI_INTERACTIVE"},
            )
        self.assertEqual("  1  A", plain.stdout.splitlines()[0].rstrip())
        self.assertNotIn("@dti:", plain.stdout)


class TheViewReachesTheRunner(unittest.TestCase):
    """The gate decides; `_run_commands` is where the decision has to arrive."""

    class _Runner:
        def __init__(self):
            self.views = []

        def locate(self, executable):
            return "/usr/bin/" + executable

        async def stream(self, command, on_output, cwd=None, view=None):
            self.views.append(view)
            return ProcessResult(exit_code=0, stdout="", stderr="")

    class _Ui:
        def __init__(self, view):
            self.view = view

        def write(self, message=""):
            pass

        def list_view(self):
            return self.view

    def _ran(self, *, setting, declared):
        from company_tui.templates.scripts import _run_commands

        runner = self._Runner()
        view = _View()
        services = PackServices(
            console=self._Ui(view),
            file_system=None,
            process_runner=runner,
            config=_Config(setting),
            finalizer=None,
        )
        action = ScriptAction(
            section="acc", key="browse",
            interactive=declared,
            after_success=("acc-browse --json",),
        )
        asyncio.run(_run_commands(action, {}, Path("."), services))
        return runner.views

    def test_both_keys_hands_the_runner_a_view(self):
        self.assertEqual(1, len(self._ran(setting=True, declared=True)))
        self.assertIsNotNone(self._ran(setting=True, declared=True)[0])

    def test_the_setting_alone_hands_it_nothing(self):
        self.assertEqual([None], self._ran(setting=True, declared=False))

    def test_the_declaration_alone_hands_it_nothing(self):
        self.assertEqual([None], self._ran(setting=False, declared=True))
