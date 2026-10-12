"""The run panel's stdin row: what a question does to the keyboard and the tabs.

The strip is counted rather than eyeballed - a rebuilt strip looks almost right
and flickers only while something is asking. `docs/pitfalls.md` 11.1 is why.
"""

import asyncio
import unittest
from contextlib import asynccontextmanager

from textual.app import App
from textual.widgets import Button, Input

from company_tui.domain.options import Option, OptionKind
from company_tui.presentation import session_tabs
from company_tui.presentation.run_screen import RunScreen
from company_tui.presentation.session import SessionRegistry, SessionStatus


class _Panel(App):
    """One panel over two tabs, which is the least that can show a strip."""

    def __init__(self, tabs: int = 2) -> None:
        super().__init__()
        self.sessions = SessionRegistry()
        self.session = self.sessions.create("first", None, {"capability": "probe"})
        self.session.load(
            "Probe", [Option(key="name", label="Name", kind=OptionKind.TEXT)]
        )
        self.session.opened = True
        for extra in range(1, tabs):
            beside = self.sessions.create(
                f"other-{extra}", None, {"capability": "probe"}
            )
            beside.opened = True
        self.panel = RunScreen(self.session, self.sessions)

    def on_mount(self) -> None:
        self.push_screen(self.panel)


@asynccontextmanager
async def _running(tabs: int = 2):
    """A panel with a run going, which is the only state that asks anything."""
    app = _Panel(tabs)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.session.started = True
        app.session.changed()
        await pilot.pause()
        yield app, pilot


class WhatAQuestionDoesToTheTabs(unittest.IsolatedAsyncioTestCase):
    """A status is a colour on one tab, not a reason to build the strip again."""

    def setUp(self):
        self.built: list[str] = []
        real = session_tabs.SessionTab.__init__

        def counted(tab, session, active):
            self.built.append(session.name)
            real(tab, session, active)

        session_tabs.SessionTab.__init__ = counted
        self.addCleanup(setattr, session_tabs.SessionTab, "__init__", real)

    async def test_asking_and_answering_builds_no_tabs_at_all(self):
        async with _running() as (app, pilot):
            self.built.clear()
            for _ in range(3):
                asked = asyncio.ensure_future(app.session.prompt("Which?"))
                await pilot.pause()
                app.session.reply("yes")
                await asked
                await pilot.pause()
            self.assertEqual([], self.built)

    async def test_the_strip_is_never_holding_two_of_every_tab(self):
        # Removal is answered on the next pass but mounting is not, so a strip
        # rebuilt mid-question carried both sets for a frame and jumped width.
        async with _running(tabs=4) as (app, pilot):
            strip = app.panel.query_one("#tabs")
            settled = len(strip.children)
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await asyncio.sleep(0)
            self.assertEqual(settled, len(strip.children))
            app.session.reply("yes")
            await asked
            await pilot.pause()

    async def test_the_tab_still_says_which_run_is_asking(self):
        # The whole point of the status, so restating in place has to keep it.
        async with _running() as (app, pilot):
            tab = next(iter(app.panel.query(session_tabs.SessionTab)))
            self.assertFalse(tab.has_class("-asking"))
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await pilot.pause()
            self.assertTrue(tab.has_class("-asking"))
            self.assertEqual(SessionStatus.ASKING, app.session.status)
            app.session.reply("yes")
            await asked
            await pilot.pause()
            self.assertFalse(tab.has_class("-asking"))


class WhatAQuestionDoesToTheKeyboard(unittest.IsolatedAsyncioTestCase):
    """It borrows the focus, so it has to give it back."""

    async def test_the_box_takes_the_keyboard_while_it_is_asking(self):
        async with _running() as (app, pilot):
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await pilot.pause()
            self.assertEqual("stdin", app.panel.focused.id)
            app.session.reply("yes")
            await asked

    async def test_answering_does_not_leave_the_keyboard_nowhere(self):
        # Disabling a focused widget blurs it and focuses nothing else, so Enter
        # answered the question and left the panel unable to hear another key.
        async with _running() as (app, pilot):
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await pilot.pause()
            await pilot.press("y", "e", "s")
            await pilot.press("enter")
            self.assertEqual("yes", await asked)
            await pilot.pause()
            self.assertIsNotNone(app.panel.focused)
            self.assertEqual("run", app.panel.focused.id)

    async def test_the_send_button_hands_it_back_the_same_way(self):
        # Textual moves focus to the next sibling when a focused button is
        # disabled, which put it on COPY - a button about something else.
        async with _running() as (app, pilot):
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await pilot.pause()
            await pilot.press("y")
            await pilot.click("#stdin-send")
            self.assertEqual("y", await asked)
            await pilot.pause()
            self.assertEqual("run", app.panel.focused.id)

    async def test_a_line_of_output_does_not_take_the_box_away(self):
        async with _running() as (app, pilot):
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await pilot.pause()
            await pilot.press("m", "a")
            app.session.write("still working", marker="output")
            await pilot.pause()
            await pilot.press("i", "n")
            await pilot.pause()
            box = app.panel.query_one("#stdin", Input)
            self.assertEqual("main", box.value)
            self.assertTrue(box.has_focus)
            app.session.reply("main")
            await asked


class WhatTheRowOffers(unittest.IsolatedAsyncioTestCase):
    """Every key named under the box has to be one the box answers."""

    async def test_the_row_names_only_the_key_it_has(self):
        # `Ctrl+Enter - New line` sat here over a single-line `Input` with nothing
        # bound to it: a hint for a key that was never going to do anything.
        async with _running() as (app, _pilot):
            named = {hint.id for hint in app.panel.query("#stdin-keys KeyHint")}
            self.assertEqual({"stdin-hint"}, named)

    async def test_the_box_is_empty_and_closed_until_something_asks(self):
        async with _running() as (app, _pilot):
            box = app.panel.query_one("#stdin", Input)
            send = app.panel.query_one("#stdin-send", Button)
            self.assertTrue(box.disabled)
            self.assertTrue(send.disabled)
            self.assertFalse(app.panel.has_class("-asking"))

    async def test_what_was_typed_is_gone_once_it_has_been_answered(self):
        async with _running() as (app, pilot):
            asked = asyncio.ensure_future(app.session.prompt("Which?"))
            await pilot.pause()
            await pilot.press("y")
            await pilot.press("enter")
            await asked
            await pilot.pause()
            self.assertEqual("", app.panel.query_one("#stdin", Input).value)


if __name__ == "__main__":
    unittest.main()
