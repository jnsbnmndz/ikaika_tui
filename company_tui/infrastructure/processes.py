"""`ProcessRunner` over `subprocess`, with argument arrays and no shell."""

import asyncio
import os
import shutil
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from company_tui.domain import interactive
from company_tui.domain.interactive import ListView
from company_tui.domain.ports import ProcessResult, ProcessRunner


def _resolve_command(command: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve launch shims such as npm.cmd without involving a shell."""
    if not command:
        return command

    executable = shutil.which(command[0])
    if executable is None:
        return command
    return (executable, *command[1:])


class LocalProcessRunner(ProcessRunner):
    def locate(self, executable: str) -> str | None:
        return shutil.which(executable)

    def run(self, command: tuple[str, ...], cwd: Path | None = None) -> ProcessResult:
        completed = subprocess.run(
            _resolve_command(command),
            capture_output=True,
            check=False,
            cwd=cwd,
            shell=False,
            text=True,
        )
        return ProcessResult(
            exit_code=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )

    async def stream(
        self,
        command: tuple[str, ...],
        on_output: Callable[[str], None],
        cwd: Path | None = None,
        view: ListView | None = None,
    ) -> ProcessResult:
        extra = {}
        if view is not None:
            # The whole of the opt-in. Without a view there is no stdin pipe and no
            # variable, so a command cannot tell it is being run by this at all and
            # the run is byte for byte what it was.
            extra = {
                "stdin": asyncio.subprocess.PIPE,
                "env": {**os.environ, interactive.INTERACTIVE_VAR: interactive.ENABLED},
            }
        try:
            process = await asyncio.create_subprocess_exec(
                *_resolve_command(command),
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **extra,
            )
        except OSError as error:
            message = f"{command[0]}: {error.strerror or error}"
            on_output(message)
            return ProcessResult(exit_code=127, stdout="", stderr=message)

        collected: list[str] = []
        assert process.stdout is not None  # noqa: S101 - narrowing; PIPE was asked for
        try:
            async for raw in process.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if view is not None and await self._handled(line, process, view):
                    continue
                collected.append(line)
                on_output(line)
            exit_code = await process.wait()
        except asyncio.CancelledError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        finally:
            if view is not None:
                # A process parked on a read cannot be left there by a view that has
                # gone, and the view must not outlive the run that opened it.
                self._close_input(process)
                view.close()

        return ProcessResult(
            exit_code=exit_code, stdout="\n".join(collected), stderr=""
        )

    async def _handled(self, line: str, process, view: ListView) -> bool:
        """Whether the protocol took this line, so it is not output to print.

        A view that is not a browser is never handed the browser's verbs: they go
        back to being output, which is what a person reads where there is no
        browser to read them in, and is the whole of how a browser command runs as
        an ordinary script (`docs/decisions/0006`).
        """
        event = interactive.parse(line)
        if event is None:
            return False
        if isinstance(event, interactive.Finished):
            view.close()
            return True

        if isinstance(event, (interactive.ViewSpec, interactive.Status, interactive.Ask)):
            if not view.browsing:
                return False
            return await self._browser_said(event, process, view)

        if view.browsing and event.pane:
            answer = await view.browse(event)
            if answer is None:
                self._stop(process)
                return True
            await self._say(process, interactive.said(answer))
            return True

        picked = await view.show(event)
        if picked is None:
            # Nothing else is going to answer it, so leaving it waiting is the one
            # outcome worse than stopping it.
            self._stop(process)
            return True
        await self._say(process, interactive.pick(picked))
        return True

    async def _browser_said(self, event, process, view: ListView) -> bool:
        if isinstance(event, interactive.ViewSpec):
            view.describe(event)
            return True
        if isinstance(event, interactive.Status):
            view.say(event)
            return True
        answer = await view.ask(event)
        await self._say(process, interactive.answered(answer or ""))
        return True

    @staticmethod
    def _stop(process) -> None:
        with suppress(ProcessLookupError):
            process.kill()

    async def _say(self, process, line: str) -> None:
        """Write one line to the child, and WAIT for it to leave the buffer.

        `StreamWriter.write` only queues it. Without the drain the pick can sit in
        the transport while the child waits to read it and this waits on the child's
        stdout — a deadlock with no error and nothing on screen.
        """
        if process.stdin is None or process.stdin.is_closing():
            return
        try:
            process.stdin.write(f"{line}\n".encode())
            await process.stdin.drain()
        except (OSError, ValueError, ConnectionResetError):
            pass

    def _close_input(self, process) -> None:
        if process.stdin is None or process.stdin.is_closing():
            return
        with suppress(OSError, ValueError, AttributeError):
            process.stdin.close()
