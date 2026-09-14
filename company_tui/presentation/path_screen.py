"""Browsing for a directory instead of remembering where it is."""

from collections.abc import Iterable, Sequence
from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, DirectoryTree, Static, Tree

from company_tui.presentation.chrome import KeyHint
from company_tui.presentation.screens import DialogScreen


class DirectoryOnlyTree(DirectoryTree):
    """What can be chosen, and none of what tooling leaves lying around."""

    def __init__(self, *args, show_files: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.show_files = show_files

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        keep = []
        for path in paths:
            try:
                if path.name.startswith("."):
                    continue
                if path.is_dir() or self.show_files:
                    keep.append(path)
            except OSError:
                continue
        return keep


class PathScreen(DialogScreen[str | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("backspace", "go_up", "Up"),
    ]

    DEFAULT_CSS = """
    PathScreen > Container {
        width: 78;
        height: 26;
    }

    PathScreen DirectoryTree {
        height: 1fr;
        border: round $primary-lighten-1;
        background: $panel;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }

    PathScreen DirectoryTree:focus {
        border: round $accent;
    }

    /* The history, above the tree rather than beside it: the dialog is 78 columns
       and a path is long, so a column split would truncate both halves. One row per
       entry, and the whole block is gone when there is nothing in it - an empty
       "Recent" heading is a promise the app is not keeping. */
    PathScreen #recent {
        height: auto;
        max-height: 7;
        margin-bottom: 1;
        border: round $primary-lighten-1;
        background: $panel;
        scrollbar-size-vertical: 1;
    }

    PathScreen #recent:focus-within {
        border: round $accent;
    }

    PathScreen #recent.-empty {
        display: none;
    }

    PathScreen .recent--entry {
        width: 100%;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    PathScreen .recent--entry:hover {
        color: $primary-lighten-2;
    }

    PathScreen .recent--entry.-chosen {
        color: $accent;
        text-style: bold;
    }

    PathScreen #chosen-path {
        width: 100%;
        height: auto;
        margin: 1 0;
        color: $accent;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def __init__(
        self,
        start: str = "",
        trail: str = "Choose a directory",
        files: bool = False,
        recent: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self._start = self._resolve(start)
        self._trail = trail
        self._files = files
        self._current = self._start
        self._recent = tuple(recent)
        """Directories picked before, newest first. Empty is the normal state on a."""

    @staticmethod
    def _resolve(start: str) -> Path:
        """The nearest real directory to what the field already says."""
        try:
            candidate = Path(start.strip() or ".").expanduser().resolve()
        except (OSError, RuntimeError):
            return Path.cwd()
        for path in (candidate, *candidate.parents):
            if path.is_dir():
                return path
        return Path.cwd()

    def compose(self) -> ComposeResult:
        with Container() as dialog:
            dialog.border_title = self._trail
            with VerticalScroll(
                id="recent", classes="" if self._recent else "-empty"
            ):
                for path in self._recent:
                    yield Static(path, classes="recent--entry", markup=False)
            yield DirectoryOnlyTree(str(self._start), id="tree", show_files=self._files)
            yield Static(self._display(self._start), id="chosen-path")
            with Horizontal(classes="dialog--actions"):
                with Horizontal(classes="dialog--escape"):
                    yield KeyHint("Esc", "Go back", dim=True)
                yield Button("Up", id="up", flat=True)
                yield Button("Select", id="select", variant="primary", flat=True)

    def on_mount(self) -> None:
        self.query_one(DirectoryTree).focus()

    @staticmethod
    def _display(path: Path) -> str:
        return path.as_posix()

    def _set_current(self, path: Path) -> None:
        self._current = path
        self.query_one("#chosen-path", Static).update(self._display(path))
        shown = self._display(path)
        for entry in self.query(".recent--entry").results(Static):
            entry.set_class(str(entry.render()) == shown, "-chosen")

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = getattr(event.node, "data", None)
        if data is not None and getattr(data, "path", None) is not None:
            self._set_current(Path(data.path))

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self._set_current(Path(event.path))

    def on_click(self, event: events.Click) -> None:
        """A click on a history row moves the tree to it."""
        target = getattr(event, "widget", None)
        if target is None or not target.has_class("recent--entry"):
            return
        path = self._resolve(str(target.render()))
        tree = self.query_one(DirectoryTree)
        tree.path = str(path)
        self._set_current(path)
        tree.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select":
            self.dismiss(self._display(self._current))
        elif event.button.id == "up":
            self.action_go_up()

    def action_go_up(self) -> None:
        tree = self.query_one(DirectoryTree)
        root = Path(tree.path)
        if root.parent == root:
            return
        tree.path = str(root.parent)
        self._set_current(root.parent)
        tree.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
