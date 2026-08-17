import asyncio
import shutil
import stat
import time
from collections.abc import Mapping
from pathlib import Path

from company_tui.domain.ports import FileSystemPort

REMOVE_ATTEMPTS = 6
REMOVE_BACKOFF = 0.15
"""Seconds before retrying a delete, multiplied by the attempt number."""


class LocalFileSystem(FileSystemPort):
    def exists(self, path: Path) -> bool:
        return path.exists()

    def entries(self, path: Path) -> tuple[str, ...]:
        if not path.is_dir():
            return ()
        return tuple(sorted(child.name for child in path.iterdir()))

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_project(self, root: Path, files: Mapping[str, str]) -> None:
        root.mkdir(parents=True, exist_ok=False)
        for relative_path, content in files.items():
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    async def remove_tree(self, path: Path) -> None:
        # Off the event loop: deleting a dependency directory means tens of
        # thousands of files, and doing that inline freezes the interface for
        # the whole of it — including the button that would stop it.
        await asyncio.to_thread(self._remove_tree, path)

    def _remove_tree(self, path: Path) -> None:
        preserve_root = path.resolve() == Path.cwd().resolve()
        for attempt in range(1, REMOVE_ATTEMPTS + 1):
            self._clear_read_only(path)
            try:
                if preserve_root:
                    # A process cannot remove its own working directory on
                    # Windows.  Empty it instead so commands such as
                    # ``git clone ... .`` can reuse the directory.
                    for child in path.iterdir():
                        if child.is_dir() and not child.is_symlink():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                else:
                    shutil.rmtree(path)
                return
            except OSError:
                # Windows refuses a delete while anything still holds the file
                # open, and on a tree this size something usually does for a
                # moment — a virus scanner or the search indexer reading what
                # was just written. The hold is brief, and each attempt deletes
                # what it can, so the next one has less left to fight over.
                if attempt == REMOVE_ATTEMPTS:
                    raise
                time.sleep(REMOVE_BACKOFF * attempt)

    @staticmethod
    def _clear_read_only(path: Path) -> None:
        # Git marks the pack files under .git read-only, and Windows refuses to
        # unlink a read-only file, so clear the bit before deleting. Done as a
        # pass rather than an rmtree error handler because the handler argument
        # was renamed across the Python versions this project supports.
        for child in path.rglob("*"):
            try:
                child.chmod(child.stat().st_mode | stat.S_IWRITE)
            except OSError:
                # Leave it; rmtree reports anything that genuinely blocks removal.
                pass
