"""The theme, the wordmark, the splash mark and the version read from VERSION."""

import sys
from pathlib import Path

from textual.theme import Theme

from company_tui.domain import naming

APP_NAME = naming.APP_NAME
APP_TAGLINE = naming.APP_TAGLINE
APP_SIGNATURE = naming.APP_SIGNATURE

VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def _version_candidates() -> tuple[Path, ...]:
    """Everywhere VERSION might be, in the order worth looking."""
    frozen: list[Path] = []
    bundled = getattr(sys, "_MEIPASS", "")
    if bundled:
        frozen.append(Path(bundled) / "VERSION")
    if getattr(sys, "frozen", False):
        frozen.append(Path(sys.executable).resolve().parent / "VERSION")
    return (*frozen, VERSION_FILE)


def _version() -> str:
    """The one place the version is written, read rather than restated."""
    for candidate in _version_candidates():
        try:
            raw = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw:
            return f"v{raw}"
    return "v0.0.0+0"


APP_VERSION = _version()

PEAK_ART = "▲ ▲▲ ▲"
WORDMARK = " ".join(APP_NAME)
"""The product name, letter-spaced, for the splash screen."""

LOGO_MARK = "\n".join(
    (
        " ▄█▄ ",
        "█████",
    )
)

SPLASH_MARK = "\n".join(
    (
        "            \u2588",
        "          \u2588\u2588 \u2588\u2588",
        "        \u2588\u2588     \u2588\u2588",
        "      \u2588\u2588         \u2588\u2588",
        "    \u2588\u2588      \u2588      \u2588\u2588",
        "  \u2588\u2588      \u2588\u2588 \u2588\u2588      \u2588\u2588",
        "\u2588\u2588      \u2588\u2588     \u2588\u2588      \u2588\u2588",
        "  \u2588\u2588      \u2588\u2588 \u2588\u2588      \u2588\u2588",
        "    \u2588\u2588      \u2588      \u2588\u2588",
        "      \u2588\u2588         \u2588\u2588",
        "        \u2588\u2588     \u2588\u2588",
        "          \u2588\u2588 \u2588\u2588",
        "            \u2588",
    )
)

TOGGLE_ON = "#EA7B2E"
"""The colour of a switch that is on."""

APP_THEME = Theme(
    name=naming.APP_SLUG,
    primary="#123A63",
    secondary="#3E6E9E",
    accent="#E3A857",
    foreground="#EAF1F8",
    background="#081521",
    surface="#0F2438",
    panel="#153148",
    success="#4CAF7D",
    warning="#E3A857",
    error="#D9534F",
    dark=True,
)
