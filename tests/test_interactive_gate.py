"""Two keys turn this on, the setting travels, and the rows are a real list."""

import asyncio
import re
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from textual.app import App
from textual.widgets import Static

from company_tui.capabilities.advanced import INTERACTIVE_KEY, TIMED_KEY
from company_tui.domain.config import Settings
from company_tui.domain.interactive import (
    Listing,
    ListView,
    RecordingListView,
    Row,
    Untimed,
)
from company_tui.domain.ports import ProcessResult
from company_tui.domain.script_config import ScriptAction, actions_from
from company_tui.domain.settings_document import read_document, write_document
from company_tui.infrastructure.config import render
from company_tui.presentation import screens
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
    def __init__(self, on, timed=False):
        self._on = on
        self._timed = timed

    def interactive_lists(self):
        return self._on

    def timed_prompts(self):
        return self._timed


class _Services:
    def __init__(self, on, view, timed=False):
        self.config = _Config(on, timed)
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


class TheOtherSettingTravels(unittest.TestCase):
    """`timed_prompts`, in the same three places and independent of the first."""

    def test_it_is_off_out_of_the_box(self):
        self.assertFalse(Settings().timed_prompts)

    def test_the_document_carries_it_both_ways(self):
        for value in (True, False):
            document = write_document(replace(Settings(), timed_prompts=value))
            read, problems = read_document(document, Settings())
            self.assertEqual(value, read.timed_prompts)
            self.assertEqual((), problems)

    def test_a_document_that_predates_it_keeps_what_is_set(self):
        document = write_document(Settings())
        del document["experimental"]["timed_prompts"]
        read, problems = read_document(document, replace(Settings(), timed_prompts=True))
        self.assertTrue(read.timed_prompts)
        self.assertEqual((), problems)

    def test_a_value_that_is_not_a_boolean_is_reported_not_guessed(self):
        document = write_document(Settings())
        document["experimental"]["timed_prompts"] = 20
        read, problems = read_document(document, Settings())
        self.assertFalse(read.timed_prompts)
        self.assertTrue(any("timed_prompts" in p for p in problems))

    def test_the_settings_file_only_mentions_it_when_it_is_on(self):
        self.assertNotIn("timed_prompts", render(Settings()))
        self.assertIn(
            "timed_prompts = true", render(replace(Settings(), timed_prompts=True))
        )

    def test_either_flag_alone_still_writes_a_readable_section(self):
        for flags in ({"interactive_lists": True}, {"timed_prompts": True},
                      {"interactive_lists": True, "timed_prompts": True}):
            written = render(replace(Settings(), **flags))
            self.assertEqual(1, written.count("[experimental]"), flags)
            for key in flags:
                self.assertIn(f"{key} = true", written)

    def test_advanced_names_the_same_key_the_settings_do(self):
        self.assertEqual("timed_prompts", TIMED_KEY)


class TheCountdownIsASecondKey(unittest.TestCase):
    """Off, the fields are taken out rather than passed along beside a flag."""

    def _view(self, *, timed):
        action = ScriptAction(section="acc", key="browse", interactive=True)
        return _list_view(action, _Services(True, _View(), timed))

    def test_off_wraps_the_view_so_no_listing_can_carry_one(self):
        self.assertIsInstance(self._view(timed=False), Untimed)

    def test_on_hands_over_the_view_itself(self):
        self.assertIsInstance(self._view(timed=True), _View)

    def test_a_console_that_cannot_draw_one_is_still_nothing_at_all(self):
        action = ScriptAction(section="a", key="b", interactive=True)
        self.assertIsNone(_list_view(action, _Services(True, None, False)))

    def test_it_cannot_switch_the_list_itself_on(self):
        action = ScriptAction(section="a", key="b", interactive=True)
        self.assertIsNone(_list_view(action, _Services(False, _View(), True)))


class AToolboxThatWillNotRunOne(unittest.IsolatedAsyncioTestCase):
    """The compatibility rule: it renders, it waits, the extra fields are gone."""

    TIMED = Listing(
        title="Upload failed",
        hint="Enter chooses",
        rows=(Row("go", "Keep going"), Row("stop", "Stop")),
        timeout=20,
        default="stop",
    )

    async def test_the_countdown_never_reaches_the_view(self):
        inner = RecordingListView(answers=["go"])
        picked = await Untimed(inner).show(self.TIMED)
        self.assertEqual("go", picked)
        shown = inner.seen[0]
        self.assertEqual(0, shown.timeout)
        self.assertEqual("", shown.default)
        self.assertFalse(shown.counts_down)

    async def test_everything_else_arrives_exactly_as_it_was(self):
        inner = RecordingListView(answers=["stop"])
        await Untimed(inner).show(self.TIMED)
        shown = inner.seen[0]
        self.assertEqual(self.TIMED.rows, shown.rows)
        self.assertEqual("Upload failed", shown.title)
        self.assertEqual("Enter chooses", shown.hint)

    def test_being_done_with_the_list_goes_through(self):
        inner = RecordingListView()
        Untimed(inner).close()
        self.assertEqual(1, inner.closed)


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


