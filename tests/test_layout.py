"""The layout document, the page that edits it, and the interface it comes out of."""

import asyncio
import dataclasses
import json
import re
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from company_tui.application.registry import CapabilityRegistry
from company_tui.domain.capability import Capability, CapabilityInfo
from company_tui.domain.config import ConfigScope, Settings
from company_tui.domain.layout import (
    LARGEST,
    MAX_CARDS_PER_ROW,
    SMALLEST,
    Layout,
    Menu,
    Palette,
    Window,
    arrange,
    is_colour,
    read_layout,
    write_layout,
)
from company_tui.domain.settings_document import read_document, write_document
from company_tui.infrastructure.builder import PAGE, SCRIPT, BuilderServer
from company_tui.infrastructure.config import FileConfig, render
from company_tui.infrastructure.window_shape import DEFAULT_PLAN, plan_from
from company_tui.presentation.branding import APP_THEME, theme_from


def _open(url: str, body: bytes | None = None):
    """Reach our own loopback server, and refuse to reach anything else.

    Which is exactly what the `S310` audit is asking about, so the check here is a
    real one rather than a directive over a call that could go anywhere.
    """
    if not url.startswith("http://127.0.0.1:"):
        raise AssertionError(f"not this machine: {url}")
    request = urllib.request.Request(  # noqa: S310 - the scheme is checked above
        url,
        body,
        {"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    return urllib.request.urlopen(request, timeout=5)  # noqa: S310 - and again here


CARDS = (
    ("scaffold", "Scaffold", "Create projects"),
    ("build", "Build", "Run builds"),
    ("scripts", "Scripts", "This project's commands"),
)


class NothingArrangedIsNothingChanged(unittest.TestCase):
    """Every default is what the code held, so an untouched toolbox is untouched."""

    def test_the_window_defaults_are_the_constants_that_were_there(self):
        self.assertEqual(DEFAULT_PLAN, plan_from(Window()))

    def test_the_palette_defaults_are_the_theme_that_was_there(self):
        built = theme_from(Palette())
        self.assertEqual(APP_THEME.name, built.name)
        for key, colour in Palette().colours.items():
            self.assertEqual(getattr(APP_THEME, key), colour, key)

    def test_the_theme_keeps_the_apps_own_name_whatever_the_colours(self):
        # What is registered and what `TuiConsole` activates cannot be allowed to
        # drift: a mismatch there is an unstyled app.
        odd = theme_from(dataclasses.replace(Palette(), primary="#000000"))
        self.assertEqual(APP_THEME.name, odd.name)

    def test_a_settings_file_nobody_arranged_says_nothing_about_it(self):
        self.assertNotIn("[layout", render(Settings()))

    def test_a_port_that_never_heard_of_it_answers_with_the_defaults(self):
        from company_tui.domain.config import ConfigPort

        self.assertEqual(Layout(), ConfigPort.layout(object()))


class ReadingALayout(unittest.TestCase):
    def test_it_comes_back_whole(self):
        arranged = Layout(
            palette=dataclasses.replace(Palette(), accent="#FF8800"),
            window=Window(1240, 1000, 900, 700),
            menu=Menu(cards_per_row=2, order=("build",), hidden=("scripts",)),
        )
        read, problems = read_layout(write_layout(arranged))
        self.assertEqual(arranged, read)
        self.assertEqual((), problems)

    def test_an_empty_document_is_the_defaults(self):
        read, problems = read_layout({})
        self.assertEqual(Layout(), read)
        self.assertEqual((), problems)

    def test_something_that_is_not_a_layout_says_so(self):
        for document in ("layout", [], 7, None):
            read, problems = read_layout(document)
            self.assertEqual(Layout(), read)
            self.assertEqual(1, len(problems), repr(document))

    def test_a_document_from_a_later_version_is_read_as_far_as_it_goes(self):
        read, problems = read_layout({"schema": 99, "menu": {"cards_per_row": 2}})
        self.assertEqual(2, read.menu.cards_per_row)
        self.assertTrue(any("schema" in one for one in problems))


class TheColours(unittest.TestCase):
    """An unreadable colour reaches Textual as a theme it refuses."""

    def test_what_counts_as_one(self):
        for value in ("#fff", "#FFFFFF", "#0a1B2c"):
            self.assertTrue(is_colour(value), value)
        for value in ("fff", "#ff", "#fffff", "#gggggg", "red", "", None, 0, "#ffffff "):
            self.assertFalse(is_colour(value), repr(value))

    def test_one_that_is_not_a_colour_is_reported_and_the_old_one_kept(self):
        read, problems = read_layout({"palette": {"accent": "burnt orange"}})
        self.assertEqual(Palette().accent, read.palette.accent)
        self.assertTrue(any("palette.accent" in one for one in problems))

    def test_the_others_are_taken_even_so(self):
        read, _ = read_layout({"palette": {"accent": "nope", "primary": "#101010"}})
        self.assertEqual("#101010", read.palette.primary)

    def test_a_palette_that_is_not_an_object_is_reported(self):
        read, problems = read_layout({"palette": "#FF8800"})
        self.assertEqual(Palette(), read.palette)
        self.assertTrue(any("palette" in one for one in problems))

    def test_a_key_it_has_never_heard_of_is_simply_not_a_colour_it_draws(self):
        read, problems = read_layout({"palette": {"chartreuse": "#7FFF00"}})
        self.assertEqual(Palette(), read.palette)
        self.assertEqual((), problems)


class TheWindow(unittest.TestCase):
    def test_a_size_that_is_not_a_number_is_reported(self):
        for size in ("1200", None, 12.5, True):
            read, problems = read_layout({"window": {"start_width": size}})
            self.assertEqual(Window().start_width, read.window.start_width, repr(size))
            self.assertTrue(problems, repr(size))

    def test_a_size_nobody_meant_is_refused(self):
        for size in (SMALLEST - 1, LARGEST + 1, 0, -900):
            read, problems = read_layout({"window": {"min_height": size}})
            self.assertEqual(Window().min_height, read.window.min_height, size)
            self.assertTrue(any("min_height" in one for one in problems), size)

    def test_a_floor_above_the_opening_size_is_brought_down(self):
        # A floor bigger than the window it is the floor for would resize the
        # window for opening at the size it was told to open at.
        read, problems = read_layout(
            {"window": {"start_width": 900, "start_height": 800,
                        "min_width": 1600, "min_height": 1500}}
        )
        self.assertEqual(900, read.window.min_width)
        self.assertEqual(800, read.window.min_height)
        self.assertTrue(any("smallest" in one for one in problems))


class TheMenu(unittest.TestCase):
    KEYS = ("scaffold", "build", "scripts", "doctor")

    def test_no_order_is_the_order_they_were_registered_in(self):
        self.assertEqual(self.KEYS, arrange(self.KEYS, Menu()))

    def test_an_order_is_followed(self):
        menu = Menu(order=("doctor", "scripts"))
        self.assertEqual(("doctor", "scripts", "scaffold", "build"), arrange(self.KEYS, menu))

    def test_a_key_the_order_never_named_keeps_its_place_behind_the_ones_it_did(self):
        # A layout written before a capability existed must not be able to hide one.
        self.assertEqual(
            ("build", "scaffold", "scripts", "doctor"),
            arrange(self.KEYS, Menu(order=("build",))),
        )

    def test_a_key_that_is_gone_is_simply_not_there(self):
        self.assertEqual(("build", "scaffold"), arrange(("scaffold", "build"), Menu(order=("build", "wallet"))))

    def test_hiding_leaves_it_off(self):
        self.assertEqual(("scaffold", "build", "doctor"), arrange(self.KEYS, Menu(hidden=("scripts",))))

    def test_hiding_all_of_them_is_refused(self):
        # A menu with no cards is an app with no way in, and the file saying so
        # would have to be edited by hand to escape it.
        self.assertEqual(self.KEYS, arrange(self.KEYS, Menu(hidden=self.KEYS)))

    def test_a_width_outside_what_reads_is_refused(self):
        for across in (0, -1, MAX_CARDS_PER_ROW + 1, "3", None, True):
            read, problems = read_layout({"menu": {"cards_per_row": across}})
            self.assertEqual(3, read.menu.cards_per_row, repr(across))
            self.assertTrue(any("cards_per_row" in one for one in problems), repr(across))

    def test_a_list_that_is_not_keys_is_reported(self):
        for listed in ("build", [1, 2], ["build", ""], {"a": 1}):
            read, problems = read_layout({"menu": {"order": listed}})
            self.assertEqual((), read.menu.order, repr(listed))
            self.assertTrue(any("menu.order" in one for one in problems), repr(listed))

    def test_a_key_named_twice_is_named_once(self):
        read, _ = read_layout({"menu": {"order": ["build", "build", "scaffold"]}})
        self.assertEqual(("build", "scaffold"), read.menu.order)


class _Card(Capability):
    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def info(self) -> CapabilityInfo:
        return CapabilityInfo(key=self._key, name=self._key.title(), description="")

    async def execute(self) -> int:
        return 0


class TheRegistryFollowsIt(unittest.TestCase):
    CARDS = tuple(_Card(key) for key in ("scaffold", "build", "scripts"))

    def test_with_no_menu_it_is_registration_order(self):
        registry = CapabilityRegistry(self.CARDS)
        self.assertEqual(
            ("scaffold", "build", "scripts"), tuple(c.info.key for c in registry.all())
        )

    def test_a_menu_reorders_and_hides(self):
        registry = CapabilityRegistry(self.CARDS, Menu(order=("scripts",), hidden=("build",)))
        self.assertEqual(("scripts", "scaffold"), tuple(c.info.key for c in registry.all()))

    def test_off_the_menu_is_not_gone(self):
        # `--start` naming a hidden capability still opens it, and the builder has
        # to be able to list one to drag it back.
        registry = CapabilityRegistry(self.CARDS, Menu(hidden=("build",)))
        self.assertIsNotNone(registry.get("build"))
        self.assertEqual(3, len(registry.every()))


class TheSettingsFileCarriesIt(unittest.TestCase):
    ARRANGED = Layout(
        palette=dataclasses.replace(Palette(), accent="#FF8800"),
        window=Window(1240, 1000, 900, 700),
        menu=Menu(cards_per_row=2, order=("build",), hidden=("scripts",)),
    )

    def _saved(self, layout):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = FileConfig(Path(folder.name) / "dti.toml", Path(folder.name) / "user.toml")
        config.save(dataclasses.replace(Settings(), layout=layout), ConfigScope.PROJECT)
        return config, (Path(folder.name) / "dti.toml").read_text(encoding="utf-8")

    def test_it_survives_the_file(self):
        config, _ = self._saved(self.ARRANGED)
        self.assertEqual(self.ARRANGED, config.layout())

    def test_only_what_was_arranged_is_written_down(self):
        _, body = self._saved(self.ARRANGED)
        self.assertIn("[layout.palette]", body)
        self.assertIn('accent = "#FF8800"', body)
        self.assertNotIn("primary", body)
        self.assertIn('order = ["build"]', body)

    def test_an_untouched_layout_writes_nothing(self):
        config, body = self._saved(Layout())
        self.assertNotIn("[layout", body)
        self.assertEqual(Layout(), config.layout())

    def test_the_exported_document_carries_it_both_ways(self):
        settings = dataclasses.replace(Settings(), layout=self.ARRANGED)
        read, problems = read_document(write_document(settings), Settings())
        self.assertEqual(self.ARRANGED, read.layout)
        self.assertEqual((), problems)

    def test_a_document_that_predates_it_keeps_what_is_set(self):
        document = write_document(Settings())
        del document["layout"]
        read, problems = read_document(document, dataclasses.replace(Settings(), layout=self.ARRANGED))
        self.assertEqual(self.ARRANGED, read.layout)
        self.assertEqual((), problems)

    def test_an_unreadable_layout_is_reported_under_its_own_name(self):
        document = write_document(Settings())
        document["layout"]["palette"]["accent"] = "orange"
        _, problems = read_document(document, Settings())
        self.assertTrue(any(one.startswith("layout: ") for one in problems))


class ThePageAndItsScript(unittest.TestCase):
    """The page is program text here, so nothing checks it but a test."""

    def test_every_id_the_script_reaches_for_is_in_the_page(self):
        # A renamed id is a null dereference and a blank page, with nothing said.
        wanted = set(re.findall(r'\$\("([\w-]+)"\)', SCRIPT))
        present = set(re.findall(r'id="([\w-]+)"', PAGE))
        self.assertTrue(wanted)
        self.assertEqual(set(), wanted - present, "ids the script expects and the page lacks")

    def test_the_page_asks_for_the_assets_the_server_serves(self):
        self.assertIn("builder.css?t=TOKEN", PAGE)
        self.assertIn("builder.js?t=TOKEN", PAGE)

    def test_the_token_is_never_written_into_the_page_as_a_constant(self):
        self.assertNotIn("TOKEN=", SCRIPT)
        self.assertIn("URLSearchParams(location.search)", SCRIPT)


class _Loop(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = BuilderServer(Layout(), CARDS, asyncio.get_running_loop())
        self.url = self.server.start()
        self.base, _, self.query = self.url.partition("?")
        self.base = self.base.rstrip("/")
        self.addCleanup(self.server.stop)

    def _get(self, path, query=None):
        asked = self.query if query is None else query
        with _open(f"{self.base}{path}?{asked}") as answer:
            return answer.status, answer.read()

    def _post(self, path, payload):
        target = f"{self.base}{path}?{self.query}"
        with _open(target, json.dumps(payload).encode()) as answer:
            return answer.status, json.loads(answer.read())


class TheServerHandsOverThePage(_Loop):
    async def test_it_is_only_on_this_machine(self):
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))

    async def test_the_page_and_its_assets_come_back(self):
        code, page = self._get("/")
        self.assertEqual(200, code)
        self.assertIn(b"<title>Layout</title>", page)
        self.assertEqual(200, self._get("/builder.css")[0])
        self.assertEqual(200, self._get("/builder.js")[0])

    async def test_it_hands_over_the_layout_and_every_card(self):
        _, body = self._get("/layout")
        body = json.loads(body)
        self.assertEqual(write_layout(Layout()), body["layout"])
        self.assertEqual(
            ["scaffold", "build", "scripts"], [one["key"] for one in body["capabilities"]]
        )


class NothingWithoutTheToken(_Loop):
    """Localhost is not a boundary: any program here can reach a loopback port."""

    def _refused(self, path, query="t=wrong"):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get(path, query)
        return caught.exception.code

    async def test_a_wrong_token_gets_nothing(self):
        self.assertEqual(404, self._refused("/"))
        self.assertEqual(404, self._refused("/layout"))

    async def test_no_token_gets_nothing(self):
        self.assertEqual(404, self._refused("/", ""))

    async def test_a_refusal_never_confirms_the_path(self):
        # 404 rather than 403, and the same for a path that does not exist.
        self.assertEqual(404, self._refused("/layout"))
        self.assertEqual(404, self._refused("/nowhere"))

    async def test_there_is_no_filesystem_to_walk(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/../../../etc/passwd")
        self.assertEqual(404, caught.exception.code)


class WhatThePagePosts(_Loop):
    async def test_an_arrangement_is_held_and_reported_on(self):
        document = write_layout(Layout())
        document["palette"]["accent"] = "#FF8800"
        document["menu"]["order"] = ["scripts", "build"]
        code, body = self._post("/layout", document)
        self.assertEqual(200, code)
        self.assertEqual([], body["problems"])
        self.assertEqual("#FF8800", self.server.layout.palette.accent)
        self.assertEqual(("scripts", "build"), self.server.layout.menu.order)

    async def test_what_could_not_be_taken_is_said_rather_than_guessed(self):
        document = write_layout(Layout())
        document["palette"]["accent"] = "burnt orange"
        _, body = self._post("/layout", document)
        self.assertTrue(any("palette.accent" in one for one in body["problems"]))
        self.assertEqual(Palette().accent, self.server.layout.palette.accent)

    async def test_the_rest_of_an_arrangement_survives_one_bad_field(self):
        document = write_layout(Layout())
        document["palette"]["accent"] = "orange"
        document["menu"]["cards_per_row"] = 2
        self._post("/layout", document)
        self.assertEqual(2, self.server.layout.menu.cards_per_row)

    async def test_something_that_is_not_json_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            _open(f"{self.base}/layout?{self.query}", b"not json")
        self.assertEqual(400, caught.exception.code)

    async def test_an_absurd_body_is_refused_and_the_refusal_arrives(self):
        # It is read away first. Answering while the client is still writing aborts
        # the connection under it, and the refusal never gets there
        # (`docs/pitfalls.md` 10.1) - intermittently, which is worse.
        for _ in range(3):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                _open(f"{self.base}/layout?{self.query}", b"{}" + b" " * 300_000)
            self.assertEqual(413, caught.exception.code)

    async def test_nothing_absurd_was_taken_from_it(self):
        _open_failed = False
        try:
            _open(f"{self.base}/layout?{self.query}", b"{}" + b" " * 300_000)
        except urllib.error.HTTPError:
            _open_failed = True
        self.assertTrue(_open_failed)
        self.assertEqual(Layout(), self.server.layout)

    async def test_reset_puts_everything_back(self):
        document = write_layout(Layout())
        document["palette"]["accent"] = "#FF8800"
        self._post("/layout", document)
        self._post("/reset", {})
        self.assertEqual(Layout(), self.server.layout)


class WhenItIsOver(_Loop):
    async def test_saving_and_closing_is_what_finishes_it(self):
        self.assertFalse(self.server.finished.is_set())
        self._post("/done", {})
        await asyncio.wait_for(self.server.finished.wait(), 3)
        self.assertTrue(self.server.finished.is_set())

    async def test_the_port_closes_with_the_run(self):
        self.server.stop()
        with self.assertRaises(urllib.error.URLError):
            self._get("/")

    async def test_stopping_twice_is_not_an_error(self):
        self.server.stop()
        self.server.stop()

    async def test_the_server_never_writes_anything(self):
        # It hands back a document; saving it goes through `ConfigPort` like every
        # other setting, so there is one place that writes settings.
        self.assertFalse(hasattr(self.server, "save"))
        self.assertIsInstance(self.server.layout, Layout)
