"""A poll that costs two reads and draws nothing.

CLAUDE.md says this file counts calls on a fake window: a hundred ticks over one
being dragged, one maximized, one minimized, or one with room in it all have to
answer zero resizes, and a floor that cannot be reached has to stop after
`RESIZE_ATTEMPTS` rather than asking once per tick forever. It did not exist -
`tests/` was gitignored - so this is that test.

Both invariants are about cost, which is why they need counting rather than
reading. `SizeGuard.hold` runs on a timer; a branch that resizes when it should
not is not a wrong window size, it is a window being shoved about several times a
second while somebody is trying to drag it.

No `user32` here. `SizeGuard` takes an `AppWindow`, so a fake with the same two
methods is the whole harness, and `dragging()` is patched at module scope because
it reads the real mouse button.
"""

import unittest
from unittest import mock

from company_tui.infrastructure import window_shape
from company_tui.infrastructure.window_shape import (
    DEFAULT_PLAN,
    RESIZE_ATTEMPTS,
    SizeGuard,
    WindowState,
    fits,
)

TICKS = 100


class FakeWindow:
    """Counts what was asked of it, and grants every resize."""

    def __init__(self, state: WindowState | None = None) -> None:
        self.state_value = state
        self.resizes: list[tuple[int, int]] = []

    def state(self) -> WindowState | None:
        return self.state_value

    def resize(self, width: int, height: int) -> bool:
        self.resizes.append((width, height))
        return True


def roomy() -> WindowState:
    return WindowState(
        width=DEFAULT_PLAN.min_width + 200,
        height=DEFAULT_PLAN.min_height + 200,
        maximized=False,
        minimized=False,
    )


def cramped_state(**overrides) -> WindowState:
    base = {
        "width": max(DEFAULT_PLAN.min_width - 200, 1),
        "height": max(DEFAULT_PLAN.min_height - 200, 1),
        "maximized": False,
        "minimized": False,
    }
    base.update(overrides)
    return WindowState(**base)


class QuietTicksTest(unittest.TestCase):
    """Every one of these is a tick that must draw nothing."""

    def setUp(self):
        patcher = mock.patch.object(window_shape, "dragging", return_value=False)
        self.dragging = patcher.start()
        self.addCleanup(patcher.stop)

    def _hold(self, state: WindowState, ticks: int = TICKS) -> FakeWindow:
        window = FakeWindow(state)
        guard = SizeGuard(window)
        for _ in range(ticks):
            guard.hold(state)
        return window

    def test_a_window_with_room_in_it_is_never_resized(self):
        self.assertEqual([], self._hold(roomy()).resizes)

    def test_a_maximized_window_is_left_alone(self):
        # The user asked for the whole screen more recently than this did.
        self.assertEqual([], self._hold(cramped_state(maximized=True)).resizes)

    def test_a_minimized_window_is_left_alone(self):
        # Not a size anybody chose.
        self.assertEqual([], self._hold(cramped_state(minimized=True)).resizes)

    def test_a_window_being_dragged_is_never_resized(self):
        # The expensive case, and the one that reads as the app fighting the mouse.
        self.dragging.return_value = True
        self.assertEqual([], self._hold(cramped_state()).resizes)


class BoundedAttemptsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(window_shape, "dragging", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_floor_that_cannot_be_reached_is_asked_for_at_most_twice(self):
        # A window manager that refuses the size would otherwise be asked once per
        # tick, forever - a resize several times a second for as long as the app is
        # open. The state handed in never improves, which is the point.
        state = cramped_state()
        window = FakeWindow(state)
        guard = SizeGuard(window)
        for _ in range(TICKS):
            guard.hold(state)
        self.assertEqual(RESIZE_ATTEMPTS, len(window.resizes))

    def test_the_budget_is_returned_once_the_window_has_room(self):
        # Otherwise one bad stretch early on spends the budget for the session.
        window = FakeWindow()
        guard = SizeGuard(window)
        for _ in range(RESIZE_ATTEMPTS):
            guard.hold(cramped_state())
        guard.hold(roomy())
        window.resizes.clear()
        guard.hold(cramped_state())
        self.assertEqual(1, len(window.resizes))

    def test_it_asks_for_at_least_the_floor(self):
        state = cramped_state()
        window = FakeWindow(state)
        SizeGuard(window).hold(state)
        width, height = window.resizes[0]
        self.assertTrue(fits(width, height), f"{width}x{height} is still under the floor")


class OpeningTest(unittest.TestCase):
    def test_a_window_already_the_right_size_is_not_asked_about(self):
        # The common case on the second run of the day.
        window = FakeWindow(
            WindowState(
                width=DEFAULT_PLAN.start_width,
                height=DEFAULT_PLAN.start_height,
                maximized=False,
                minimized=False,
            )
        )
        self.assertFalse(SizeGuard(window).open_at_start_size())
        self.assertEqual([], window.resizes)

    def test_a_window_that_cannot_be_read_is_left_alone(self):
        window = FakeWindow(None)
        self.assertFalse(SizeGuard(window).open_at_start_size())
        self.assertEqual([], window.resizes)

    def test_a_maximized_window_opens_maximized(self):
        window = FakeWindow(cramped_state(maximized=True))
        self.assertFalse(SizeGuard(window).open_at_start_size())
        self.assertEqual([], window.resizes)

    def test_otherwise_it_opens_at_the_planned_size(self):
        window = FakeWindow(roomy())
        self.assertTrue(SizeGuard(window).open_at_start_size())
        self.assertEqual(
            [(DEFAULT_PLAN.start_width, DEFAULT_PLAN.start_height)], window.resizes
        )


if __name__ == "__main__":
    unittest.main()
