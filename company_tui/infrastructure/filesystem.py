"""`FileSystemPort` over the local disk."""

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

    def remove_file(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    async def remove_tree(self, path: Path) -> None:
        await asyncio.to_thread(self._remove_tree, path)

    def _remove_tree(self, path: Path) -> None:
        preserve_root = path.resolve() == Path.cwd().resolve()
        for attempt in range(1, REMOVE_ATTEMPTS + 1):
            self._clear_read_only(path)
            try:
                if preserve_root:
                    for child in path.iterdir():
                        if child.is_dir() and not child.is_symlink():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                else:
                    shutil.rmtree(path)
                return
            except OSError:
                if attempt == REMOVE_ATTEMPTS:
                    raise
                time.sleep(REMOVE_BACKOFF * attempt)

    @staticmethod
    def _clear_read_only(path: Path) -> None:
        for child in path.rglob("*"):
            try:
                child.chmod(child.stat().st_mode | stat.S_IWRITE)
            except OSError:
                pass
