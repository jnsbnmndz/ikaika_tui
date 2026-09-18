"""The browser against a real child: the round trip, and the script it degrades into."""

import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from company_tui.domain.interactive import (
    Invoked,
    ListView,
    Opened,
    RecordingListView,
)
from company_tui.infrastructure.processes import LocalProcessRunner

CHILD = '''
import json, os, sys

if os.environ.get("DTI_INTERACTIVE") != "1":
    print("Reports/  Archive/")
    raise SystemExit(0)


def send(verb, payload=None):
    print(verb if payload is None else verb + " " + json.dumps(payload))
    sys.stdout.flush()


send("@dti:view", {"columns": [{"key": "name", "label": "Name", "grow": True}],
                   "tree": [{"id": "root", "label": "Root", "parent": None}]})
print("@dti:status 2 folders, nothing checked out")   # text, not JSON
sys.stdout.flush()
send("@dti:rows", {"breadcrumb": ["Root"],
                   "rows": [{"id": "rep", "cells": {"name": "Reports"}},
                            {"id": "arc", "cells": {"name": "Archive"}}],
                   "actions": [{"id": "add", "label": "Add", "key": "a"},
                               {"id": "remove", "label": "Remove", "key": "r",
                                "danger": True}]})

reply = sys.stdin.readline().strip()
verb, _, rest = reply.partition(" ")
print("REPLY " + verb + " | " + rest)
sys.stdout.flush()

if verb == "@dti:action":
    send("@dti:ask", {"prompt": "New folder name", "value": "untitled"})
    answered = sys.stdin.readline().strip()
    print("NAMED " + repr(answered.partition(" ")[2]))
    sys.stdout.flush()
    send("@dti:rows", {"title": "Delete it?",
                       "rows": [{"id": "yes", "label": "Delete"},
                                {"id": "no", "label": "Keep"}]})
    print("CONFIRMED " + sys.stdin.readline().strip())
    sys.stdout.flush()

send("@dti:end")
'''


class _Browser(ListView):
    """A browser that answers from a script, and records what it was shown."""

    def __init__(self, does=()):
        self.does = list(does)
        self.panes = []
        self.modals = []
        self.described = []
        self.said = []
        self.asked = []
        self.closed = 0

    @property
    def browsing(self):
        return True

    def describe(self, spec):
        self.described.append(spec)

    def say(self, status):
        self.said.append(status.text)

    async def browse(self, listing):
        self.panes.append(listing)
        return self.does.pop(0) if self.does else None

    async def show(self, listing):
        self.modals.append(listing)
        return listing.rows[0].id if listing.rows else None

    async def ask(self, question):
        self.asked.append(question)
        return "march"

    def close(self):
        self.closed += 1


