"""Keeping a Windows terminal willing to talk to the app.

Nothing here changes the *shape* of the terminal, on purpose. Asking one to
resize itself leaves its cell grid and the app's disagreeing until something
forces them back into step, and until then every mouse report names a cell the
app never drew there — the pointer lands somewhere other than where it points.

The window's pixel rectangle is a separate thing, and `window_shape` does hold
that to a minimum and a ratio. The difference is who measures: a terminal handed
a new window remeasures its own grid from it and reports the result, so the two
stay in step, while a grid demanded by escape sequence is a number the app made
up about a window that never changed.
"""

import ctypes
import os
import sys
from collections.abc import Callable

Writer = Callable[[str], None]
"""How to reach the terminal.

Injected rather than assumed, because the caller's terminal library owns the
output stream and usually buffers it on another thread. Writing to `sys.stdout`
alongside it interleaves bytes into the middle of whatever it is emitting.
"""

# Deliberately the same modes, in the same order, that Textual's own driver
# arms on startup, plus focus reporting. Re-arming with a different set is worse
# than not re-arming: the extended-coordinate modes decide how the terminal
# encodes a mouse report, and a terminal left in a different encoding than the
# parser expects reports positions that are wrong rather than missing.
_TERMINAL_INTERACTION_SEQUENCE = (
    "\x1b[?1000h"  # button press/release reporting
    "\x1b[?1003h"  # mouse movement reporting (hover)
    "\x1b[?1015h"  # urxvt-compatible mouse coordinates
    "\x1b[?1006h"  # SGR extended mouse coordinates
    "\x1b[?1004h"  # terminal focus in/out reporting
)

# Console input mode bits. Escape sequences configure how the terminal *reports*
# a mouse event; this decides whether the console hands the event to the program
# at all, and it is a separate setting that separate things can change.
_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_ENABLE_EXTENDED_FLAGS = 0x0080


def restore_console_input_mode() -> bool:
    """Put the console input handle back into virtual-terminal mode.

    The terminal library sets this once, while starting up, and never again.
    Anything that resets it afterwards — reactivating the window is the usual
    way — leaves the console delivering mouse input the old way instead of as
    escape sequences, which the parser never sees. Re-sending escape sequences
    cannot repair that: they are output, and this is input.

    `ENABLE_EXTENDED_FLAGS` is included deliberately. Without it the quick-edit
    bit is left at whatever it was, and quick-edit means the console keeps
    press-and-drag for its own text selection rather than passing it on — the
    highlight that follows the mouse while the program underneath sees nothing.
    """
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
    """Re-arm the input handling a Windows terminal may drop while deactivated.

    Both halves matter: the console has to be willing to deliver mouse input,
    and the terminal has to be told to report it in the encoding the parser
    expects.
    """
    if os.name != "nt":
        return False

    restored = restore_console_input_mode()
    try:
        write(_TERMINAL_INTERACTION_SEQUENCE)
    except (AttributeError, OSError):
        return False
    return restored
