"""Measuring the window the app is drawn in, and saying when it is too small.

The interface is laid out for a window of at least `MIN_WIDTH` x `MIN_HEIGHT`:
below that the run panel's two panes stop fitting side by side and the menu grid
drops to one card per row. This module reads the window and reports that. It
does not resize it, and there is a scar where resizing used to be.

**Never resize the window from here.** The app used to hold the window to a floor
and a ratio, correcting it ten times a second, and that pegged the CPU and the
GPU on a 150%-scaled display until the display driver reset — a black screen, an
unthemed title bar coming back, and an interface that could be pointed at but
not used. Three things compounded:

  * The window being corrected is usually **another process's**. Under Windows
    Terminal the window on screen belongs to Terminal, and `SetWindowPos` on a
    foreign window blocks the calling thread — Textual's event loop — until that
    process has handled the resize and re-rasterized its whole grid.
  * Each correction is a real resize, so the terminal remeasures its cell grid
    and hands the app a new size: a full relayout and repaint here, on top of
    the terminal's own re-render and a compositor pass.
  * It never converged. The terminal snaps a window to whole character cells,
    and DPI virtualization rounds every size on the way in and again on the way
    back out, so what is read back is never quite what was asked for, the ratio
    test fails again, and the next tick asks again. Remembering the last size
    that was refused cannot help when no two refusals are the same size.

So a window that is too small is a sentence in the chrome, not a fight with the
window manager. `TuiConsole` reads the window every `WINDOW_POLL_INTERVAL` and
shows what it found; the user resizes it, or does not.

Only the floor is reported. The layout is drawn for a 1.263:1 window and the
floor is itself that shape, but a ratio is not something anyone can hit by
dragging a window edge — on a scaled display nothing lands within a pixel of it —
and a notice that is always showing is a notice nobody reads.

`GetConsoleWindow` does not name the window the user can see, and does not fail
to, either — see `current_window`. That trap is most of why measuring is worth a
module: measuring the pseudo-console reports a 0x0 window, which is a notice that
never goes away.

Sizes here are whatever units `GetWindowRect` reports for the window, which for a
process that has not declared itself DPI-aware are the display's logical pixels
rather than its physical ones. The floor and the measurement are in the same
units, so the comparison holds either way.
"""

import ctypes
import os
import sys
from dataclasses import dataclass

MIN_WIDTH = 846
MIN_HEIGHT = 670


@dataclass(frozen=True)
class WindowState:
    """What the window looks like right now."""

    width: int
    height: int
    maximized: bool
    minimized: bool


def fits(width: int, height: int) -> bool:
    """Is there room to draw the interface as it was laid out?"""
    return width >= MIN_WIDTH and height >= MIN_HEIGHT


def cramped(state: WindowState) -> bool:
    """Is the interface being drawn smaller than it was laid out for?

    A minimized window is not being drawn at all, and measures a few pixels in
    a corner of nowhere — reporting that as too small would leave the notice
    standing behind a window nobody is looking at. A maximized one that is still
    short is worth saying: the screen is the limit, and the notice is then the
    explanation for a layout the user cannot do anything about.
    """
    if state.minimized:
        return False
    return not fits(state.width, state.height)


class AppWindow:
    """The operating-system window this app is drawn in.

    Read-only, deliberately. See the module docstring for what a `resize` here
    cost the last time there was one.
    """

    def __init__(self, handle: int) -> None:
        self.handle = handle

    def state(self) -> WindowState | None:
        """Read the window, or `None` if it is no longer there to read.

        `GetWindowRect` reads the window manager's own record of the window
        rather than asking the process that owns it, so this stays cheap even
        when the window belongs to a terminal that is busy drawing.
        """
        try:
            user32 = _user32()
            if not user32.IsWindow(self.handle):
                return None
            rect = _Rect()
            if not user32.GetWindowRect(self.handle, ctypes.byref(rect)):
                return None
            return WindowState(
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                maximized=bool(user32.IsZoomed(self.handle)),
                minimized=bool(user32.IsIconic(self.handle)),
            )
        except (AttributeError, OSError, ValueError):
            return None


def current_window() -> AppWindow | None:
    """The window to measure, or `None` if there is none to measure.

    Two terminals, two answers, and `GetConsoleWindow` only settles one of them.
    A classic console window really does belong to this process and can be named
    outright. A terminal that hosts the console through a pseudo-console —
    Windows Terminal, and an editor's built-in terminal — draws the window the
    user can see from another process entirely, and hands this process a
    `PseudoConsoleWindow` instead: a window that reports itself **visible** and
    measures 0x0. Asking whether the console window is visible does not tell the
    two apart, so the class name is what decides, and everything else falls
    through to the window in front — which is the one the app was launched from.

    Read once, while the app is still the window in front, so that alt-tabbing
    away later can never measure somebody else's window and report it as this
    one.
    """
    if os.name != "nt" or not sys.__stdout__:
        return None

    try:
        user32 = _user32()
        console = _console_window()
        if console and _is_own_console_window(console, user32):
            return AppWindow(console)
        foreground = user32.GetForegroundWindow()
    except (AttributeError, OSError, ValueError):
        return None

    return AppWindow(foreground) if foreground else None


CONSOLE_WINDOW_CLASS = "ConsoleWindowClass"
"""A classic console window — the only kind this process owns a real one of.

Named rather than inferred, because the pseudo-console stand-in passes every
other test one might think to apply: it is a window, and it is visible. It just
is not on the screen, and it is 0x0.
"""


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _is_own_console_window(handle: int, user32: ctypes.CDLL) -> bool:
    return bool(user32.IsWindowVisible(handle)) and _window_class(handle) == CONSOLE_WINDOW_CLASS


def _console_window() -> int | None:
    """This process's own console window, real or pseudo, or `0` if it has none."""
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    return kernel32.GetConsoleWindow()


def _window_class(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32().GetClassNameW(handle, buffer, len(buffer))
    return buffer.value


_LOADED: ctypes.CDLL | None = None


def _user32() -> ctypes.CDLL:
    """`user32`, with the signatures that a 64-bit handle needs spelled out.

    A handle is pointer-sized and `ctypes` assumes `int`, so left to itself it
    returns half of one — which is not this window, and on a bad day is another.

    Loaded once and kept. Every reading of the window makes several of these
    calls, and re-declaring the signatures each time is work done per poll for
    an answer that cannot change.
    """
    global _LOADED
    if _LOADED is not None:
        return _LOADED

    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    for name in ("IsWindow", "IsWindowVisible", "IsZoomed", "IsIconic"):
        getattr(user32, name).argtypes = (ctypes.c_void_p,)
    user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Rect))
    user32.GetClassNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    _LOADED = user32
    return user32
