"""The browser: its verbs, its gate, its screen, and the script it degrades into."""

import asyncio
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from textual.app import App
from textual.widgets import Input, Static, TextArea

from company_tui.capabilities.advanced import BROWSER_KEY
from company_tui.capabilities.script_actions import answers
from company_tui.domain.config import Settings
from company_tui.domain.interactive import (
    ASK,
    ROWS,
    STATUS,
    VIEW,
    Action,
    Ask,
    Column,
    Detailed,
    Invoked,
    Listing,
    ListView,
    Node,
    Opened,
    Row,
    Status,
    Untimed,
    ViewSpec,
    acted,
    answered,
    detail,
    opened,
    parse,
    said,
)
from company_tui.domain.options import Option, OptionKind
from company_tui.domain.script_config import ScriptAction, actions_from
from company_tui.domain.settings_document import read_document, write_document
from company_tui.infrastructure.config import render
from company_tui.presentation import browser_screen
from company_tui.presentation.browser_screen import (
    ActionChip,
    BrowseRow,
    BrowserScreen,
    TreeRow,
    _depths,
)
from company_tui.presentation.plain_console import PlainConsole
from company_tui.presentation.screens import InputScreen
from company_tui.templates.scripts import _list_view, browses

COLUMNS = [
    {"key": "name", "label": "Name", "grow": True},
    {"key": "size", "label": "Size", "width": 10, "align": "right"},
]


def _rows(**document):
    return f"{ROWS} {json.dumps(document)}"


def _view(**document):
    return f"{VIEW} {json.dumps(document)}"


class TheBrowsersOwnVerbs(unittest.TestCase):
    """`@dti:view`, `@dti:status` and `@dti:ask`, on the line format already here."""

    def test_a_view_declares_the_table_and_the_tree(self):
        spec = parse(
            _view(columns=COLUMNS, tree=[{"id": "root", "label": "Root", "parent": None}])
        )
        self.assertIsInstance(spec, ViewSpec)
        self.assertEqual(("name", "size"), tuple(c.key for c in spec.columns))
        self.assertEqual(("Name", "Size"), tuple(c.label for c in spec.columns))
        self.assertEqual((True, False), tuple(c.grow for c in spec.columns))
        self.assertEqual((0, 10), tuple(c.width for c in spec.columns))
        self.assertEqual(("", "right"), tuple(c.align for c in spec.columns))
        self.assertEqual((Node("root", "Root", ""),), spec.tree)

    def test_a_column_is_named_by_its_key_where_it_gives_no_label(self):
        self.assertEqual("tables", parse(_view(columns=[{"key": "tables"}])).columns[0].label)

    def test_a_view_with_no_tree_is_still_a_view(self):
        self.assertEqual((), parse(_view(columns=COLUMNS)).tree)

    def test_a_view_that_could_not_be_drawn_is_text(self):
        for document in (
            {},
            {"columns": []},
            {"columns": {}},
            {"columns": [{"label": "no key"}]},
            {"columns": [{"key": ""}]},
            {"columns": COLUMNS, "tree": [{"id": "a"}]},
            {"columns": COLUMNS, "tree": "root"},
        ):
            self.assertIsNone(parse(_view(**document)), repr(document))

    def test_a_width_that_is_not_a_size_is_no_width(self):
        for width in ("10", -1, 0, True, None, 1.5):
            spec = parse(_view(columns=[{"key": "a", "width": width}]))
            self.assertEqual(0, spec.columns[0].width, repr(width))

    def test_an_alignment_it_has_never_heard_of_is_no_alignment(self):
        self.assertEqual("", parse(_view(columns=[{"key": "a", "align": "skew"}])).columns[0].align)

    def test_a_status_is_the_rest_of_the_line_as_it_was_written(self):
        self.assertEqual(Status("41 files, 2.1 GB"), parse(f"{STATUS} 41 files, 2.1 GB"))
        self.assertEqual(Status(""), parse(STATUS))

    def test_an_ask_carries_the_prompt_and_whatever_is_already_there(self):
        asked = parse(f"{ASK} " + json.dumps({"prompt": "Name?", "value": "untitled"}))
        self.assertEqual(Ask("Name?", "untitled"), asked)
        self.assertEqual(Ask("", ""), parse(f"{ASK} {{}}"))

    def test_a_verb_from_a_later_version_is_still_only_text(self):
        self.assertIsNone(parse("@dti:upload {}"))
        self.assertIsNone(parse(f"{ASK} not json"))


class WhereTheUserIs(unittest.TestCase):
    """A listing carrying a breadcrumb is the pane; one without it is a question."""

    def test_a_pane_says_so_by_carrying_a_breadcrumb(self):
        listing = parse(
            _rows(breadcrumb=["Root", "Reports"], rows=[{"id": "r", "cells": {"name": "march"}}])
        )
        self.assertTrue(listing.pane)
        self.assertEqual(("Root", "Reports"), listing.breadcrumb)

    def test_an_empty_breadcrumb_is_still_a_pane(self):
        # The key being there says so, not what is in it: a browser at its own root
        # is still somewhere, and is still not a question.
        self.assertTrue(parse(_rows(breadcrumb=[], rows=[])).pane)

    def test_an_ordinary_pick_list_is_not_a_pane(self):
        listing = parse(_rows(title="Delete it?", rows=[{"id": "y", "label": "Delete"}]))
        self.assertFalse(listing.pane)
        self.assertEqual((), listing.breadcrumb)

    def test_a_breadcrumb_this_build_cannot_read_is_text(self):
        for crumbs in ("Root", {"at": "Root"}, ["Root", 2], [None]):
            self.assertIsNone(parse(_rows(breadcrumb=crumbs, rows=[])), repr(crumbs))


