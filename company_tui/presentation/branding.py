"""The theme, the wordmark and the splash mark. The version comes from `version.py`."""

from textual.theme import Theme

from company_tui.domain import naming
from company_tui.domain.layout import Palette
from company_tui.version import APP_VERSION as APP_VERSION

APP_NAME = naming.APP_NAME
APP_TAGLINE = naming.APP_TAGLINE
APP_SIGNATURE = naming.APP_SIGNATURE

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

def theme_from(palette: Palette) -> Theme:
    """The theme these colours make.

    Its name is always `naming.APP_SLUG`, because what is registered and what
    `TuiConsole` activates cannot be allowed to drift - a mismatch there is an
    unstyled app. Only the colours are the palette's to decide.
    """
    return Theme(name=naming.APP_SLUG, dark=True, **palette.colours)


APP_THEME = theme_from(Palette())
"""What the interface draws itself in where nobody has arranged otherwise."""