class TheCountdownOnScreen(unittest.IsolatedAsyncioTestCase):
    """It shows, it answers with the row the command named, and a touch ends it."""

    class _App(App):
        pass

    LISTING = Listing(
        title="Upload failed",
        hint="Enter chooses",
        rows=(
            Row("retry", "Try again"),
            Row("wait", "Wait for it"),
            Row("stop", "Stop"),
        ),
        timeout=5,
        default="stop",
    )

    TICK = 0.15
    """How fast the clock runs here. The seconds shown are the listing's own.

    Fast enough to expire inside a test, slow enough that opening the screen does
    not use the countdown up before anything can look at it."""

    PAST_IT = 1.3
    """Longer than `TICK` x the listing's own timeout, with room for a slow machine."""

    @staticmethod
    def _hint_of(screen) -> str:
        line = next(iter(screen.query("#pick-hint")), None)
        return str(line.render()) if line is not None else ""

    def _seconds_in(self, hint: str) -> int:
        """The number on the clock. Never the one the listing opened with: the
        clock is real and starting the app costs some of it."""
        found = re.search(r"(\d+)s", hint)
        self.assertIsNotNone(found, f"no countdown in {hint!r}")
        return int(found.group(1))

    @asynccontextmanager
    async def _open(self, listing=None):
        """A `PickScreen` up and mounted, with whatever it is answered with.

        Pushed with a result callback rather than awaited from a worker: the push
        is then something to await, so nothing here is racing the screen it is
        about to press keys at.
        """
        app = self._App()
        answer: dict = {}
        with patch.object(screens, "COUNTDOWN_TICK", self.TICK):
            async with app.run_test() as pilot:
                screen = PickScreen(self.LISTING if listing is None else listing)
                await app.push_screen(screen, lambda picked: answer.update(picked=picked))
                await pilot.pause()
                yield pilot, screen, answer

    async def test_the_hint_line_says_how_long_and_which_row_wins(self):
        async with self._open() as (_, screen, _answer):
            hint = self._hint_of(screen)
            self.assertIn("Enter chooses", hint)
            self.assertRegex(hint, r"\d+s → Stop")
            self.assertLessEqual(self._seconds_in(hint), self.LISTING.timeout)

    async def test_a_listing_with_no_hint_of_its_own_still_counts_down(self):
        async with self._open(replace(self.LISTING, hint="")) as (_, screen, _answer):
            self.assertRegex(self._hint_of(screen), r"^\d+s → Stop$")

    async def test_the_seconds_come_down(self):
        # A long listing, so this is reading the clock rather than racing it.
        async with self._open(replace(self.LISTING, timeout=60)) as (pilot, screen, _a):
            was = self._seconds_in(self._hint_of(screen))
            await pilot.pause(self.TICK * 1.5)
            self.assertLess(self._seconds_in(self._hint_of(screen)), was)

    async def test_expiry_answers_with_the_row_the_command_named(self):
        async with self._open() as (pilot, _screen, answer):
            await pilot.pause(self.PAST_IT)
            self.assertEqual("stop", answer.get("picked"))

    async def test_expiry_is_never_nothing(self):
        # `None` is Esc, which the runner reads as "nothing will answer this" and
        # kills the child. A timer that ran out is an answer, not an abandonment.
        async with self._open() as (pilot, _screen, answer):
            await pilot.pause(self.PAST_IT)
            self.assertIn("picked", answer)
            self.assertIsNotNone(answer["picked"])

    async def test_a_listing_offering_no_countdown_waits_as_it_always_did(self):
        waiting = replace(self.LISTING, timeout=0, default="")
        async with self._open(waiting) as (pilot, screen, answer):
            self.assertEqual("Enter chooses", self._hint_of(screen))
            self.assertIsNone(screen._timer)
            await pilot.pause(self.PAST_IT)
            self.assertNotIn("picked", answer)

    async def test_a_key_stops_it_for_good(self):
        async with self._open() as (pilot, _screen, answer):
            await pilot.press("down")
            await pilot.pause(self.PAST_IT)
            self.assertNotIn("picked", answer, "the countdown fired after an arrow key")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual("wait", answer.get("picked"))

    async def test_a_stopped_countdown_leaves_the_hint_behind(self):
        async with self._open() as (pilot, screen, _answer):
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual("Enter chooses", self._hint_of(screen))

    async def test_a_mouse_click_that_chooses_nothing_still_stops_it(self):
        async with self._open() as (pilot, screen, answer):
            await pilot.click("#pick-hint")
            await pilot.pause(self.PAST_IT)
            self.assertNotIn("picked", answer)
            self.assertIsNone(screen._timer)

    async def test_the_pointer_moving_onto_another_row_stops_it(self):
        async with self._open() as (pilot, screen, answer):
            list(screen.query(PickRow))[2].focus()
            await pilot.pause(self.PAST_IT)
            self.assertNotIn("picked", answer)

    async def test_a_screen_that_closed_first_takes_its_timer_with_it(self):
        async with self._open() as (pilot, screen, answer):
            self.assertIsNotNone(screen._timer)
            screen.dismiss("retry")  # what `close_rows` does when a run ends
            await pilot.pause()
            self.assertIsNone(screen._timer)
            await pilot.pause(self.PAST_IT)
            self.assertEqual("retry", answer.get("picked"))


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
