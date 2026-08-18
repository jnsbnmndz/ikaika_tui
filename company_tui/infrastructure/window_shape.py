"""Measuring the window the app is drawn in, opening it at a size, holding a floor.

The interface is laid out for a window of at least `MIN_WIDTH` x `MIN_HEIGHT` and
opens at the size `DEFAULT_PLAN` names. This module reads the window, says when
there is less room than the layout wants, and — twice, at the two moments where it
pays for itself — asks the window manager for a size.

**Nothing here may resize per tick.** The app used to hold the window to a floor
*and* a `1.263:1` ratio, correcting it ten times a second, and that pegged the CPU
and the GPU on a 150%-scaled display until the display driver reset — a black
screen, an unthemed title bar coming back, and an interface that could be pointed
at but not used. Three things compounded, and every one of them is still true of
any resize made from here:

  * The window being resized is usually **another process's**. Under Windows
    Terminal the window on screen belongs to Terminal, and `SetWindowPos` on a
    foreign window blocks the calling thread — Textual's event loop — until that
    process has handled the resize and re-rasterized its whole grid.
  * Each correction is a real resize, so the terminal remeasures its cell grid
    and hands the app a new size: a full relayout and repaint here, on top of
    the terminal's own re-render and a compositor pass.
  * It never converged. The terminal snaps a window to whole character cells,
    and DPI virtualization rounds every size on the way in and again on the way
    back out, so what is read back is never quite what was asked for, the test
    fails again, and the next tick asks again. Remembering the last size that was
    refused cannot help when no two refusals are the same size.

`SizeGuard` is written against all three. It asks **once** when the app opens, and
after that only when a window that does not fit has *stopped being dragged* — which
is where every one of those ten-a-second corrections came from, since the window is
under the floor for the whole of a drag inwards and the user is still holding the
edge being fought over. `dragging()` is what says to wait. Non-convergence is
bounded rather than reasoned about: `RESIZE_ATTEMPTS` asks are all one shortfall
ever gets, and the budget refills only once the window has fit, so a size this
window cannot have costs two calls and then goes back to being a sentence in the
chrome. `SNAP_SLACK` is why it is usually reached on the first ask.

The ratio is a layout target and nothing checks it: nobody hits a ratio by
dragging a window edge, and a notice that is always showing is a notice nobody
reads. A *maximized* window that is still short is not resized either — the screen
is the limit there, and the notice is the explanation.

`GetConsoleWindow` does not name the window the user can see, and does not fail
to, either — see `current_window`. That trap is most of why this is worth a module:
measuring the pseudo-console reports a 0x0 window, which is a notice that never
goes away and, now, a resize aimed at nothing.

Sizes here are whatever units `GetWindowRect` reports for the window, which for a
process that has not declared itself DPI-aware are the display's logical pixels
rather than its physical ones. The floor, the target and the measurement are in the
same units, so the comparisons hold either way.
"""

import ctypes
import os
import sys
from dataclasses import dataclass

START_SIDE = 980
"""How big the window opens, on both edges unless `DEFAULT_PLAN` says otherwise.

Neither the floor nor the ratio: it is a size the layout has room to breathe at,
and a square is the shape that reads as chosen rather than as whatever the last
program to use this terminal left the window at.
"""

MIN_WIDTH = 900
MIN_HEIGHT = 700

SCREEN_MARGIN = 30
"""Room left between the square and the edge of a screen too short for it.

A window the exact height of the space it has hangs its own bottom frame off the
display, and there is then nothing there to drag.
"""


@dataclass(frozen=True)
class WindowPlan:
    """The size to open at and the size to hold to, for one screen.

    Both come off the screen, because a floor taller than the display is a floor
    nothing can stand on: the window would open short, be corrected, come back
    short, and spend its whole `RESIZE_ATTEMPTS` on a size the screen does not
    have. A screen with room for it gets `DEFAULT_PLAN` exactly; a shorter one
    gets that size shrunk to fit, which is then its own floor.
    """
    start_width: int
    start_height: int
    min_width: int
    min_height: int


