"""Every menu step the console records has to be a step it knows about.

`TRAIL_STEPS` is ordered, and `_enter_step` indexes into it to forget a step and
everything after it. A name missing from that tuple raises `ValueError` — which
is caught by the run supervisor as a failed workflow, written to a session log
nobody is looking at, and answered by calmly putting the previous menu back. The
capability appears to open and vanish, with no error anywhere the user can see.

That is exactly what a new `script_section` step did, so this reads the step
names back out of the source rather than listing them again here: a test that
repeated the tuple would agree with itself and still miss the next one.
"""

import ast
import unittest
from pathlib import Path

from company_tui.presentation.tui_console import TRAIL_STEPS

SOURCE = Path(__file__).resolve().parents[1] / "company_tui" / "presentation" / "tui_console.py"


def recorded_steps() -> set[str]:
    """Every literal step name passed to `_enter_step` or `_record`."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("_enter_step", "_record", "_replay"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str):
                names.add(node.args[0].value)
    return names


class TrailStepsTest(unittest.TestCase):
    def test_every_recorded_step_is_declared(self):
        undeclared = sorted(recorded_steps() - set(TRAIL_STEPS))
        self.assertEqual(
            [],
            undeclared,
            f"{undeclared} are used as steps but missing from TRAIL_STEPS, so "
            "_enter_step raises and the workflow dies silently",
        )

    def test_the_source_really_does_record_steps(self):
        # Guards the guard: if the AST walk stopped matching, the test above would
        # pass by finding nothing at all.
        self.assertIn("capability", recorded_steps())
        self.assertIn("script_section", recorded_steps())

    def test_a_section_is_forgotten_before_the_action_under_it(self):
        # Order decides what going back clears. A section listed after its own
        # actions would leave a stale action behind when the section changes.
        self.assertLess(
            TRAIL_STEPS.index("script_section"), TRAIL_STEPS.index("script_action")
        )


if __name__ == "__main__":
    unittest.main()
