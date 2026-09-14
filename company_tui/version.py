"""The running version, read from VERSION and nothing else imported to get it."""

import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
FALLBACK = "v0.0.0+0"


def _candidates() -> tuple[Path, ...]:
    """Everywhere VERSION might be, in the order worth looking."""
    frozen: list[Path] = []
    bundled = getattr(sys, "_MEIPASS", "")
    if bundled:
        frozen.append(Path(bundled) / "VERSION")
    if getattr(sys, "frozen", False):
        frozen.append(Path(sys.executable).resolve().parent / "VERSION")
    return (*frozen, VERSION_FILE)


def read_version() -> str:
    """The one place the version is written, read rather than restated."""
    for candidate in _candidates():
        try:
            raw = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw:
            return f"v{raw}"
    return FALLBACK


APP_VERSION = read_version()
