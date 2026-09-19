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
from company_tui.domain.commands import Command
from company_tui.domain.config import ConfigScope, Settings
from company_tui.domain.layout import (
    DEFAULT_THEME,
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
from company_tui.infrastructure.builder import BuilderServer
from company_tui.infrastructure.builder_page import PAGE, SCRIPT
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


def _themed(colours):
    """A layout document carrying one theme with these colours in it."""
    return {"themes": {DEFAULT_THEME: colours}}


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
            themes={DEFAULT_THEME: dataclasses.replace(Palette(), accent="#FF8800")},
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
        read, problems = read_layout(_themed({"accent": "burnt orange"}))
        self.assertEqual(Palette().accent, read.palette.accent)
        self.assertTrue(any("palette.accent" in one for one in problems))

    def test_the_others_are_taken_even_so(self):
        read, _ = read_layout(_themed({"accent": "nope", "primary": "#101010"}))
        self.assertEqual("#101010", read.palette.primary)

    def test_a_palette_that_is_not_an_object_is_reported(self):
        read, problems = read_layout({"themes": {DEFAULT_THEME: "#FF8800"}})
        self.assertEqual(Palette(), read.palette)
        self.assertTrue(any("palette" in one for one in problems))

    def test_a_key_it_has_never_heard_of_is_simply_not_a_colour_it_draws(self):
        read, problems = read_layout(_themed({"chartreuse": "#7FFF00"}))
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
        themes={
            DEFAULT_THEME: Palette(),
            "dusk": dataclasses.replace(Palette(), accent="#FF8800"),
        },
        theme="dusk",
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
        self.assertIn("[layout.themes.dusk]", body)
        self.assertIn('accent = "#FF8800"', body)
        self.assertNotIn("primary", body)
        self.assertIn('theme = "dusk"', body)
        self.assertIn('order = ["build"]', body)

    def test_a_theme_that_equals_the_defaults_is_still_written_down(self):
        # It is still a theme somebody made and can switch to; a table left out
        # because its colours happen to match is a theme they lose.
        _, body = self._saved(self.ARRANGED)
        self.assertIn("[layout.themes.default]", body)

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
        document["layout"]["themes"][DEFAULT_THEME]["accent"] = "orange"
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

    def test_every_pane_has_a_tab_that_reaches_it(self):
        # A pane with no button is a section nobody can get to, and it looks like
        # nothing at all rather than like a mistake.
        panes = set(re.findall(r'data-tab="([\w-]+)"', PAGE))
        tabs = set(re.findall(r'\["(\w+)", "[^"]+"\],', SCRIPT))
        self.assertTrue(panes)
        self.assertEqual(set(), panes - tabs)

    def test_the_page_asks_for_the_assets_the_server_serves(self):
        self.assertIn("builder.css?t=TOKEN", PAGE)
        self.assertIn("builder.js?t=TOKEN", PAGE)

    def test_the_token_is_never_written_into_the_page_as_a_constant(self):
        self.assertNotIn("TOKEN=", SCRIPT)
        self.assertIn("URLSearchParams(location.search)", SCRIPT)


class _Loop(unittest.IsolatedAsyncioTestCase):
    """A live server, on a loopback port, for the length of one test."""

    async def asyncSetUp(self):
        self.server = BuilderServer(
            Settings(), CARDS, asyncio.get_running_loop(), where="dti.toml"
        )
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

    def _document(self):
        return json.loads(self._get("/document")[1])["document"]

    def _send(self, document):
        return self._post("/document", document)[1]


class TheServerHandsOverThePage(_Loop):
    async def test_it_is_only_on_this_machine(self):
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))

    async def test_the_page_and_its_assets_come_back(self):
        code, page = self._get("/")
        self.assertEqual(200, code)
        self.assertIn(b"<title>Builder</title>", page)
        self.assertEqual(200, self._get("/builder.css")[0])
        self.assertEqual(200, self._get("/builder.js")[0])

    async def test_it_hands_over_the_whole_settings_document(self):
        # The same one App Setup exports, so nothing here decides what a setting is.
        body = json.loads(self._get("/document")[1])
        self.assertEqual(write_document(Settings()), body["document"])

    async def test_it_hands_over_every_card_and_the_channels_and_the_file(self):
        body = json.loads(self._get("/document")[1])
        self.assertEqual(
            ["scaffold", "build", "scripts"], [one["key"] for one in body["capabilities"]]
        )
        self.assertEqual(
            ["official", "prerelease", "any"], [one["value"] for one in body["channels"]]
        )
        self.assertEqual("dti.toml", body["where"])


