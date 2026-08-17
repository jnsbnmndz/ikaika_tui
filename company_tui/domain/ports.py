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
    def run(self, command: tuple[str, ...]) -> ProcessResult:
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self, command: tuple[str, ...], on_output: Callable[[str], None]
    ) -> ProcessResult:
        """Run `command`, handing each output line over as it arrives.

        For anything slow enough that the user should see it working. `run`
        stays for short commands whose output only matters once it is complete.

        Cancelling the caller must kill the command rather than orphan it: a
        stopped run means the work stops, not just the waiting.
        """
        raise NotImplementedError

    async def capture(self, command: tuple[str, ...]) -> ProcessResult:
        """`run`, off the interface's thread.

        `run` blocks until the command is done, which from inside a workflow
        means the interface stops redrawing and stops answering the key that
        would stop it. Anything called while a screen is up goes through here;
        `run` stays for the plain console, where there is no frame to hold up.
        """
        return await asyncio.to_thread(self.run, command)

    @abstractmethod
    def locate(self, executable: str) -> str | None:
        """Where `executable` is, or `None` if it is not on this machine.

        Asked before a workflow starts rather than discovered halfway through
        it: a missing `git` should be one sentence up front, not a half-cloned
        directory and a subprocess error.
        """
        raise NotImplementedError


class FileSystemPort(ABC):
    @abstractmethod
    def exists(self, path: Path) -> bool:
        raise NotImplementedError

    @abstractmethod
    def entries(self, path: Path) -> tuple[str, ...]:
        """The names directly inside `path`, sorted; empty if it is not a directory.

        Enough to show someone what a destructive step is about to take, which
        is the difference between confirming a delete and guessing at one.
        """
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
    async def remove_tree(self, path: Path) -> None:
        """Delete a directory and everything beneath it.

        Destructive and not undoable: callers are responsible for confirming
        with the user first, and for passing a path they created themselves.

        Async because a project directory can hold tens of thousands of files,
        and deleting them inline would freeze the interface for the duration —
        including whatever the user would press to stop it.
        """
        raise NotImplementedError
