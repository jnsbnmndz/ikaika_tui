import asyncio
import shutil
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

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
    ) -> ProcessResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *_resolve_command(command),
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                # Interleaved, because the point is to show what the user would
                # have seen in their own terminal, in the order it happened.
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as error:
            message = f"{command[0]}: {error.strerror or error}"
            on_output(message)
            return ProcessResult(exit_code=127, stdout="", stderr=message)

        collected: list[str] = []
        assert process.stdout is not None
        try:
            async for raw in process.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                collected.append(line)
                on_output(line)
            exit_code = await process.wait()
        except asyncio.CancelledError:
            # Whoever stopped us wanted the command stopped, not just this
            # coroutine. Reaped before re-raising so nothing is left running.
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise

        return ProcessResult(
            exit_code=exit_code, stdout="\n".join(collected), stderr=""
        )
