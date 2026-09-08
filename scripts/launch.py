"""The entry point a frozen build starts at.

PyInstaller freezes a SCRIPT, not a module - its `-m` is `--manifest`, and passing
`-m company_tui` makes it demand a scriptname it never got. `__main__.py` could be
named directly, but a file inside the package being run as a top-level script is
how a package ends up imported twice under two names.

So this is the script: it imports the package the normal way and calls the same
`main` the `dti` console command calls, which is what keeps a frozen build,
`dti` and `python -m company_tui` the same program.
"""

from company_tui.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
