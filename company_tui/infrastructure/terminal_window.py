"""Keeping a Windows terminal willing to talk to the app, and giving it back after.

`restore_terminal_interaction` re-arms the reporting a Windows terminal drops while
it is deactivated; `release_terminal` turns the same modes off and puts the console
back the way it was found. The second exists because nothing else is guaranteed to:
Textual queues its own shutdown sequences on a daemon writer thread whose `flush` is
a no-op, so a shutdown that does not reach `close()` throws them away unwritten
(`docs/pitfalls.md` 12.1). Both sequences are built from one list of modes, so what
is turned on and what is turned off cannot drift.

The release writes straight to `sys.__stdout__` and never through the driver, which
is the thing that may already be gone.
"""

import ctypes
import os
import sys
from collections.abc import Callable

Writer = Callable[[str], None]
"""How to reach the terminal."""

_REPORTING_MODES = ("1000", "1003", "1015", "1006", "1004")
"""VT200 mouse, any-event mouse, highlight mouse, SGR extended, focus in/out."""

_TERMINAL_INTERACTION_SEQUENCE = "".join(f"\x1b[?{mode}h" for mode in _REPORTING_MODES)

_RELEASE_SEQUENCE = (
    "".join(f"\x1b[?{mode}l" for mode in reversed(_REPORTING_MODES))
    + "\x1b[?2004l"
    + "\x1b[<u"
    + "\x1b[?1049l"
    + "\x1b[?25h"
)
"""Every mode above, off, plus the four Textual writes last and may not reach."""

_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_ENABLE_EXTENDED_FLAGS = 0x0080


def _handle(stream: object) -> int | None:
    """The Windows handle behind a stream, or `None` where there is not one."""
    if os.name != "nt" or stream is None:
        return None
    try:
        import msvcrt

        return msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return None


def _console_mode(stream: object) -> int | None:
    """What mode a console stream is in, for putting it back later."""
    handle = _handle(stream)
    if handle is None:
        return None
    held = ctypes.c_uint()
    try:
        if ctypes.WinDLL("kernel32").GetConsoleMode(handle, ctypes.byref(held)):
            return held.value
    except (AttributeError, OSError, ValueError):
        return None
    return None


def _set_console_mode(stream: object, mode: int) -> bool:
    handle = _handle(stream)
    if handle is None:
        return False
    try:
        return bool(ctypes.WinDLL("kernel32").SetConsoleMode(handle, mode))
    except (AttributeError, OSError, ValueError):
        return False


def console_modes() -> tuple[int | None, int | None]:
    """The console's own modes, read before anything has changed them."""
    return (_console_mode(sys.__stdin__), _console_mode(sys.__stdout__))


def restore_console_input_mode() -> bool:
    """Put the console input handle back into virtual-terminal mode."""
    if os.name != "nt":
        return False
    mode = _ENABLE_VIRTUAL_TERMINAL_INPUT | _ENABLE_EXTENDED_FLAGS
    return _set_console_mode(sys.__stdin__, mode)


def restore_terminal_interaction(write: Writer) -> bool:
    """Re-arm the input handling a Windows terminal may drop while deactivated."""
    if os.name != "nt":
        return False

    restored = restore_console_input_mode()
    try:
        write(_TERMINAL_INTERACTION_SEQUENCE)
    except (AttributeError, OSError):
        return False
    return restored


def release_terminal(modes: tuple[int | None, int | None] = (None, None)) -> bool:
    """Stop the terminal reporting at us, and give the console its modes back.

    Safe to call after a clean exit as well: every sequence written here is an
    off, and turning off what is already off is what the terminal does with it.
    """
    out = sys.__stdout__
    written = False
    try:
        if out is not None and out.isatty():
            out.write(_RELEASE_SEQUENCE)
            out.flush()
            written = True
    except (AttributeError, OSError, ValueError):
        written = False

    held_in, held_out = modes
    if held_in is not None:
        _set_console_mode(sys.__stdin__, held_in)
    if held_out is not None:
        _set_console_mode(sys.__stdout__, held_out)
    return written
