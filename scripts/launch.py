"""The entry point a frozen build starts at: PyInstaller freezes a script, not a module."""

from company_tui.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
