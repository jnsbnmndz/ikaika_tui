"""The recently-picked directories: the ordering rules, the store, and the picker."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.app import App
from textual.widgets import DirectoryTree, Static

from company_tui.domain.recent import LIMIT, remember
from company_tui.infrastructure.recent_file import FileRecentPaths
from company_tui.presentation.path_screen import PathScreen


class Ordering(unittest.TestCase):
    def test_the_newest_goes_first(self):
        self.assertEqual(("b", "a"), remember(("a",), "b"))

    def test_a_repeat_moves_rather_than_duplicating(self):
        self.assertEqual(("a", "c", "b"), remember(("c", "b", "a"), "a"))

    def test_the_list_is_capped(self):
        many = tuple(str(number) for number in range(LIMIT + 5))
        self.assertEqual(LIMIT, len(remember(many, "new")))
        self.assertEqual("new", remember(many, "new")[0])

    def test_blank_is_not_remembered(self):
        self.assertEqual(("a",), remember(("a",), "   "))

    def test_it_does_not_mutate_what_it_was_given(self):
        original = ["a", "b"]
        remember(original, "c")
        self.assertEqual(["a", "b"], original)


class TheStore(unittest.TestCase):
    def _store(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return FileRecentPaths(Path(folder.name) / "recent.json"), Path(folder.name)

    def test_it_round_trips(self):
        store, folder = self._store()
        first = folder / "one"
        first.mkdir()
        store.remember(str(first))
        self.assertEqual((str(first),), store.recent())

    def test_a_missing_file_is_an_empty_history(self):
        store, _ = self._store()
        self.assertEqual((), store.recent())

    def test_rubbish_is_an_empty_history_rather_than_a_crash(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "recent.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual((), FileRecentPaths(path).recent())

    def test_a_future_version_is_not_guessed_at(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "recent.json"
        path.write_text('{"version": 99, "paths": ["C:/x"]}', encoding="utf-8")
        self.assertEqual((), FileRecentPaths(path).recent())

    def test_a_directory_that_is_gone_is_not_offered(self):
        store, folder = self._store()
        here = folder / "here"
        here.mkdir()
        store.remember(str(folder / "gone"))
        store.remember(str(here))
        self.assertEqual((str(here),), store.recent())

    def test_but_it_is_not_forgotten_by_writing(self):
        store, folder = self._store()
        unmounted = folder / "unmounted"
        unmounted.mkdir()
        store.remember(str(unmounted))
        unmounted.rmdir()

        here = folder / "here"
        here.mkdir()
        store.remember(str(here))
        self.assertEqual((str(here),), store.recent(), "not offered while it is gone")

        unmounted.mkdir()
        self.assertIn(str(unmounted), store.recent(), "and back when it returns")


class ThePicker(unittest.IsolatedAsyncioTestCase):
    """Mounted for real: the list has to render, and a click has to move the tree."""

    class _App(App):
        def __init__(self, recent, start) -> None:
            super().__init__()
            self._recent = recent
            self._start = start
            self.chosen = None

        def on_mount(self) -> None:
            self.push_screen(
                PathScreen(self._start, "Which project?", recent=self._recent),
                callback=self._took,
            )

        def _took(self, answer) -> None:
            self.chosen = answer

    async def test_the_history_is_listed(self):
        with TemporaryDirectory() as folder:
            first = Path(folder) / "one"
            first.mkdir()
            app = self._App((first.as_posix(),), folder)
            async with app.run_test() as pilot:
                await pilot.pause()
                rows = list(app.screen.query(".recent--entry").results(Static))
                self.assertEqual(1, len(rows))
                self.assertEqual(first.as_posix(), str(rows[0].render()))
                self.assertFalse(app.screen.query_one("#recent").has_class("-empty"))

    async def test_no_history_hides_the_block_entirely(self):
        with TemporaryDirectory() as folder:
            app = self._App((), folder)
            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertTrue(app.screen.query_one("#recent").has_class("-empty"))
                self.assertEqual([], list(app.screen.query(".recent--entry")))

    async def test_clicking_a_row_moves_the_tree_without_answering(self):
        with TemporaryDirectory() as folder:
            elsewhere = Path(folder) / "elsewhere"
            elsewhere.mkdir()
            app = self._App((elsewhere.as_posix(),), folder)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click(".recent--entry")
                await pilot.pause()
                tree = app.screen.query_one(DirectoryTree)
                self.assertEqual(elsewhere.resolve(), Path(str(tree.path)).resolve())
                self.assertIsNone(app.chosen, "navigating is not answering")


if __name__ == "__main__":
    unittest.main()