class NothingWithoutTheToken(_Loop):
    """Localhost is not a boundary: any program here can reach a loopback port."""

    def _refused(self, path, query="t=wrong"):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get(path, query)
        return caught.exception.code

    async def test_a_wrong_token_gets_nothing(self):
        self.assertEqual(404, self._refused("/"))
        self.assertEqual(404, self._refused("/document"))

    async def test_no_token_gets_nothing(self):
        self.assertEqual(404, self._refused("/", ""))

    async def test_a_refusal_never_confirms_the_path(self):
        # 404 rather than 403, and the same for a path that does not exist.
        self.assertEqual(404, self._refused("/document"))
        self.assertEqual(404, self._refused("/nowhere"))

    async def test_there_is_no_filesystem_to_walk(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/../../../etc/passwd")
        self.assertEqual(404, caught.exception.code)


class Designing(_Loop):
    """Themes: add one, recolour it, switch to it, and delete one."""

    async def test_a_theme_can_be_added_and_made_the_one_in_use(self):
        document = self._document()
        document["layout"]["themes"]["dusk"] = dict(
            document["layout"]["themes"][DEFAULT_THEME]
        )
        document["layout"]["themes"]["dusk"]["accent"] = "#FF8800"
        document["layout"]["theme"] = "dusk"
        self.assertEqual([], self._send(document)["problems"])

        layout = self.server.settings.layout
        self.assertEqual({DEFAULT_THEME, "dusk"}, set(layout.themes))
        self.assertEqual("dusk", layout.theme)
        self.assertEqual("#FF8800", layout.palette.accent)

    async def test_a_theme_can_be_deleted_even_the_one_it_started_with(self):
        document = self._document()
        document["layout"]["themes"]["dusk"] = dict(
            document["layout"]["themes"][DEFAULT_THEME]
        )
        document["layout"]["theme"] = "dusk"
        document = self._send(document)["document"]
        del document["layout"]["themes"][DEFAULT_THEME]
        self._send(document)

        layout = self.server.settings.layout
        self.assertEqual(["dusk"], sorted(layout.themes))
        self.assertEqual("dusk", layout.theme)

    async def test_the_last_theme_cannot_be_deleted_away(self):
        # An interface has to be drawn in something, and `theme` has to point at
        # something. The page will not offer it either, but this is the floor.
        document = self._document()
        document["layout"]["themes"] = {}
        answer = self._send(document)
        self.assertTrue(any("default one was put back" in one for one in answer["problems"]))
        self.assertEqual([DEFAULT_THEME], sorted(self.server.settings.layout.themes))

    async def test_a_name_a_settings_file_could_not_hold_is_refused(self):
        document = self._document()
        document["layout"]["themes"]["not a key"] = {}
        answer = self._send(document)
        self.assertTrue(any("usable theme name" in one for one in answer["problems"]))
        self.assertNotIn("not a key", self.server.settings.layout.themes)


class TheMenuAndTheWindow(_Loop):
    async def test_an_arrangement_is_held(self):
        document = self._document()
        document["layout"]["menu"]["order"] = ["scripts", "build"]
        document["layout"]["menu"]["hidden"] = ["build"]
        document["layout"]["menu"]["cards_per_row"] = 2
        document["layout"]["window"]["start_width"] = 1240
        self.assertEqual([], self._send(document)["problems"])

        layout = self.server.settings.layout
        self.assertEqual(("scripts", "build"), layout.menu.order)
        self.assertEqual(("build",), layout.menu.hidden)
        self.assertEqual(2, layout.menu.cards_per_row)
        self.assertEqual(1240, layout.window.start_width)


class AddingAndDeletingSources(_Loop):
    """The add/update/delete the settings document already knew how to express."""

    PACK = {"url": "https://github.com/a/b.git", "ref": "v2"}

    def _with_pack(self):
        document = self._document()
        document["templates"]["react_native"] = dict(self.PACK)
        document["scripts"]["react_native"] = {"url": "https://github.com/a/c.git", "ref": ""}
        document["script_checks"]["react_native"] = False
        return self._send(document)["document"]

    async def test_a_template_pack_can_be_added(self):
        self._with_pack()
        held = self.server.settings.templates["react_native"]
        self.assertEqual("https://github.com/a/b.git", held.url)
        self.assertEqual("v2", held.ref)

    async def test_a_script_repository_and_its_watch_come_together(self):
        self._with_pack()
        self.assertIn("react_native", self.server.settings.scripts)
        self.assertEqual({"react_native": False}, dict(self.server.settings.script_checks))

    async def test_one_can_be_updated(self):
        document = self._with_pack()
        document["templates"]["react_native"]["ref"] = "main"
        self._send(document)
        self.assertEqual("main", self.server.settings.templates["react_native"].ref)

    async def test_one_can_be_deleted(self):
        # Which works because the document replaces the section rather than merging
        # it: a key that is not in what was sent is a key that is gone.
        document = self._with_pack()
        del document["templates"]["react_native"]
        del document["scripts"]["react_native"]
        del document["script_checks"]["react_native"]
        self._send(document)
        self.assertEqual({}, dict(self.server.settings.templates))
        self.assertEqual({}, dict(self.server.settings.scripts))

    async def test_one_with_no_url_is_not_written_down(self):
        document = self._document()
        document["templates"]["half"] = {"url": "", "ref": ""}
        self._send(document)
        self.assertNotIn("half", self.server.settings.templates)


class TheRestOfTheSettings(_Loop):
    async def test_the_workspace_the_feed_and_the_flags_all_travel(self):
        document = self._document()
        document["scaffold"]["bundle_prefix"] = "com.acme"
        document["scaffold"]["workspace_root"] = "~/work"
        document["updates"]["channel"] = "any"
        document["updates"]["repository"] = "acme/toolbox"
        document["experimental"]["browser_view"] = True
        self.assertEqual([], self._send(document)["problems"])

        held = self.server.settings
        self.assertEqual("com.acme", held.bundle_prefix)
        self.assertEqual("~/work", held.workspace_root)
        self.assertEqual("any", held.updates.channel)
        self.assertEqual("acme/toolbox", held.updates.repository)
        self.assertTrue(held.browser_view)


class WhatCouldNotBeTaken(_Loop):
    async def test_it_is_said_rather_than_guessed(self):
        document = self._document()
        document["layout"]["themes"][DEFAULT_THEME]["accent"] = "burnt orange"
        answer = self._send(document)
        self.assertTrue(any("palette.accent" in one for one in answer["problems"]))
        self.assertEqual(Palette().accent, self.server.settings.layout.palette.accent)

    async def test_the_rest_of_it_survives_one_bad_field(self):
        document = self._document()
        document["layout"]["themes"][DEFAULT_THEME]["accent"] = "orange"
        document["layout"]["menu"]["cards_per_row"] = 2
        self._send(document)
        self.assertEqual(2, self.server.settings.layout.menu.cards_per_row)

    async def test_the_document_comes_back_as_it_was_actually_read(self):
        # So a page showing a value the toolbox would not take corrects itself
        # rather than standing there claiming it was kept.
        document = self._document()
        document["layout"]["window"]["min_width"] = 99999
        answer = self._send(document)
        self.assertEqual(
            Window().min_width, answer["document"]["layout"]["window"]["min_width"]
        )

    async def test_something_that_is_not_json_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            _open(f"{self.base}/document?{self.query}", b"not json")
        self.assertEqual(400, caught.exception.code)

    async def test_an_absurd_body_is_refused_and_the_refusal_arrives(self):
        # It is read away first. Answering while the client is still writing aborts
        # the connection under it, and the refusal never gets there
        # (`docs/pitfalls.md` 10.1) - intermittently, which is worse.
        for _ in range(3):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                _open(f"{self.base}/document?{self.query}", b"{}" + b" " * 300_000)
            self.assertEqual(413, caught.exception.code)
        self.assertEqual(Settings(), self.server.settings)


class WhenItIsOver(_Loop):
    async def test_revert_goes_back_to_what_it_opened_with(self):
        document = self._document()
        document["scaffold"]["bundle_prefix"] = "com.acme"
        self._send(document)
        self.assertEqual("com.acme", self.server.settings.bundle_prefix)
        self._post("/revert", {})
        self.assertEqual(Settings(), self.server.settings)

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
        # It hands back settings; saving them goes through `ConfigPort` like every
        # other setting, so one place still writes them.
        self.assertFalse(hasattr(self.server, "save"))
        self.assertIsInstance(self.server.settings, Settings)


DECLARED = (
    Command(section="build", commands=("npm run build",), was="build"),
    Command(
        section="scaffold",
        key="screen",
        commands=("node finish.mjs",),
        kept=("template", "args"),
        was="scaffold.screen",
    ),
)


class TheProjectsOwnCommands(unittest.IsolatedAsyncioTestCase):
    """The page's other half: the commands, held the same way the settings are."""

    async def asyncSetUp(self):
        self.server = BuilderServer(
            Settings(),
            CARDS,
            asyncio.get_running_loop(),
            commands=DECLARED,
            manifest="C:/proj/dti.script.json",
        )
        self.url = self.server.start()
        self.base, _, self.query = self.url.partition("?")
        self.base = self.base.rstrip("/")
        self.addCleanup(self.server.stop)

    def _offered(self):
        with _open(f"{self.base}/document?{self.query}") as answer:
            return json.loads(answer.read())

    def _send(self, listed):
        target = f"{self.base}/commands?{self.query}"
        with _open(target, json.dumps({"commands": listed}).encode()) as answer:
            return json.loads(answer.read())

    async def test_they_are_handed_over_with_the_file_they_came_from(self):
        body = self._offered()
        self.assertEqual("C:/proj/dti.script.json", body["manifest"])
        self.assertEqual(
            ["build", "screen"], [one["key"] or one["section"] for one in body["commands"]]
        )

    async def test_what_the_builder_will_not_edit_travels_so_the_page_can_say_so(self):
        body = self._offered()
        self.assertEqual(["template", "args"], body["commands"][1]["kept"])

    async def test_a_command_can_be_changed(self):
        listed = self._offered()["commands"]
        listed[0]["commands"] = ["npm ci", "npm run build"]
        listed[0]["view"] = "browser"
        self._send(listed)
        held = self.server.commands[0]
        self.assertEqual(("npm ci", "npm run build"), held.commands)
        self.assertEqual("browser", held.view)

    async def test_one_can_be_added_and_one_deleted(self):
        listed = self._offered()["commands"]
        del listed[0]
        listed.append(
            {"section": "generate", "key": "hook", "description": "A hook",
             "commands": ["node hook.mjs"], "interactive": True, "view": "",
             "kept": [], "was": ""}
        )
        self._send(listed)
        self.assertEqual(
            ["scaffold.screen", "generate.hook"],
            [one.identifier for one in self.server.commands],
        )
        self.assertTrue(self.server.commands[1].interactive)

    async def test_a_rename_keeps_where_it_came_from(self):
        # Which is what lets the writer move what it carries rather than build a
        # new one and lose the template.
        listed = self._offered()["commands"]
        listed[1]["section"] = "generate"
        listed[1]["key"] = "page"
        self._send(listed)
        moved = self.server.commands[1]
        self.assertEqual("generate.page", moved.identifier)
        self.assertEqual("scaffold.screen", moved.was)
        self.assertEqual(("template", "args"), moved.kept)

    async def test_an_entry_it_cannot_read_is_simply_not_a_command(self):
        # Nothing is judged here - `write_commands` is the one reader that decides
        # what a manifest may hold.
        self._send(["not a command", 7, None])
        self.assertEqual((), self.server.commands)

    async def test_revert_puts_them_back_too(self):
        self._send([])
        self.assertEqual((), self.server.commands)
        with _open(f"{self.base}/revert?{self.query}", b"{}"):
            pass
        self.assertEqual(DECLARED, self.server.commands)

    async def test_a_project_declaring_none_offers_none(self):
        bare = BuilderServer(Settings(), CARDS, asyncio.get_running_loop())
        url = bare.start()
        base, _, query = url.partition("?")
        try:
            with _open(f"{base.rstrip('/')}/document?{query}") as answer:
                body = json.loads(answer.read())
            self.assertEqual("", body["manifest"])
            self.assertEqual([], body["commands"])
        finally:
            bare.stop()
