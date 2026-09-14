"""Keeping a Windows terminal willing to talk to the app."""

import ctypes
import os
import sys
from collections.abc import Callable

Writer = Callable[[str], None]
"""How to reach the terminal."""

_TERMINAL_INTERACTION_SEQUENCE = (
    "\x1b[?1000h"
    "\x1b[?1003h"
    "\x1b[?1015h"
    "\x1b[?1006h"
    "\x1b[?1004h"
)

_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_ENABLE_EXTENDED_FLAGS = 0x0080


def restore_console_input_mode() -> bool:
    """Put the console input handle back into virtual-terminal mode."""
    if os.name != "nt":
        return False

    terminal_in = sys.__stdin__
    if terminal_in is None:
        return False

    try:
        import msvcrt

        handle = msvcrt.get_osfhandle(terminal_in.fileno())
        mode = _ENABLE_VIRTUAL_TERMINAL_INPUT | _ENABLE_EXTENDED_FLAGS
        return bool(ctypes.WinDLL("kernel32").SetConsoleMode(handle, mode))
    except (AttributeError, OSError, ValueError):
        return False


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
