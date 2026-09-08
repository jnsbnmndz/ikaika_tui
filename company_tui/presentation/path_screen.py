"""Browsing for a directory instead of remembering where it is.

Opened from a `PATH` field, and it answers with one string: the directory that
was highlighted when Select was pressed. The full path sits under the tree and
follows the highlight, because a tree shows you where you are relative to what
you opened and this is the only thing that says where you are absolutely.

The tree is re-rooted rather than scrolled to go upwards: a `DirectoryTree` can
only ever show what is beneath its root, so "Up" means opening the parent as a
new root.
"""

from collections.abc import Iterable
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, DirectoryTree, Static, Tree

from company_tui.presentation.chrome import KeyHint
from company_tui.presentation.screens import DialogScreen


class DirectoryOnlyTree(DirectoryTree):
    """What can be chosen, and none of what tooling leaves lying around.

    Directories always; files only when the field is asking for one, because
    browsing for a file in a tree that hides files means never finding it. A
    listing that includes `.git` and every other dot-entry buries the handful
    worth choosing either way.
    """

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
                # A directory that cannot be stat'ed — a disconnected network
                # drive, something the user may not read — is simply not offered.
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
    ) -> None:
        super().__init__()
        self._start = self._resolve(start)
        self._trail = trail
        self._files = files
        self._current = self._start

    @staticmethod
    def _resolve(start: str) -> Path:
        """The nearest real directory to what the field already says.

        A field holding a path that has not been created yet should still open
        somewhere useful, so the first parent that does exist is used.
        """
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

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = getattr(event.node, "data", None)
        if data is not None and getattr(data, "path", None) is not None:
            self._set_current(Path(data.path))

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        # Enter on a directory expands it, which is what a tree should do; it is
        # also the moment to treat that directory as the answer-in-waiting.
        self._set_current(Path(event.path))

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