DEFAULT_PLAN = WindowPlan(START_SIDE+100, START_SIDE, MIN_WIDTH, MIN_HEIGHT)
"""The size wanted, on a screen with room for the whole of it.

Edit this — or the four constants above it — to change what the window opens at
and what it is held to. `plan_for` reads it rather than the constants, so a plan
that is not a square is one on every screen and not only on an unmeasurable one,
and it is also the plan used when the screen cannot be measured at all.
"""

RESIZE_ATTEMPTS = 2
"""How many asks one shortfall gets before the answer is a sentence instead.

The cap is the whole defence against the loop that reset a display driver. Two
rather than one because a first ask can land a pixel under a floor after cell
snapping and DPI rounding twice; two rather than more because a size two asks did
not reach is a size this window is not going to have.
"""

SNAP_SLACK = 24
"""Asked for over the floor, on whichever edge is under it.

A terminal snaps a window down to whole character cells, so a request for exactly
the floor comes back beneath it — the window still does not fit and the notice
stands over a window that looks right. A cell's worth of slack lands at or above
the floor on the first ask. Slack rather than a retry loop, because it is bounded
and it is spent once.
"""


@dataclass(frozen=True)
class WindowState:
    """What the window looks like right now."""

    width: int
    height: int
    maximized: bool
    minimized: bool


def plan_for(screen_width: int, screen_height: int) -> WindowPlan:
    """What to open at, and what to hold to, on a screen this size.

    `DEFAULT_PLAN` is the size wanted; this is that size against one screen. Read
    off the plan rather than off the constants beside it, so the two cannot
    disagree: the version that read `START_SIDE` here opened a square on every
    screen it could measure however `DEFAULT_PLAN` had been edited, because the
    plan was only ever reached when the screen could *not* be measured.

    A screen with no room for the height gets the shape shrunk rather than
    squashed — the height becomes the screen less `SCREEN_MARGIN` and the width
    comes down with it, which for the square this opens at by default is the
    same thing as making both edges the height. The floor follows the window
    down, because a floor bigger than the window it is the floor for would
    immediately fight the size the window was shrunk to fit.
    """
    wanted = DEFAULT_PLAN
    tall_enough = screen_height >= wanted.start_height
    height = (
        wanted.start_height if tall_enough else max(screen_height - SCREEN_MARGIN, 1)
    )
    width = (
        wanted.start_width
        if tall_enough
        else max(round(wanted.start_width * height / wanted.start_height), 1)
    )
    if screen_width > 0:
        width = min(width, screen_width)
    return WindowPlan(
        start_width=width,
        start_height=height,
        min_width=min(wanted.min_width, width),
        min_height=min(wanted.min_height if tall_enough else height, height),
    )


def fits(width: int, height: int, plan: WindowPlan = DEFAULT_PLAN) -> bool:
    """Is there room to draw the interface as it was laid out?"""
    return width >= plan.min_width and height >= plan.min_height


def cramped(state: WindowState, plan: WindowPlan = DEFAULT_PLAN) -> bool:
    """Is the interface being drawn smaller than it was laid out for?

    A minimized window is not being drawn at all, and measures a few pixels in
    a corner of nowhere — reporting that as too small would leave the notice
    standing behind a window nobody is looking at. A maximized one that is still
    short is worth saying: the screen is the limit, and the notice is then the
    explanation for a layout the user cannot do anything about.
    """
    if state.minimized:
        return False
    return not fits(state.width, state.height, plan)


class AppWindow:
    """The operating-system window this app is drawn in."""

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

    def resize(self, width: int, height: int) -> bool:
        """Ask the window manager for a size, and expect to be answered slowly.

        Where the window is stays where it was: the size is the app's business
        and the position is the user's. `SWP_NOACTIVATE` because a window raised
        by its own resize takes the focus off whatever the user went to while it
        was happening.

        The call blocks until the process owning the window has handled the
        resize, and under any terminal that hosts a pseudo-console that process
        is not this one. `SizeGuard` is the only thing that should reach it.
        """
        try:
            user32 = _user32()
            if not user32.IsWindow(self.handle):
                return False
            return bool(
                user32.SetWindowPos(self.handle, None, 0, 0, width, height, _SWP_RESIZE_ONLY)
            )
        except (AttributeError, OSError, ValueError):
            return False


