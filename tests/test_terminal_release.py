"""Giving the terminal back, on the exits Textual's own shutdown does not reach.

`docs/pitfalls.md` 12.1 is the failure: the sequences that stop a terminal reporting
mouse motion are queued on a daemon thread whose flush is a no-op, so an interrupted
shutdown drops them and the console fills with `^[[<35;61;40M` forever.
"""

import re
import sys
import unittest
from unittest.mock import patch

from company_tui import cli
from company_tui.infrastructure import terminal_window
from company_tui.infrastructure.terminal_window import (
    _RELEASE_SEQUENCE,
    _REPORTING_MODES,
    _TERMINAL_INTERACTION_SEQUENCE,
    release_terminal,
)


class _Terminal:
    """Somewhere to write that can say whether it is a terminal."""

    def __init__(self, tty: bool = True) -> None:
        self.written: list[str] = []
        self.flushed = 0
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def write(self, text: str) -> None:
        self.written.append(text)

    def flush(self) -> None:
        self.flushed += 1


class _Console:
    """A TUI console that ends the way the test wants it to."""

    def __init__(self, raising: BaseException | None = None) -> None:
        self.result_code = 7
        self._raising = raising
        self.ran = False

    def run(self) -> None:
        self.ran = True
        if self._raising is not None:
            raise self._raising


class WhatIsTurnedOnIsTurnedOff(unittest.TestCase):
    """One list of modes, so the two sequences cannot drift apart."""

    def test_every_mode_the_app_arms_is_disarmed(self):
        for mode in _REPORTING_MODES:
            self.assertIn(f"\x1b[?{mode}h", _TERMINAL_INTERACTION_SEQUENCE)
            self.assertIn(f"\x1b[?{mode}l", _RELEASE_SEQUENCE)

    def test_the_release_also_undoes_what_textual_writes_last(self):
        # The four it writes after `disable_input`, which is where it stopped.
        for sequence in ("\x1b[?2004l", "\x1b[<u", "\x1b[?1049l", "\x1b[?25h"):
            self.assertIn(sequence, _RELEASE_SEQUENCE)

    def test_the_release_turns_no_reporting_back_on(self):
        # Showing the cursor is the one `h` that belongs here; a reporting mode
        # set on the way out would leave the terminal talking to a shell.
        armed = re.findall(r"\x1b\[\?(\d+)h", _RELEASE_SEQUENCE)
        self.assertEqual(["25"], armed)
        self.assertNotIn("25", _REPORTING_MODES)


class WritingIt(unittest.TestCase):
    """Straight to the real stdout, because the driver may already be gone."""

    def test_it_goes_out_and_is_flushed(self):
        terminal = _Terminal()
        with patch.object(sys, "__stdout__", terminal):
            self.assertTrue(release_terminal())
        self.assertEqual([_RELEASE_SEQUENCE], terminal.written)
        self.assertEqual(1, terminal.flushed)

    def test_nothing_is_written_where_nobody_would_read_it(self):
        # Piped output is somebody's text, not a terminal to put back.
        terminal = _Terminal(tty=False)
        with patch.object(sys, "__stdout__", terminal):
            self.assertFalse(release_terminal())
        self.assertEqual([], terminal.written)

    def test_a_stdout_that_is_gone_is_not_an_error(self):
        with patch.object(sys, "__stdout__", None):
            self.assertFalse(release_terminal())

    def test_the_console_modes_are_put_back_when_there_are_any(self):
        put = []
        with (
            patch.object(sys, "__stdout__", _Terminal()),
            patch.object(
                terminal_window, "_set_console_mode", lambda s, m: put.append(m) is None
            ),
        ):
            release_terminal((0x1F7, 0x7))
        self.assertEqual([0x1F7, 0x7], put)

    def test_modes_nobody_could_read_are_not_guessed_at(self):
        put = []
        with (
            patch.object(sys, "__stdout__", _Terminal()),
            patch.object(
                terminal_window, "_set_console_mode", lambda s, m: put.append(m) is None
            ),
        ):
            release_terminal((None, None))
        self.assertEqual([], put)


class LeavingTheApp(unittest.TestCase):
    """Every way out of the TUI goes past the release."""

    def _run(self, console):
        released = []
        with (
            patch("company_tui.bootstrap.create_tui_console", lambda _start: console),
            patch.object(terminal_window, "console_modes", lambda: (1, 2)),
            patch.object(
                terminal_window, "release_terminal", lambda m: released.append(m) is None
            ),
        ):
            code = cli.main([])
        return code, released

    def test_an_ordinary_exit_releases_it(self):
        console = _Console()
        code, released = self._run(console)
        self.assertTrue(console.ran)
        self.assertEqual(7, code)
        self.assertEqual([(1, 2)], released)

    def test_a_ctrl_c_during_shutdown_releases_it_too(self):
        # The reported failure: Textual blocks joining its input thread, Ctrl+C
        # lands there, and `except Exception` does not catch a KeyboardInterrupt.
        code, released = self._run(_Console(KeyboardInterrupt()))
        self.assertEqual(cli.INTERRUPTED, code)
        self.assertEqual([(1, 2)], released)

    def test_a_crash_releases_it_before_the_traceback(self):
        with self.assertRaises(RuntimeError):
            self._run(_Console(RuntimeError("boom")))

    def test_the_modes_are_read_before_the_app_is_built(self):
        # Textual overwrites them in `enable_application_mode`, so reading after
        # it starts would record Textual's own modes and restore those.
        order = []
        console = _Console()

        def built(_start):
            order.append("built")
            return console

        with (
            patch("company_tui.bootstrap.create_tui_console", built),
            patch.object(
                terminal_window,
                "console_modes",
                lambda: order.append("read") or (1, 2),
            ),
            patch.object(terminal_window, "release_terminal", lambda _m: None),
        ):
            cli.main([])
        self.assertEqual(["read", "built"], order)


if __name__ == "__main__":
    unittest.main()
