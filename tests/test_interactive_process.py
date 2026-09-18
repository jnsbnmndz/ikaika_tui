"""The runner against a real child: the opt-in, the pick, and the path that must not move."""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from company_tui.domain.interactive import (
    END,
    INTERACTIVE_VAR,
    ROWS,
    Listing,
    ListView,
    Untimed,
)
from company_tui.infrastructure.processes import LocalProcessRunner


def _script(body: str, folder: str) -> tuple[str, ...]:
    path = Path(folder) / "child.py"
    path.write_text(body, encoding="utf-8")
    return (sys.executable, str(path))


class _View(ListView):
    """Answers from a script, and records what it was shown."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.seen: list[Listing] = []
        self.closed = 0

    async def show(self, listing):
        self.seen.append(listing)
        return self.answers.pop(0) if self.answers else None

    def close(self):
        self.closed += 1


class _Runner(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.runner = LocalProcessRunner()
        self.lines: list[str] = []

    def _stream(self, body, view=None):
        command = _script(body, self.folder.name)
        return asyncio.run(
            self.runner.stream(command, self.lines.append, None, view)
        )


class WithoutAView(_Runner):
    """Setting off: nothing about a run may differ from the day before this existed."""

    def test_the_variable_is_not_in_the_environment(self):
        result = self._stream(
            "import os\n"
            f"print('SET' if {INTERACTIVE_VAR!r} in os.environ else 'UNSET')\n"
        )
        self.assertEqual(["UNSET"], self.lines)
        self.assertEqual(0, result.exit_code)

    def test_there_is_no_stdin_to_read(self):
        # No pipe at all: a child that reads gets whatever the parent had, and in a
        # test that is a closed handle - never a pipe this would have to feed.
        result = self._stream(
            "import sys\n"
            "print('TTY' if sys.stdin and sys.stdin.isatty() else 'NOT A PIPE')\n"
        )
        self.assertEqual(0, result.exit_code)

    def test_a_protocol_line_is_just_output(self):
        # Without the opt-in nothing parses anything, so a line that looks like the
        # protocol is text, exactly as it was.
        body = f"print({ROWS + ' ' + json.dumps({'rows': []})!r})\n"
        self._stream(body)
        self.assertEqual([ROWS + " " + json.dumps({"rows": []})], self.lines)


class WithAView(_Runner):
    def test_the_command_is_told_it_can_speak(self):
        view = _View()
        self._stream(
            "import os\n"
            f"print(os.environ.get({INTERACTIVE_VAR!r}, 'UNSET'))\n",
            view,
        )
        self.assertEqual(["1"], self.lines)

    def test_rows_are_shown_and_the_pick_goes_back(self):
        body = (
            "import json, sys\n"
            f"print({ROWS!r} + ' ' + json.dumps("
            "{'title': 'T', 'hint': 'H', 'rows': [{'id': '1', 'label': 'One'},"
            " {'id': '10', 'label': 'Ten'}]}))\n"
            "sys.stdout.flush()\n"
            "answer = sys.stdin.readline().strip()\n"
            "print('GOT ' + answer)\n"
        )
        view = _View(answers=["10"])
        result = self._stream(body, view)
        self.assertEqual(0, result.exit_code)
        self.assertEqual(1, len(view.seen))
        self.assertEqual("T", view.seen[0].title)
        self.assertEqual(("1", "10"), tuple(r.id for r in view.seen[0].rows))
        self.assertEqual(["GOT @dti:pick 10"], self.lines)

    def test_a_second_block_replaces_the_first(self):
        body = (
            "import json, sys\n"
            "for step in ('a', 'b'):\n"
            f"    print({ROWS!r} + ' ' + json.dumps("
            "{'rows': [{'id': step, 'label': step.upper()}]}))\n"
            "    sys.stdout.flush()\n"
            "    print('PICKED ' + sys.stdin.readline().strip().split()[-1])\n"
            "    sys.stdout.flush()\n"
        )
        view = _View(answers=["a", "b"])
        self._stream(body, view)
        self.assertEqual(2, len(view.seen))
        self.assertEqual(["PICKED a", "PICKED b"], self.lines)

    def test_protocol_lines_are_not_output(self):
        body = (
            "import json, sys\n"
            "print('before')\n"
            f"print({ROWS!r} + ' ' + json.dumps({{'rows': []}}))\n"
            "sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
            f"print({END!r})\n"
            "print('after')\n"
        )
        view = _View(answers=["x"])
        result = self._stream(body, view)
        self.assertEqual(["before", "after"], self.lines)
        self.assertNotIn(ROWS, result.stdout)

    def test_end_closes_the_view_and_streaming_carries_on(self):
        body = f"print({END!r})\nprint('plain again')\n"
        view = _View()
        self._stream(body, view)
        self.assertEqual(["plain again"], self.lines)
        self.assertGreaterEqual(view.closed, 1)

    def test_leaving_the_view_stops_the_command(self):
        # Esc. Nothing else is going to answer it, so leaving it parked on a read is
        # the one outcome worse than killing it.
        body = (
            "import json, sys, time\n"
            f"print({ROWS!r} + ' ' + json.dumps({{'rows': [{{'id': '1', 'label': 'A'}}]}}))\n"
            "sys.stdout.flush()\n"
            "time.sleep(60)\n"
            "print('NEVER')\n"
        )
        view = _View(answers=[None])
        result = self._stream(body, view)
        self.assertNotIn("NEVER", self.lines)
        self.assertNotEqual(0, result.exit_code)

    def test_a_malformed_line_prints_and_the_run_survives(self):
        body = (
            f"print({ROWS!r} + ' {{not json')\n"
            "print('still here')\n"
        )
        view = _View()
        result = self._stream(body, view)
        self.assertEqual([ROWS + " {not json", "still here"], self.lines)
        self.assertEqual(0, result.exit_code)
        self.assertEqual([], view.seen)

    def test_offered_but_never_used_is_not_an_error(self):
        # DTI_INTERACTIVE set and no rows ever arrive: it simply streamed.
        view = _View()
        result = self._stream("print('ordinary')\n", view)
        self.assertEqual(["ordinary"], self.lines)
        self.assertEqual(0, result.exit_code)
        self.assertEqual([], view.seen)

    def test_a_command_reading_with_no_rows_out_can_still_be_stopped(self):
        """It blocks — and Stop is what gets you out, as with any hung command.

        Nothing can answer a read no listing asked for: the toolbox waits on its
        stdout while it waits on our stdin. That is the command misbehaving, and the
        recourse is the one every hung run already has.
        """
        body = (
            "import sys\n"
            "print('reading')\n"
            "sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
            "print('NEVER')\n"
        )
        command = _script(body, self.folder.name)

        async def stopped():
            task = asyncio.ensure_future(
                self.runner.stream(command, self.lines.append, None, _View())
            )
            await asyncio.sleep(1.5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(stopped())
        self.assertEqual(["reading"], self.lines)

    def test_stdin_is_closed_once_the_run_is_over(self):
        # The guardrail where it is observable: the pipe the run opened is not left
        # open behind it.
        closed = []

        class _Stdin:
            def is_closing(self):
                return False

            def close(self):
                closed.append(True)

        class _Process:
            stdin = _Stdin()

        LocalProcessRunner()._close_input(_Process())
        self.assertEqual([True], closed)


class TheEnvironmentIsInherited(_Runner):
    def test_the_child_keeps_the_rest_of_the_environment(self):
        # The variable is added, not substituted for everything else.
        os.environ["DTI_TEST_MARKER"] = "kept"
        self.addCleanup(os.environ.pop, "DTI_TEST_MARKER", None)
        self._stream(
            "import os\nprint(os.environ.get('DTI_TEST_MARKER', 'LOST'))\n", _View()
        )
        self.assertEqual(["kept"], self.lines)


class ATimedListingOnTheWire(_Runner):
    """The countdown changes nothing about how an answer travels."""

    CHILD = (
        "import json, sys\n"
        "print(" + repr(ROWS) + " + ' ' + json.dumps({\n"
        "    'rows': [{'id': 'retry', 'label': 'Try again'},\n"
        "             {'id': 'stop', 'label': 'Stop'}],\n"
        "    'timeout': 20, 'default': 'stop'}))\n"
        "sys.stdout.flush()\n"
        "picked = sys.stdin.readline().strip()\n"
        "print('CHOSE ' + picked.split(' ', 1)[1])\n"
        "print(" + repr(END) + ")\n"
    )

    def test_the_fields_reach_the_view(self):
        view = _View(answers=["retry"])
        self._stream(self.CHILD, view)
        self.assertEqual(20, view.seen[0].timeout)
        self.assertEqual("stop", view.seen[0].default)

    def test_an_expiry_goes_back_as_an_ordinary_pick(self):
        # The screen resolves with the default row's id, which is a string like any
        # other; nothing on the wire says a timer chose it and nothing needs to.
        view = _View(answers=["stop"])
        result = self._stream(self.CHILD, view)
        self.assertIn("CHOSE stop", self.lines)
        self.assertEqual(0, result.exit_code)

    def test_a_toolbox_that_will_not_run_one_answers_the_same_way(self):
        view = _View(answers=["retry"])
        self._stream(self.CHILD, Untimed(view))
        self.assertEqual(0, view.seen[0].timeout)
        self.assertEqual("", view.seen[0].default)
        self.assertIn("CHOSE retry", self.lines)