class TheCells(unittest.TestCase):
    def test_a_row_puts_its_cells_under_the_declared_keys(self):
        row = parse(
            _rows(rows=[{"id": "r-1", "cells": {"name": "march", "size": "4.2 MB"},
                         "kind": "leaf"}])
        ).rows[0]
        self.assertEqual({"name": "march", "size": "4.2 MB"}, dict(row.cells))
        self.assertEqual("leaf", row.kind)

    def test_a_row_with_cells_and_no_label_is_labelled_by_its_first(self):
        # Which is the whole of what makes the same row readable in a pick-list,
        # where there is no table to lay it out in.
        listing = parse(_rows(rows=[{"id": "r", "cells": {"name": "march", "size": "4 MB"}}]))
        self.assertEqual("march", listing.rows[0].label)

    def test_a_label_of_its_own_wins_over_the_cell(self):
        listing = parse(
            _rows(rows=[{"id": "r", "label": "March report", "cells": {"name": "march"}}])
        )
        self.assertEqual("March report", listing.rows[0].label)

    def test_a_row_with_nothing_to_call_it_is_text(self):
        self.assertIsNone(parse(_rows(rows=[{"id": "r", "cells": {}}])))
        self.assertIsNone(parse(_rows(rows=[{"id": "r", "cells": {"name": ""}}])))

    def test_cells_are_strings_and_only_strings(self):
        for cells in ({"size": 4200}, {"size": None}, {"size": ["4"]}, {"size": True},
                      "name=march"):
            self.assertIsNone(parse(_rows(rows=[{"id": "r", "cells": cells}])), repr(cells))

    def test_a_row_with_no_cells_at_all_still_reads(self):
        listing = parse(_rows(rows=[{"id": "r", "label": "A"}]))
        self.assertEqual({}, dict(listing.rows[0].cells))


class TheActionBar(unittest.TestCase):
    """Per listing, never remembered, and never anything this build added."""

    BAR = [
        {"id": "add", "label": "Add", "key": "a"},
        {"id": "remove", "label": "Remove", "key": "r", "danger": True},
    ]

    def test_the_bar_is_exactly_what_this_listing_declared(self):
        actions = parse(_rows(rows=[], actions=self.BAR)).actions
        self.assertEqual(
            (Action("add", "Add", "a", False), Action("remove", "Remove", "r", True)),
            actions,
        )

    def test_a_listing_declaring_none_offers_none(self):
        self.assertEqual((), parse(_rows(rows=[])).actions)

    def test_a_key_that_is_not_one_key_is_no_key(self):
        for key in ("ctrl+a", "", "ab", 1, None, True):
            listing = parse(_rows(rows=[], actions=[{"id": "a", "label": "A", "key": key}]))
            self.assertEqual("", listing.actions[0].key, repr(key))

    def test_only_a_real_true_is_dangerous(self):
        for value in ("true", 1, "danger", None):
            listing = parse(_rows(rows=[], actions=[{"id": "a", "label": "A", "danger": value}]))
            self.assertFalse(listing.actions[0].danger, repr(value))

    def test_an_id_that_could_not_be_written_back_is_text(self):
        # It goes out as `@dti:action <id> <row>`, where a space would be two ids.
        for identifier in ("re move", "", None, 7):
            self.assertIsNone(
                parse(_rows(rows=[], actions=[{"id": identifier, "label": "A"}])),
                repr(identifier),
            )

    def test_a_bar_this_build_cannot_read_is_text(self):
        for bar in ("add", {"id": "add"}, ["add"], [{"label": "no id"}], [{"id": "a"}]):
            self.assertIsNone(parse(_rows(rows=[], actions=bar)), repr(bar))


class WhatGoesBack(unittest.TestCase):
    def test_a_row_entered_is_an_open(self):
        self.assertEqual("@dti:open r-1", opened("r-1"))
        self.assertEqual("@dti:open a b/c", opened("a b/c"))

    def test_an_action_carries_the_row_it_was_run_on(self):
        self.assertEqual("@dti:action remove r-1", acted("remove", "r-1"))

    def test_an_action_on_nothing_in_particular_names_no_row(self):
        self.assertEqual("@dti:action add", acted("add"))
        self.assertEqual("@dti:action add", acted("add", ""))

    def test_an_answer_is_the_text_and_a_cancel_is_the_verb_alone(self):
        self.assertEqual("@dti:answer march", answered("march"))
        self.assertEqual("@dti:answer", answered(""))

    def test_what_the_user_did_chooses_its_own_line(self):
        self.assertEqual("@dti:open r-1", said(Opened("r-1")))
        self.assertEqual("@dti:action remove r-1", said(Invoked("remove", "r-1")))
        self.assertEqual("@dti:action add", said(Invoked("add")))


