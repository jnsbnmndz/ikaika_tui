"""The command line: four commands, three switches, and the app's own name.

EVERY NAME HERE IS DERIVED, NOT WRITTEN

`prog` was the literal "company" and the description was "Company developer
toolbox", so `dti --help` introduced itself as a program nobody has been able to
invoke by that name since the rename. Both come out of `domain/naming.py` now,
which is the file CLAUDE.md points at for exactly this reason: a name written
twice is a name that goes stale in the copy nobody looks at.

`--version` prints the same string the header shows, from the same `VERSION`
file (`docs/decisions/0002`). It is a switch rather than a command because it is
what every other program on the machine answers to, and somebody typing it is
not choosing between `tui` and `doctor`.
"""

import argparse
import asyncio

from company_tui.bootstrap import create_application, create_tui_console
from company_tui.domain import naming
from company_tui.presentation.branding import APP_VERSION
from company_tui.presentation.plain_console import PlainConsole

COMMANDS = """commands:
  tui       the interactive interface (default)
  list      every capability, as plain text
  doctor    what this machine is missing
  check     the definition of done: tests, list, doctor"""
"""Laid out rather than left to argparse's choices list.

`{tui,list,doctor,check}` is four words with no hint of what any of them does,
and the epilog is the only place a formatter will not reflow. Same shape as
`script.ps1`'s own listing, for the same reason.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=naming.APP_SLUG,
        description=f"{naming.APP_TITLE} - project scaffolding and automation",
        epilog=COMMANDS,
        # Raw, so COMMANDS keeps its columns. Without it argparse rewraps the
        # block into one paragraph and the alignment that makes it readable goes.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=("tui", "list", "doctor", "check"),
        default="tui",
        nargs="?",
        metavar="COMMAND",
        help="one of the four below; omit it for the interactive interface",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{naming.APP_TITLE} {APP_VERSION}",
        help="print the version and exit",
    )
    parser.add_argument(
        "--install-hook",
        action="store_true",
        help="with `check`, install it as this repository's pre-push hook",
    )
    parser.add_argument(
        "--start",
        default="",
        metavar="CAPABILITY",
        help=(
            "open on this capability instead of the menu, e.g. --start scripts. "
            "Backing out of it lands on the menu."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "check":
        from company_tui.check import main as run_checks

        return run_checks(install=args.install_hook)

    if args.command == "list":
        application = create_application(PlainConsole())
        application.print_capabilities()
        return 0

    if args.command == "doctor":
        application = create_application(PlainConsole())
        return asyncio.run(application.run_capability("doctor"))

    console = create_tui_console(args.start)
    console.run()
    return console.result_code
