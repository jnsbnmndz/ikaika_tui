"""The subprocess and filesystem ports the domain is written against."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str


class ProcessRunner(ABC):
    @abstractmethod
    def run(self, command: tuple[str, ...], cwd: Path | None = None) -> ProcessResult:
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self,
        command: tuple[str, ...],
        on_output: Callable[[str], None],
        cwd: Path | None = None,
    ) -> ProcessResult:
        """Run `command`, handing each output line over as it arrives."""
        raise NotImplementedError

    async def capture(
        self, command: tuple[str, ...], cwd: Path | None = None
    ) -> ProcessResult:
        """`run`, off the interface's thread."""
        return await asyncio.to_thread(self.run, command, cwd)

    @abstractmethod
    def locate(self, executable: str) -> str | None:
        """Where `executable` is, or `None` if it is not on this machine."""
        raise NotImplementedError


class FileSystemPort(ABC):
    @abstractmethod
    def exists(self, path: Path) -> bool:
        raise NotImplementedError

    @abstractmethod
    def entries(self, path: Path) -> tuple[str, ...]:
        """The names directly inside `path`, sorted; empty if it is not a directory."""
        raise NotImplementedError

    @abstractmethod
    def read_text(self, path: Path) -> str:
        raise NotImplementedError

    @abstractmethod
    def write_text(self, path: Path, content: str) -> None:
        """Write `content` to `path`, creating the directories above it."""
        raise NotImplementedError

    @abstractmethod
    def write_project(self, root: Path, files: Mapping[str, str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def remove_file(self, path: Path) -> None:
        """Delete one file, and say nothing if it was not there."""
        raise NotImplementedError

    @abstractmethod
    async def remove_tree(self, path: Path) -> None:
        """Delete a directory and everything beneath it."""
        raise NotImplementedError