class TheManifestHalf(unittest.TestCase):
    def test_an_action_is_not_a_browser_unless_it_says_so(self):
        self.assertFalse(ScriptAction(section="x").browses)

    def test_the_word_is_browser_and_nothing_else(self):
        for value in ("browser", "Browser", "grid", "", True, None, 1):
            document = {
                "config": {"acc": {"files": {"command-after-success": ["x"], "view": value}}}
            }
            self.assertEqual(
                value == "browser", actions_from(document)[0].browses, repr(value)
            )

    def test_a_manifest_that_never_heard_of_it_still_reads(self):
        document = {"config": {"acc": {"files": {"command-after-success": ["x"]}}}}
        self.assertEqual("", actions_from(document)[0].view)

    def test_it_is_its_own_declaration_and_not_the_list_one(self):
        document = {
            "config": {"acc": {"files": {"command-after-success": ["x"], "view": "browser"}}}
        }
        action = actions_from(document)[0]
        self.assertTrue(action.browses)
        self.assertFalse(action.interactive)


class _Config:
    def __init__(self, *, lists=False, timed=False, browser=False):
        self._lists, self._timed, self._browser = lists, timed, browser

    def interactive_lists(self):
        return self._lists

    def timed_prompts(self):
        return self._timed

    def browser_view(self):
        return self._browser


class TheSettingTravels(unittest.TestCase):
    """`browser_view`, in the same places the other two go."""

    def test_it_is_off_out_of_the_box(self):
        self.assertFalse(Settings().browser_view)

    def test_a_port_that_never_heard_of_it_answers_no(self):
        from company_tui.domain.config import ConfigPort

        self.assertFalse(ConfigPort.browser_view(object()))

    def test_the_document_carries_it_both_ways(self):
        for value in (True, False):
            document = write_document(replace(Settings(), browser_view=value))
            read, problems = read_document(document, Settings())
            self.assertEqual(value, read.browser_view)
            self.assertEqual((), problems)

    def test_a_document_that_predates_it_keeps_what_is_set(self):
        document = write_document(Settings())
        del document["experimental"]["browser_view"]
        read, problems = read_document(document, replace(Settings(), browser_view=True))
        self.assertTrue(read.browser_view)
        self.assertEqual((), problems)

    def test_a_value_that_is_not_a_boolean_is_reported_not_guessed(self):
        document = write_document(Settings())
        document["experimental"]["browser_view"] = "browser"
        read, problems = read_document(document, Settings())
        self.assertFalse(read.browser_view)
        self.assertTrue(any("browser_view" in p for p in problems))

    def test_the_settings_file_only_mentions_it_when_it_is_on(self):
        self.assertNotIn("browser_view", render(Settings()))
        self.assertIn("browser_view = true", render(replace(Settings(), browser_view=True)))

    def test_all_three_share_one_section(self):
        written = render(
            replace(Settings(), interactive_lists=True, timed_prompts=True, browser_view=True)
        )
        self.assertEqual(1, written.count("[experimental]"))
        for key in ("interactive_lists", "timed_prompts", "browser_view"):
            self.assertIn(f"{key} = true", written)

    def test_advanced_names_the_same_key_the_settings_do(self):
        self.assertEqual("browser_view", BROWSER_KEY)


class _View(ListView):
    async def show(self, listing):
        return None

    def close(self):
        pass


class _Browser(_View):
    @property
    def browsing(self):
        return True


class _Console:
    def __init__(self, listing=None, browser=None):
        self._listing, self._browser = listing, browser

    def list_view(self):
        return self._listing

    def browser_view(self):
        return self._browser


class _Services:
    def __init__(self, config, console):
        self.config = config
        self.console = console


class TwoKeysAgain(unittest.TestCase):
    """The setting and the manifest, and neither one alone."""

    def _browses(self, *, setting, declared):
        action = ScriptAction(section="acc", key="files", view="browser" if declared else "")
        return browses(action, _Config(browser=setting))

    def test_both_or_nothing(self):
        self.assertTrue(self._browses(setting=True, declared=True))
        self.assertFalse(self._browses(setting=False, declared=True))
        self.assertFalse(self._browses(setting=True, declared=False))
        self.assertFalse(self._browses(setting=False, declared=False))

    def test_a_pipe_never_offers_one(self):
        self.assertIsNone(PlainConsole().browser_view())


class TheGate(unittest.TestCase):
    """Which view a run is handed, which is the whole of how it degrades."""

    BROWSING = ScriptAction(section="acc", key="files", view="browser")
    LISTING = ScriptAction(section="acc", key="files", interactive=True)
    BOTH = ScriptAction(section="acc", key="files", view="browser", interactive=True)

    def _view(self, action, config, *, browser=None, listing=None):
        return _list_view(action, _Services(config, _Console(listing, browser)))

    def test_a_browser_action_with_the_setting_on_gets_the_browser(self):
        view = self._view(self.BROWSING, _Config(browser=True, timed=True), browser=_Browser())
        self.assertIsInstance(view, _Browser)
        self.assertTrue(view.browsing)

    def test_the_browser_carries_the_list_protocol_with_it(self):
        # It is the stronger declaration of the two, and a browser that had to ask
        # for `interactive_lists` as well would be two switches for one feature.
        view = self._view(self.BROWSING, _Config(browser=True, timed=True), browser=_Browser())
        self.assertIsNotNone(view)

    def test_the_setting_off_falls_back_to_the_list_protocol(self):
        view = self._view(
            self.BOTH, _Config(lists=True, timed=True), browser=_Browser(), listing=_View()
        )
        self.assertIsInstance(view, _View)
        self.assertFalse(view.browsing)

    def test_the_setting_off_and_no_list_protocol_is_nothing_at_all(self):
        # Which leaves the run byte for byte what it was: no pipe, no variable.
        self.assertIsNone(self._view(self.BOTH, _Config(), browser=_Browser(), listing=_View()))
        self.assertIsNone(self._view(self.BROWSING, _Config(), browser=_Browser()))

    def test_a_surface_that_cannot_draw_one_falls_back_too(self):
        view = self._view(
            self.BOTH, _Config(browser=True, lists=True, timed=True), listing=_View()
        )
        self.assertIsInstance(view, _View)

    def test_the_countdown_setting_still_reaches_a_browser(self):
        view = self._view(self.BROWSING, _Config(browser=True), browser=_Browser())
        self.assertIsInstance(view, Untimed)
        self.assertTrue(view.browsing)

    def test_untimed_hands_the_whole_browser_through(self):
        spec = ViewSpec(columns=(Column("name"),))
        inner = _Recorder()
        wrapped = Untimed(inner)
        self.assertTrue(wrapped.browsing)
        wrapped.describe(spec)
        wrapped.say(Status("x"))
        self.assertEqual([spec], inner.described)
        self.assertEqual(["x"], inner.said)