class SizeGuard:
    """Opens the window at a size, and puts it back once it has been dragged under.

    Everything expensive about resizing is a resize made *during* a drag, and this
    makes none: `hold` waits for the button to come up and then asks at most
    `RESIZE_ATTEMPTS` times before letting the window be whatever it is. See the
    module docstring for what the version without those two rules cost.
    """

    def __init__(self, window: AppWindow, plan: WindowPlan = DEFAULT_PLAN) -> None:
        self.window = window
        self.plan = plan
        self._spent = 0

    def open_at_start_size(self) -> bool:
        """Ask once, as the app starts, for the size it wants to open at.

        A window the user has already maximized is left maximized — they asked
        for the whole screen more recently than this did — and a minimized one is
        not a size anybody chose. A window already the right size is not asked
        about at all, which is the common case on the second run of the day.
        """
        state = self.window.state()
        if state is None or state.maximized or state.minimized:
            return False
        if (state.width, state.height) == (self.plan.start_width, self.plan.start_height):
            return False
        return self.window.resize(self.plan.start_width, self.plan.start_height)

    def hold(self, state: WindowState) -> bool:
        """Put a window that has been dragged under the floor back onto it.

        `True` if it asked, which also means the measurement just handed in is now
        out of date. Called from a poll, so every branch returning `False` here is
        a tick that costs two reads and draws nothing.
        """
        if state.minimized or state.maximized:
            return False
        if fits(state.width, state.height, self.plan):
            self._spent = 0
            return False
        if dragging():
            return False
        if self._spent >= RESIZE_ATTEMPTS:
            return False
        self._spent += 1
        return self.window.resize(
            _at_least(state.width, self.plan.min_width),
            _at_least(state.height, self.plan.min_height),
        )


def _at_least(measured: int, floor: int) -> int:
    """`measured`, or the floor with a cell's slack on it where it is under.

    The slack goes on the short edge only. An edge that already clears its floor
    is left at the width the user dragged it to, rather than nudged out because
    the other edge was the problem.
    """
    return measured if measured >= floor else floor + SNAP_SLACK


def dragging() -> bool:
    """Is the left mouse button down — is a resize still in the user's hands?

    Asked rather than waited for: nothing reaches this process while another
    process's window is being dragged by an edge. `GetAsyncKeyState` reads state
    the input system already holds, which is what makes it affordable once a tick.

    Nothing to ask away from Windows, and "yes" is the safe answer to be wrong
    with — it only ever means waiting another tick.
    """
    if os.name != "nt":
        return False
    try:
        return bool(_user32().GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
    except (AttributeError, OSError, ValueError):
        return False


def screen_size() -> tuple[int, int] | None:
    """The room a window has on this display, or `None` if it cannot be read.

    The *work area* rather than the whole screen, because that is the height a
    window can actually have: the rest is under the taskbar, and a square sized to
    the screen would open with its bottom edge — and the footer's key hints —
    behind it.
    """
    if os.name != "nt":
        return None
    try:
        rect = _Rect()
        if not _user32().SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return None
    except (AttributeError, OSError, ValueError):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    return (width, height) if width > 0 and height > 0 else None


def window_plan() -> WindowPlan:
    """The plan for the screen this app is on, or the plain square if unreadable.

    A screen that cannot be read falls back rather than failing: `DEFAULT_PLAN` is
    what every screen with room for the square gets anyway.
    """
    measured = screen_size()
    return DEFAULT_PLAN if measured is None else plan_for(*measured)


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
    one — or, now, resize it.
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

_VK_LBUTTON = 0x01
_SPI_GETWORKAREA = 0x0030
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_RESIZE_ONLY = _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE


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
    user32.SetWindowPos.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    )
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SystemParametersInfoW.argtypes = (
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_uint,
    )
    _LOADED = user32
    return user32
