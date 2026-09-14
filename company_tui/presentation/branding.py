"""The theme, the wordmark and the splash mark. The version comes from `version.py`."""

from textual.theme import Theme

from company_tui.domain import naming
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