class _Recorder(ListView):
    def __init__(self):
        self.described = []
        self.said = []
        self.browsed = []
        self.answer = None

    @property
    def browsing(self):
        return True

    async def show(self, listing):
        return None

    def close(self):
        pass

    def describe(self, spec):
        self.described.append(spec)

    def say(self, status):
        self.said.append(status.text)

    async def browse(self, listing):
        self.browsed.append(listing)
        return self.answer

    async def ask(self, question):
        return question.value


class NoFormAndNoTerminal(unittest.TestCase):
    """A browser action is launched on what its manifest already says."""

    def test_the_answers_are_the_defaults(self):
        options = (
            Option(key="root", label="Project", default="/work/acc"),
            Option(key="depth", label="Depth", kind=OptionKind.NUMBER, default=3),
            Option(key="dry", label="Dry run", kind=OptionKind.BOOLEAN, default=False),
        )
        self.assertEqual({"root": "/work/acc", "depth": 3, "dry": False}, answers(options))

    def test_nothing_declared_is_nothing_answered(self):
        self.assertEqual({}, answers(()))


class TheTreeIsDrawnFromItsParents(unittest.TestCase):
    def test_depth_is_counted_through_the_chain(self):
        tree = (Node("a", "A"), Node("b", "B", "a"), Node("c", "C", "b"))
        self.assertEqual((0, 1, 2), tuple(depth for _, depth in _depths(tree)))

    def test_a_parent_nothing_declares_is_a_root(self):
        self.assertEqual((0,), tuple(d for _, d in _depths((Node("b", "B", "ghost"),))))

    def test_a_cycle_is_drawn_rather_than_raised(self):
        # Somebody else's tree. Refusing to draw a malformed one would be refusing
        # to show what is actually there.
        tree = (Node("a", "A", "b"), Node("b", "B", "a"))
        self.assertEqual(2, len(_depths(tree)))