class _Run(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.lines: list[str] = []
        path = Path(self.folder.name) / "child.py"
        path.write_text(CHILD, encoding="utf-8")
        self.command = (sys.executable, str(path))

    def _stream(self, view):
        return asyncio.run(
            LocalProcessRunner().stream(self.command, self.lines.append, None, view)
        )


class TheRoundTrip(_Run):
    """Every verb, over a real pipe, in the order a browse actually happens."""

    def test_the_view_reaches_the_browser_rather_than_the_output(self):
        view = _Browser(does=[Opened("rep")])
        self._stream(view)
        self.assertEqual(1, len(view.described))
        spec = view.described[0]
        self.assertEqual(("name",), tuple(c.key for c in spec.columns))
        self.assertEqual(("root",), tuple(n.id for n in spec.tree))
        self.assertNotIn("@dti:view", "".join(self.lines))

    def test_the_status_reaches_it_too_and_is_text_rather_than_json(self):
        view = _Browser(does=[Opened("rep")])
        self._stream(view)
        self.assertEqual(["2 folders, nothing checked out"], view.said)

    def test_the_pane_is_the_listing_with_the_breadcrumb(self):
        view = _Browser(does=[Opened("rep")])
        self._stream(view)
        self.assertEqual(1, len(view.panes))
        self.assertTrue(view.panes[0].pane)
        self.assertEqual(("Root",), view.panes[0].breadcrumb)
        self.assertEqual(("rep", "arc"), tuple(r.id for r in view.panes[0].rows))
        self.assertEqual(("add", "remove"), tuple(a.id for a in view.panes[0].actions))

    def test_entering_a_row_goes_back_as_an_open(self):
        self._stream(_Browser(does=[Opened("rep")]))
        self.assertIn("REPLY @dti:open | rep", self.lines)

    def test_an_action_goes_back_with_the_row_it_was_run_on(self):
        self._stream(_Browser(does=[Invoked("add", "rep")]))
        self.assertIn("REPLY @dti:action | add rep", self.lines)

    def test_an_action_on_nowhere_in_particular_names_no_row(self):
        self._stream(_Browser(does=[Invoked("add")]))
        self.assertIn("REPLY @dti:action | add", self.lines)

    def test_an_ask_is_answered_with_the_text(self):
        view = _Browser(does=[Invoked("add", "rep")])
        self._stream(view)
        self.assertEqual(["New folder name"], [q.prompt for q in view.asked])
        self.assertEqual(["untitled"], [q.value for q in view.asked])
        self.assertIn("NAMED 'march'", self.lines)

    def test_a_question_mid_browse_is_a_modal_and_not_the_pane(self):
        # The command's own confirmation. Nothing here invents one, and the pane
        # it was asked over is not replaced by it.
        view = _Browser(does=[Invoked("remove", "rep")])
        result = self._stream(view)
        self.assertEqual(["Delete it?"], [listing.title for listing in view.modals])
        self.assertFalse(view.modals[0].pane)
        self.assertEqual(1, len(view.panes))
        self.assertIn("CONFIRMED @dti:pick yes", self.lines)
        self.assertEqual(0, result.exit_code)

    def test_the_view_is_closed_when_the_run_ends(self):
        view = _Browser(does=[Opened("rep")])
        self._stream(view)
        self.assertTrue(view.closed)


class LeavingTheBrowser(_Run):
    def test_nothing_answering_the_pane_stops_the_command(self):
        # Esc. The same reasoning as every other listing here: a view that cannot
        # answer and does not say so leaves the child waiting forever.
        view = _Browser(does=[None])
        result = self._stream(view)
        self.assertNotEqual(0, result.exit_code)
        self.assertNotIn("REPLY @dti:open | rep", self.lines)


class AnOlderToolboxRunsItAsAScript(_Run):
    """The compatibility rule: form and terminal, pick-lists or text."""

    def test_the_browsers_verbs_come_back_as_ordinary_output(self):
        view = RecordingListView(answers=["rep"])
        self._stream(view)
        printed = "\n".join(self.lines)
        self.assertIn("@dti:view", printed)
        self.assertIn("@dti:status", printed)

    def test_the_pane_is_shown_as_an_ordinary_pick_list(self):
        view = RecordingListView(answers=["rep"])
        self._stream(view)
        self.assertEqual(1, len(view.seen))
        self.assertEqual(("rep", "arc"), tuple(r.id for r in view.seen[0].rows))

    def test_a_row_with_only_cells_is_still_readable_in_it(self):
        view = RecordingListView(answers=["rep"])
        self._stream(view)
        self.assertEqual(("Reports", "Archive"), tuple(r.label for r in view.seen[0].rows))

    def test_the_answer_goes_back_as_a_pick(self):
        # Which is why a command reads the verb of what it is sent rather than
        # assuming one: the reply says which surface answered, and it is the only
        # thing that does.
        self._stream(RecordingListView(answers=["rep"]))
        self.assertIn("REPLY @dti:pick | rep", self.lines)

    def test_with_no_view_at_all_every_line_is_output(self):
        result = self._stream(None)
        printed = "\n".join(self.lines)
        self.assertIn("Reports/  Archive/", printed)
        self.assertNotIn("@dti:", printed)
        self.assertEqual(0, result.exit_code)
