"""The command line: four commands, three switches, and the app's own name."""

import argparse
import asyncio

from company_tui.domain import naming
from company_tui.presentation.plain_console import PlainConsole
from company_tui.version import APP_VERSION

COMMANDS = """commands:
  tui       the interactive interface (default)
  list      every capability, as plain text
  doctor    what this machine is missing
  check     the definition of done: tests, list, doctor"""
"""Laid out rather than left to argparse's choices list."""

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=naming.APP_SLUG,
        description=f"{naming.APP_TITLE} - project scaffolding and automation",
        epilog=COMMANDS,
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
        from company_tui.bootstrap import create_application

        application = create_application(PlainConsole())
        application.print_capabilities()
        return 0

    if args.command == "doctor":
        from company_tui.bootstrap import create_application

        application = create_application(PlainConsole())
        return asyncio.run(application.run_capability("doctor"))

    from company_tui.bootstrap import create_tui_console

    console = create_tui_console(args.start)
    console.run()
    return console.result_code
