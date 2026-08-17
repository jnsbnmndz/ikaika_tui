import argparse
import asyncio

from company_tui.bootstrap import create_application, create_tui_console
from company_tui.presentation.plain_console import PlainConsole


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="company",
        description="Company developer toolbox",
    )
    parser.add_argument(
        "command",
        choices=("tui", "list", "doctor"),
        default="tui",
        nargs="?",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "list":
        application = create_application(PlainConsole())
        application.print_capabilities()
        return 0

    if args.command == "doctor":
        application = create_application(PlainConsole())
        return asyncio.run(application.run_capability("doctor"))

    console = create_tui_console()
    console.run()
    return console.result_code
