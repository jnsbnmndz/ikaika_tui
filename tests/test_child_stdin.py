"""What a child gets on stdin, which is the terminal the interface is drawn on.

Omitting `stdin` means inherit, not none, so every child was handed the console the
TUI had put into mouse-reporting mode; see `docs/pitfalls.md` 12.2. Proved by feeding
this process's own stdin a sentinel and checking the child cannot read it - a handle
number or a file kind differs per harness, but who can read the bytes does not.
"""

import asyncio
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from company_tui.domain.interactive import END, ROWS, Listing, ListView

SENTINEL = "bytes-meant-for-the-interface"

PATIENCE = 20
"""Seconds. The run takes about two; a child blocking on an inherited stdin
takes forever, and a test that hangs is a suite nobody runs."""

READS_STDIN = """
import sys
print("read:" + repr(sys.stdin.readline()))
"""

ASKS_AND_READS = f"""
import sys
print({ROWS!r} + ' {{"rows": [{{"id": "one", "label": "One"}}]}}')
sys.stdout.flush()
print("got:" + sys.stdin.readline().strip())
print({END!r})
"""

STANDS_IN_FOR_THE_APP = """
import asyncio, sys
from company_tui.infrastructure.processes import LocalProcessRunner

CHILD = (sys.executable, sys.argv[1])


async def main():
    runner = LocalProcessRunner()
    print("captured " + (await runner.capture(CHILD)).stdout.strip())
    lines = []
    await runner.stream(CHILD, lines.append)
    print("streamed " + " ".join(lines))


asyncio.run(main())
"""
"""Run as its own process so it has a real stdin of its own to be stolen.

`capture` goes first deliberately: whichever reads first empties the pipe, so with
`stream` ahead of it the capture half would report an empty read whether it inherited
this process's stdin or not, and prove nothing.
"""


class _Answers(ListView):
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def show(self, listing: Listing):
        return self.answer

    def close(self) -> None:
        pass


class _RealChild(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def _write(self, name: str, body: str) -> str:
        path = Path(self.folder.name) / name
        path.write_text(body, encoding="utf-8")
        return str(path)


class WhoCanReadWhatWasMeantForTheInterface(_RealChild):
    """The keystrokes arriving at this process are not the child's to read."""

    def _run_through_a_parent_with_a_real_stdin(self) -> str:
        parent = self._write("parent.py", STANDS_IN_FOR_THE_APP)
        child = self._write("child.py", READS_STDIN)
        try:
            done = subprocess.run(
                (sys.executable, parent, child),
                capture_output=True,
                check=False,
                cwd=str(Path(__file__).resolve().parent.parent),
                input=f"{SENTINEL}\n",
                shell=False,
                text=True,
                timeout=PATIENCE,
            )
        except subprocess.TimeoutExpired:
            self.fail(
                "a child sat on the inherited stdin and never returned, which is"
                " the same defect wearing the other face"
            )
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout

    def test_neither_streaming_nor_capturing_hands_the_child_our_stdin(self):
        # The whole defect in one assertion: with stdin left unsaid the child read
        # the sentinel, which on a real terminal is the user's own keys and the
        # mouse reports the app turned on.
        said = self._run_through_a_parent_with_a_real_stdin()
        self.assertNotIn(SENTINEL, said, "a child read what was meant for the app")
        self.assertIn("streamed read:''", said)
        self.assertIn("captured read:''", said)


class WhatReadingItGets(_RealChild):
    """A child that reads anyway gets an end, not a wait."""

    def _stream(self, body: str, view=None):
        lines: list[str] = []
        command = (sys.executable, self._write("child.py", body))
        from company_tui.infrastructure.processes import LocalProcessRunner

        result = asyncio.run(
            LocalProcessRunner().stream(command, lines.append, None, view)
        )
        return result, " ".join(lines)

    def test_a_child_that_reads_stdin_is_not_left_waiting(self):
        # It used to block on the terminal, eating keys meant for the interface,
        # until the run was stopped. An end is an answer; a wait is not.
        result, said = self._stream(READS_STDIN)
        self.assertEqual(0, result.exit_code)
        self.assertIn("read:''", said)

    def test_the_protocol_still_gets_a_real_pipe(self):
        # The fix must not reach the one run that is meant to have an stdin.
        result, said = self._stream(ASKS_AND_READS, view=_Answers("one"))
        self.assertEqual(0, result.exit_code)
        self.assertIn("got:@dti:pick one", said)


if __name__ == "__main__":
    unittest.main()
