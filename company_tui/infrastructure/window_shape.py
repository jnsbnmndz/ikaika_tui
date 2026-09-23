"""Measuring the window the app is drawn in, opening it at a size, holding a floor."""

import ctypes
import os
import sys
from dataclasses import dataclass

from company_tui.domain.layout import Window

START_SIDE = 980
"""How big the window opens, on both edges unless `DEFAULT_PLAN` says otherwise."""

MIN_WIDTH = 900
MIN_HEIGHT = 700

SCREEN_MARGIN = 30
"""Room left between the square and the edge of a screen too short for it."""

@dataclass(frozen=True)
class WindowPlan:
    """The size to open at and the size to hold to, for one screen."""
    start_width: int
    start_height: int
    min_width: int
    min_height: int


DEFAULT_PLAN = WindowPlan(START_SIDE+100, START_SIDE, MIN_WIDTH, MIN_HEIGHT)
"""The size wanted, on a screen with room for the whole of it."""

RESIZE_ATTEMPTS = 2
"""How many asks one shortfall gets before the answer is a sentence instead."""

SNAP_SLACK = 24
"""Asked for over the floor, on whichever edge is under it."""

@dataclass(frozen=True)
class WindowState:
    """What the window looks like right now."""

    width: int
    height: int
    maximized: bool
    minimized: bool


def plan_for(
    screen_width: int, screen_height: int, wanted: WindowPlan = DEFAULT_PLAN
) -> WindowPlan:
    """What to open at, and what to hold to, on a screen this size."""
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
    """Is the interface being drawn smaller than it was laid out for?"""
    if state.minimized:
        return False
    return not fits(state.width, state.height, plan)


class AppWindow:
    """The operating-system window this app is drawn in."""

    def __init__(self, handle: int) -> None:
        self.handle = handle

    def state(self) -> WindowState | None:
        """Read the window, or `None` if it is no longer there to read."""
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
        """Ask the window manager for a size, and expect to be answered slowly."""
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
    """Opens the window at a size, and puts it back once it has been dragged under."""

    def __init__(self, window: AppWindow, plan: WindowPlan = DEFAULT_PLAN) -> None:
        self.window = window
        self.plan = plan
        self._spent = 0

    def open_at_start_size(self) -> bool:
        """Ask once, as the app starts, for the size it wants to open at."""
        state = self.window.state()
        if state is None or state.maximized or state.minimized:
            return False
        if (state.width, state.height) == (self.plan.start_width, self.plan.start_height):
            return False
        return self.window.resize(self.plan.start_width, self.plan.start_height)

    def hold(self, state: WindowState) -> bool:
        """Put a window that has been dragged under the floor back onto it."""
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
    """`measured`, or the floor with a cell's slack on it where it is under."""
    return measured if measured >= floor else floor + SNAP_SLACK


def dragging() -> bool:
    """Is the left mouse button down — is a resize still in the user's hands?"""
    if os.name != "nt":
        return False
    try:
        return bool(_user32().GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
    except (AttributeError, OSError, ValueError):
        return False


def screen_size() -> tuple[int, int] | None:
    """The room a window has on this display, or `None` if it cannot be read."""
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


def window_plan(wanted: WindowPlan = DEFAULT_PLAN) -> WindowPlan:
    """The plan for the screen this app is on, or `wanted` itself if unreadable."""
    measured = screen_size()
    return wanted if measured is None else plan_for(*measured, wanted)


def plan_from(window: Window) -> WindowPlan:
    """The arranged window as a plan. The domain holds sizes, not screen policy."""
    return WindowPlan(
        window.start_width, window.start_height, window.min_width, window.min_height
    )


def current_window() -> AppWindow | None:
    """The window to measure, or `None` if there is none to measure."""
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
"""A classic console window — the only kind this process owns a real one of."""

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
    """`user32`, with the signatures that a 64-bit handle needs spelled out."""
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