class TheScreen(unittest.IsolatedAsyncioTestCase):
    """What it draws is what it was sent, and what it returns is what was done."""

    class _App(App):
        """An app that catches the one message the screen sends upward."""

        def __init__(self):
            super().__init__()
            self.stopped = 0

        def on_browser_screen_stopped(self, message) -> None:
            message.stop()
            self.stopped += 1

    SPEC = ViewSpec(
        columns=(Column("name", "Name", grow=True), Column("size", "Size", 10, align="right")),
        tree=(Node("root", "Root"), Node("rep", "Reports", "root")),
    )
    PANE = Listing(
        breadcrumb=("Root", "Reports"),
        pane=True,
        rows=(
            Row("r-1", "march", cells={"name": "march", "size": "4.2 MB"}),
            Row("r-2", "april", cells={"name": "april", "size": "1.1 MB"}),
        ),
        actions=(Action("add", "Add", "a"), Action("remove", "Remove", "r", danger=True)),
    )

    async def test_it_draws_the_columns_the_command_declared(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            screen.describe(self.SPEC)
            await pilot.pause()
            heads = [str(s.render()) for s in screen.query(".browse--head")]
            self.assertEqual(["Name", "Size"], heads)
            self.assertEqual(["Root", "Reports"], [r.node.label for r in screen.query(TreeRow)])

    async def test_a_row_is_its_cells_under_those_columns(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            screen.describe(self.SPEC)
            await pilot.pause()
            app.run_worker(screen.browse(self.PANE))
            for _ in range(4):
                await pilot.pause()
            rows = list(screen.query(BrowseRow))
            self.assertEqual(["r-1", "r-2"], [row.row.id for row in rows])
            drawn = [str(s.render()) for s in rows[0].query(Static)]
            self.assertEqual(["march", "4.2 MB"], drawn)

    async def test_the_breadcrumb_and_the_bar_come_from_the_listing(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(screen.browse(self.PANE))
            for _ in range(4):
                await pilot.pause()
            crumbs = str(screen.query_one("#browse-crumbs", Static).render())
            self.assertIn("Root", crumbs)
            self.assertIn("Reports", crumbs)
            chips = list(screen.query(ActionChip))
            self.assertEqual(["add", "remove"], [chip.action.id for chip in chips])
            self.assertTrue(chips[1].has_class("-danger"))

    async def test_the_bar_is_replaced_and_never_added_to(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()

            async def walk():
                answer["first"] = await screen.browse(self.PANE)
                answer["second"] = await screen.browse(
                    replace(self.PANE, actions=(Action("back", "Back", "b"),))
                )

            app.run_worker(walk())
            for _ in range(4):
                await pilot.pause()
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
            self.assertEqual(["back"], [chip.action.id for chip in screen.query(ActionChip)])

    async def test_entering_a_row_reports_that_row(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(self._answered(screen, self.PANE, answer))
            for _ in range(4):
                await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
        self.assertEqual(Opened("r-2"), answer.get("did"))

    async def test_an_action_key_reports_the_action_and_the_focused_row(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(self._answered(screen, self.PANE, answer))
            for _ in range(4):
                await pilot.pause()
            await pilot.press("r")
            for _ in range(4):
                await pilot.pause()
        self.assertEqual(Invoked("remove", "r-1"), answer.get("did"))

    async def test_an_action_from_the_tree_names_no_row(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            screen.describe(self.SPEC)
            await pilot.pause()
            app.run_worker(self._answered(screen, self.PANE, answer))
            for _ in range(4):
                await pilot.pause()
            next(iter(screen.query(TreeRow))).focus()
            await pilot.pause()
            await pilot.press("a")
            for _ in range(4):
                await pilot.pause()
        self.assertEqual(Invoked("add", ""), answer.get("did"))

    async def test_a_key_no_action_declares_does_nothing(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(self._answered(screen, self.PANE, answer))
            for _ in range(4):
                await pilot.pause()
            await pilot.press("z")
            for _ in range(4):
                await pilot.pause()
            self.assertNotIn("did", answer)

    async def test_a_listing_with_nothing_in_it_says_so(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(screen.browse(Listing(breadcrumb=("Root",), pane=True)))
            for _ in range(4):
                await pilot.pause()
            self.assertEqual([], list(screen.query(BrowseRow)))
            shown = [str(s.render()) for s in screen.query(Static)]
            self.assertTrue(any("Nothing here" in line for line in shown))

    async def test_a_command_that_declared_no_columns_still_draws_its_rows(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(screen.browse(self.PANE))
            for _ in range(4):
                await pilot.pause()
            rows = list(screen.query(BrowseRow))
            self.assertEqual(["march"], [str(s.render()) for s in rows[0].query(Static)])

    async def test_a_status_outlives_the_listing_it_was_sent_with(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            screen.say(Status("41 files, 2.1 GB"))
            await pilot.pause()
            app.run_worker(screen.browse(self.PANE))
            for _ in range(4):
                await pilot.pause()
            line = str(screen.query_one("#browse-status", Static).render())
            self.assertEqual("41 files, 2.1 GB", line)

    async def test_a_listings_own_hint_replaces_it(self):
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            screen.say(Status("older"))
            await pilot.pause()
            app.run_worker(screen.browse(replace(self.PANE, hint="Enter opens")))
            for _ in range(4):
                await pilot.pause()
            self.assertEqual(
                "Enter opens", str(screen.query_one("#browse-status", Static).render())
            )

    async def test_escape_asks_for_the_run_behind_it_to_stop(self):
        # It says so upward rather than dismissing itself: what ends is the run,
        # and the screen goes because the run went.
        app = self._App()
        async with app.run_test(size=(90, 24)) as pilot:
            screen = BrowserScreen("ACC Files")
            await app.push_screen(screen)
            await pilot.pause()
            app.run_worker(screen.browse(self.PANE))
            for _ in range(4):
                await pilot.pause()
            await pilot.press("escape")
            for _ in range(4):
                await pilot.pause()
            self.assertEqual(1, app.stopped)
            self.assertIs(screen, app.screen)

    @staticmethod
    async def _answered(screen, listing, answer):
        answer["did"] = await screen.browse(listing)


class TheConsolePutsItUpAndTakesItDown(unittest.IsolatedAsyncioTestCase):
    """`TuiConsole.browse` - the seam between the run and the screen it happens on."""

    LISTING = Listing(
        breadcrumb=("Root",),
        pane=True,
        rows=(Row("a", "Alpha", cells={"name": "Alpha"}),),
    )
    SPEC = ViewSpec(columns=(Column("name", "Name", grow=True),))

    async def _browse(self, work, *, press=(), release=None):
        """Run `work` behind the browser, checking the screen is up while it does."""
        from company_tui.presentation.tui_console import TuiConsole

        console = TuiConsole()
        self.drawn = []
        async with console.run_test(size=(90, 26)) as pilot:
            await pilot.pause()
            running = asyncio.ensure_future(console.browse("Store", work(console)))
            for _ in range(8):
                await pilot.pause()

            self.assertIsInstance(console.screen, BrowserScreen)
            self.assertIsNotNone(console.browser_view())
            self.drawn = [row.row.id for row in console.screen.query(BrowseRow)]

            if release is not None:
                release.set()
            for key in press:
                await pilot.press(key)
            for _ in range(8):
                await pilot.pause()

            outcome = await asyncio.wait_for(running, 5)
            self.assertNotIsInstance(console.screen, BrowserScreen)
            self.assertIsNone(console.browser_view())
            return outcome

    async def test_the_view_is_live_only_while_the_browser_is(self):
        seen = {}

        async def work(console):
            view = console.browser_view()
            seen["browsing"] = view.browsing
            view.describe(self.SPEC)
            view.say(Status("live"))
            seen["did"] = await view.browse(self.LISTING)
            return "not reached"

        # Esc, so the browse is still outstanding when the screen is looked at.
        self.assertIsNone(await self._browse(work, press=("escape",)))
        self.assertTrue(seen["browsing"])
        self.assertEqual(["a"], self.drawn)

    async def test_escape_cancels_the_run_behind_it(self):
        # And `browse` answers `None`, which is a stopped run everywhere else here.
        cancelled = {}

        async def work(console):
            try:
                await console.browser_view().browse(self.LISTING)
            except asyncio.CancelledError:
                cancelled["yes"] = True
                raise
            return "not reached"

        self.assertIsNone(await self._browse(work, press=("escape",)))
        self.assertTrue(cancelled.get("yes"))

    async def test_a_run_that_finishes_hands_its_result_back(self):
        gate = asyncio.Event()

        async def work(console):
            console.browser_view().describe(self.SPEC)
            await gate.wait()
            return "finished"

        self.assertEqual("finished", await self._browse(work, release=gate))


BODY = "diff --git a/x b/x\n@@ -1,2 +1,3 @@\n-was\n+is\n"


class TheBodyOnARow(unittest.TestCase):
    """`detail_body`: plain text, sent with the listing, display only."""

    def test_a_row_carries_its_body(self):
        listing = parse(_rows(rows=[{"id": "r", "label": "A", "detail_body": BODY}]))
        self.assertEqual(BODY, listing.rows[0].detail_body)

    def test_a_row_without_one_has_none(self):
        self.assertEqual("", parse(_rows(rows=[{"id": "r", "label": "A"}])).rows[0].detail_body)

    def test_a_body_that_is_not_text_is_no_body_rather_than_a_broken_listing(self):
        for body in (12, None, ["a", "b"], {"text": "a"}, True):
            listing = parse(_rows(rows=[{"id": "r", "label": "A", "detail_body": body}]))
            self.assertIsNotNone(listing, repr(body))
            self.assertEqual("", listing.rows[0].detail_body, repr(body))

    def test_a_toolbox_without_the_pane_loses_the_pane_and_not_the_listing(self):
        # Which is the whole of how this degrades: an older build reads the row,
        # ignores the key it has never heard of, and shows the row.
        listing = parse(_rows(rows=[{"id": "r", "label": "A", "detail_body": BODY}]))
        self.assertEqual(("r",), tuple(row.id for row in listing.rows))

    def test_a_body_past_the_payload_limit_is_text_like_any_other_line(self):
        # What `on-demand` exists to stay under.
        huge = json.dumps({"rows": [{"id": "r", "label": "A", "detail_body": "x" * 600_000}]})
        self.assertIsNone(parse(f"{ROWS} {huge}"))


class TheBodiesAreFetched(unittest.TestCase):
    def test_a_listing_says_so_with_on_demand(self):
        self.assertTrue(parse(_rows(breadcrumb=["a"], rows=[], detail="on-demand")).on_demand)

    def test_anything_else_asks_for_nothing(self):
        for value in (None, "inline", "ondemand", "On-Demand", True, 1, ["on-demand"]):
            listing = parse(_rows(breadcrumb=["a"], rows=[], detail=value))
            self.assertFalse(listing.on_demand, repr(value))

    def test_a_listing_that_never_heard_of_it_asks_for_nothing(self):
        self.assertFalse(parse(_rows(breadcrumb=["a"], rows=[])).on_demand)

    def test_the_request_is_one_line_naming_the_row(self):
        self.assertEqual("@dti:detail r-1", detail("r-1"))
        self.assertEqual("@dti:detail r-1", said(Detailed("r-1")))


class TheNote(unittest.TestCase):
    """`multiline` on the ask, and the one line its answer comes back on."""

    def test_a_question_asks_for_a_note_by_saying_so(self):
        asked = parse(f"{ASK} " + json.dumps({"prompt": "Review", "multiline": True}))
        self.assertTrue(asked.multiline)

    def test_anything_but_a_real_true_is_the_box_it_always_was(self):
        for value in (None, "true", 1, 0, "yes"):
            asked = parse(f"{ASK} " + json.dumps({"prompt": "Review", "multiline": value}))
            self.assertFalse(asked.multiline, repr(value))
        self.assertFalse(parse(f"{ASK} " + json.dumps({"prompt": "Review"})).multiline)

    def test_newlines_come_back_written_out(self):
        self.assertEqual("@dti:answer one\\ntwo", answered("one\ntwo"))

    def test_the_line_endings_a_terminal_gives_it_are_all_the_same_one(self):
        self.assertEqual("@dti:answer a\\nb", answered("a\r\nb"))
        self.assertEqual("@dti:answer a\\nb", answered("a\rb"))

    def test_a_backslash_is_doubled_so_the_escape_can_be_undone(self):
        # Without this `C:\new` arrives as two lines, which is the bug this rule
        # exists to prevent rather than a theoretical one.
        self.assertEqual("@dti:answer C:\\\\new", answered("C:\\new"))

    def test_both_together_survive_a_round_trip(self):
        original = "Looks right.\nBut check C:\\new and a\\\\b."
        line = answered(original)
        self.assertNotIn("\n", line)
        self.assertEqual(original, _unescaped(line.partition(" ")[2]))

    def test_nothing_typed_is_still_a_cancel(self):
        self.assertEqual("@dti:answer", answered(""))


def _unescaped(text: str) -> str:
    """What a command does with an answer: left to right, once.

    Written out here because a two-pass replace in the wrong order turns the
    escaped `C:\\new` back into a newline, which is the trap worth having a test
    stand over.
    """
    out, index = [], 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            out.append("\n" if text[index + 1] == "n" else text[index + 1])
            index += 2
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


class TheDetailPane(unittest.IsolatedAsyncioTestCase):
    """It is there when the selected row has a body, and gone when it does not."""

    class _App(App):
        pass

    ROWS = (
        Row("r-1", "one", cells={"name": "one"}, detail_body=BODY),
        Row("r-2", "two", cells={"name": "two"}),
    )
    PANE = Listing(breadcrumb=("Root",), pane=True, rows=ROWS)

    async def _open(self, pilot, app, listing):
        screen = BrowserScreen("Store")
        await app.push_screen(screen)
        await pilot.pause()
        app.run_worker(screen.browse(listing))
        for _ in range(4):
            await pilot.pause()
        return screen

    @staticmethod
    def _pane(screen):
        return screen.query_one("#browse-detail")

    @staticmethod
    def _body(screen):
        return str(screen.query_one("#detail-body", Static).render())

    async def test_the_pane_shows_the_selected_rows_body(self):
        app = self._App()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = await self._open(pilot, app, self.PANE)
            self.assertFalse(self._pane(screen).has_class("-empty"))
            self.assertEqual(BODY.rstrip("\n"), self._body(screen).rstrip("\n"))

    async def test_it_goes_when_the_selected_row_has_none(self):
        app = self._App()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = await self._open(pilot, app, self.PANE)
            await pilot.press("down")
            for _ in range(4):
                await pilot.pause()
            self.assertTrue(self._pane(screen).has_class("-empty"))

    async def test_a_listing_where_nothing_has_a_body_never_shows_it(self):
        app = self._App()
        plain = Listing(breadcrumb=("Root",), pane=True, rows=(Row("a", "A"),))
        async with app.run_test(size=(100, 24)) as pilot:
            screen = await self._open(pilot, app, plain)
            self.assertTrue(self._pane(screen).has_class("-empty"))

    async def test_the_body_is_shown_as_it_arrived_and_not_as_markup(self):
        # Somebody else's log. A bracket in it is a bracket.
        marked = "[bold]not markup[/] and $not-a-variable"
        app = self._App()
        listing = Listing(
            breadcrumb=("Root",), pane=True,
            rows=(Row("a", "A", detail_body=marked),),
        )
        async with app.run_test(size=(100, 24)) as pilot:
            screen = await self._open(pilot, app, listing)
            self.assertEqual(marked, self._body(screen))

    async def test_a_long_line_is_not_re_wrapped(self):
        # A diff re-wrapped at the pane's width stops lining its markers up, which
        # is the moment somebody is relying on them.
        long = "+" + "x" * 400
        app = self._App()
        listing = Listing(
            breadcrumb=("Root",), pane=True, rows=(Row("a", "A", detail_body=long),)
        )
        async with app.run_test(size=(100, 24)) as pilot:
            screen = await self._open(pilot, app, listing)
            self.assertEqual(long, self._body(screen))
            self.assertGreater(screen.query_one("#detail-body").size.width, 100)


class AskingForABody(unittest.IsolatedAsyncioTestCase):
    """`on-demand`: selected, then asked for, then answered with a fresh listing."""

    class _App(App):
        pass

    TICK = 0.02
    WAITED = 0.3
    UNHURRIED = 0.5
    """Long enough that a key pressed during the app's own start-up still lands
    inside the window, for the tests about which row settles."""

    ROWS = (Row("r-1", "one", cells={"name": "one"}), Row("r-2", "two", cells={"name": "two"}))

    def _listing(self, **changes):
        return replace(
            Listing(breadcrumb=("Root",), pane=True, rows=self.ROWS, on_demand=True),
            **changes,
        )

    async def _asked(self, listing, *, press=(), wait=None, delay=None):
        app = self._App()
        answer = {}
        with patch.object(browser_screen, "DETAIL_DELAY", delay or self.TICK):
            async with app.run_test(size=(100, 24)) as pilot:
                screen = BrowserScreen("Store")
                await app.push_screen(screen)
                await pilot.pause()

                async def ask():
                    answer["did"] = await screen.browse(listing)

                app.run_worker(ask())
                for _ in range(40):
                    await pilot.pause()
                    if list(screen.query(BrowseRow)):
                        break
                for key in press:
                    await pilot.press(key)
                await pilot.pause(self.WAITED if wait is None else wait)
                await pilot.pause()
        return answer

    async def test_a_selected_row_with_no_body_is_asked_about(self):
        answer = await self._asked(self._listing())
        self.assertEqual(Detailed("r-1"), answer.get("did"))

    async def test_it_is_the_row_the_user_actually_settled_on(self):
        # Pressed inside the window, so the row passed over is never asked about.
        answer = await self._asked(
            self._listing(), press=("down",), delay=self.UNHURRIED, wait=1.0
        )
        self.assertEqual(Detailed("r-2"), answer.get("did"))

    async def test_a_row_whose_body_came_with_the_listing_is_not_asked_about(self):
        rows = (replace(self.ROWS[0], detail_body=BODY), self.ROWS[1])
        answer = await self._asked(self._listing(rows=rows))
        self.assertNotIn("did", answer)

    async def test_a_listing_that_did_not_ask_for_it_asks_for_nothing(self):
        answer = await self._asked(self._listing(on_demand=False))
        self.assertNotIn("did", answer)

    async def test_the_row_still_selected_is_not_asked_about_twice(self):
        # The listing that answers a request redraws the pane the request came
        # from. Asking again there is an infinite exchange, and it is the one this
        # has to be proof against.
        app = self._App()
        seen = []
        with patch.object(browser_screen, "DETAIL_DELAY", self.TICK):
            async with app.run_test(size=(100, 24)) as pilot:
                screen = BrowserScreen("Store")
                await app.push_screen(screen)
                await pilot.pause()

                async def walk():
                    for _ in range(3):
                        seen.append(await screen.browse(self._listing()))

                app.run_worker(walk())
                for _ in range(4):
                    await pilot.pause()
                await pilot.pause(self.WAITED)
                await pilot.pause(self.WAITED)
        self.assertEqual([Detailed("r-1")], [one for one in seen if one is not None])

    async def test_coming_back_to_a_row_asks_again(self):
        # Deliberate. What is remembered is the row being looked at, not every row
        # ever looked at: a body can change, and a set of ids that outlived the
        # place they came from would answer for a different listing's "1".
        app = self._App()
        seen = []
        with patch.object(browser_screen, "DETAIL_DELAY", self.TICK):
            async with app.run_test(size=(100, 24)) as pilot:
                screen = BrowserScreen("Store")
                await app.push_screen(screen)
                await pilot.pause()

                async def walk():
                    for _ in range(4):
                        seen.append(await screen.browse(self._listing()))

                app.run_worker(walk())
                for _ in range(4):
                    await pilot.pause()
                await pilot.pause(self.WAITED)
                await pilot.press("down")
                await pilot.pause(self.WAITED)
                await pilot.press("up")
                await pilot.pause(self.WAITED)
        self.assertEqual(
            [Detailed("r-1"), Detailed("r-2"), Detailed("r-1")],
            [one for one in seen if one is not None],
        )


class TheUserKeepsTheirPlace(unittest.IsolatedAsyncioTestCase):
    """A refresh puts them back on the row they were on, by its id."""

    class _App(App):
        pass

    ROWS = (Row("a", "A"), Row("b", "B"), Row("c", "C"))

    async def test_a_redraw_restores_the_focused_row(self):
        # Without it `on-demand` cannot work at all: the listing that answers a
        # selection would move the selection, which would ask again.
        app = self._App()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = BrowserScreen("Store")
            await app.push_screen(screen)
            await pilot.pause()
            first = Listing(breadcrumb=("Root",), pane=True, rows=self.ROWS)

            async def walk():
                await screen.browse(first)
                await screen.browse(replace(first, hint="again"))

            app.run_worker(walk())
            for _ in range(4):
                await pilot.pause()
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            self.assertIsInstance(screen.focused, BrowseRow)
            self.assertEqual("c", screen.focused.row.id)

    async def test_a_row_that_is_gone_falls_back_to_the_first(self):
        app = self._App()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = BrowserScreen("Store")
            await app.push_screen(screen)
            await pilot.pause()
            first = Listing(breadcrumb=("Root",), pane=True, rows=self.ROWS)

            async def walk():
                await screen.browse(first)
                await screen.browse(replace(first, rows=(Row("z", "Z"),)))

            app.run_worker(walk())
            for _ in range(4):
                await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            self.assertEqual("z", screen.focused.row.id)


class TheNoteDialog(unittest.IsolatedAsyncioTestCase):
    """One field or many lines, and the same dialog either way."""

    class _App(App):
        pass

    async def _shown(self, multiline):
        app = self._App()
        async with app.run_test(size=(100, 24)) as pilot:
            screen = InputScreen("Review note", "acc", "start", multiline)
            await app.push_screen(screen)
            for _ in range(3):
                await pilot.pause()
            return screen, list(screen.query(TextArea)), list(screen.query(Input))

    async def test_a_note_is_a_text_area_and_a_name_is_a_line(self):
        _, areas, inputs = await self._shown(True)
        self.assertEqual(1, len(areas))
        self.assertEqual([], inputs)
        _, areas, inputs = await self._shown(False)
        self.assertEqual([], areas)
        self.assertEqual(1, len(inputs))

    async def test_a_note_opens_on_what_the_command_already_had(self):
        _, areas, _ = await self._shown(True)
        self.assertEqual("start", areas[0].text)

    async def test_what_was_typed_comes_back_whole(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(100, 24)) as pilot:
            async def ask():
                answer["text"] = await app.push_screen_wait(
                    InputScreen("Review note", "acc", "", True)
                )

            app.run_worker(ask())
            for _ in range(4):
                await pilot.pause()
            app.screen.query_one(TextArea).text = "  first line\nsecond line\n\n"
            await pilot.pause()
            await pilot.press("tab")
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
        self.assertEqual("  first line\nsecond line", answer.get("text"))

    async def test_escape_is_still_a_cancel(self):
        app = self._App()
        answer = {}
        async with app.run_test(size=(100, 24)) as pilot:
            async def ask():
                answer["text"] = await app.push_screen_wait(
                    InputScreen("Review note", "acc", "", True)
                )

            app.run_worker(ask())
            for _ in range(4):
                await pilot.pause()
            await pilot.press("escape")
            for _ in range(4):
                await pilot.pause()
        self.assertEqual("", answer.get("text"))
        self.assertEqual("@dti:answer", answered(answer["text"]))
