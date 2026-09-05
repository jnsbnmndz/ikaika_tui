"""Everything the definition of done asks for, in one command.

`python -m company_tui check`. This repository has no cloud CI, so this is the
gate - the same role `check-all` plays in the PowerShell toolkit, and written to
the same two rules that make such a gate worth having:

  A skip is REPORTED, never omitted. A run must never be able to look like it
  verified something it did not, so a missing tool prints SKIP and says why. The
  alternative - quietly dropping the check - is the failure mode the gate exists
  to prevent.

  A check that stops checking is a failure. `unittest` finding zero tests is
  reported as FAIL rather than PASS: this repository shipped with `tests/`
  gitignored and `discover` cheerfully answering OK over nothing at all, which
  is exactly how two documented, non-existent test files went unnoticed.

Every check is a subprocess of this same interpreter, so the venv running the
gate is the venv the checks run in - `sys.executable`, never a bare `python`.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

HOOK_NAME = "pre-push"
HOOK_BODY = """#!/bin/sh
# Installed by `python -m company_tui check --install-hook`.
exec "{python}" -m company_tui check
"""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    argv: tuple[str, ...]
    expect_output: str = ""
    """A string the output must contain for the check to count as having run."""


CHECKS = (
    Check("unit tests", ("-m", "unittest", "discover", "-v"), expect_output="Ran "),
    Check("list", ("-m", "company_tui", "list"), expect_output="scripts"),
    Check("doctor", ("-m", "company_tui", "doctor"), expect_output="Python:"),
)


def _no_tests_ran(output: str) -> bool:
    """`unittest discover` exits 0 when it finds nothing at all."""
    return "NO TESTS RAN" in output or "Ran 0 tests" in output


def run_check(check: Check) -> tuple[str, str]:
    try:
        finished = subprocess.run(
            [sys.executable, *check.argv],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return SKIP, f"could not start: {error}"

    output = f"{finished.stdout}\n{finished.stderr}"
    if finished.returncode != 0:
        return FAIL, output.strip().splitlines()[-1] if output.strip() else "exited non-zero"
    if check.expect_output and check.expect_output not in output:
        return FAIL, f"ran, but said nothing about {check.expect_output.strip()!r}"
    if check.name == "unit tests" and _no_tests_ran(output):
        return FAIL, "discover found no tests - a gate over nothing is not a gate"

    detail = ""
    for line in reversed(output.strip().splitlines()):
        if line.startswith(("Ran ", "OK", "Status:")):
            detail = line.strip()
            break
    return PASS, detail


def install_hook() -> int:
    hooks = ROOT / ".git" / "hooks"
    if not hooks.is_dir():
        print(f"  No {hooks} - is this a git checkout?")
        return 1
    target = hooks / HOOK_NAME
    target.write_text(HOOK_BODY.format(python=sys.executable), encoding="utf-8")
    target.chmod(0o755)
    print(f"  Installed {target}")
    return 0


def main(install: bool = False) -> int:
    if install:
        return install_hook()

    print()
    width = max(len(check.name) for check in CHECKS)
    worst = 0
    for check in CHECKS:
        status, detail = run_check(check)
        print(f"  [{status}] {check.name:<{width}}  {detail}")
        if status == FAIL:
            worst = 1
    print()
    print("  All checks passed." if worst == 0 else "  Something failed - see above.")
    print()
    return worst
