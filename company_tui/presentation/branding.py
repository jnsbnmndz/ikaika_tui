from textual.theme import Theme

APP_NAME = "IKAIKA"
APP_TAGLINE = "Developer Toolbox"
APP_VERSION = "v0.0.0+1"
APP_SIGNATURE = "IKAIKA Engineering"

PEAK_ART = "▲ ▲▲ ▲"
WORDMARK = "I K A I K A"

# Block elements, like the splash mark, rather than the geometric shapes this
# used to use. `▲` and the box-drawing characters are East Asian Ambiguous: a
# terminal is free to draw them two cells wide, which slides everything on the
# line out of place. Block elements are always one cell.
#
# Both lines are the same width, so the two halves stay stacked wherever the
# mark is placed.
LOGO_MARK = "\n".join(
    (
        " ▄█▄ ",
        "█████",
    )
)

# The company mark, generated from `assets/icons/ikaika.png` by `tools.blockify`
# and pasted in as text. Half blocks give square pixels and one colour, so the
# terminal draws it like any other characters: it takes the theme colour, costs
# nothing to repaint, and survives a resize — none of which is true of an image
# handed to the terminal as an image.
#
# Regenerate with:
#   python -m tools.blockify company_tui/assets/icons/ikaika.png \
#       --rows 13 --crop-bottom 0.34 --name SPLASH_MARK
#
# The lines are ragged, so whatever shows this must not centre them one by one —
# see `SplashScreen #mark`.
SPLASH_MARK = "\n".join(
    (
        "  █▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█",
        "  █        ▄█▄        █",
        "  █      ▄█▀ ▀█▄      █",
        "  █   ▄▄█▀ ▄▄▄ ▀█▄    █",
        "███ ▄█▀▀ ▄█▀▀▀█▄ ▀▀█▄ █",
        "█████  ▄█▀     ▀█▄  ▀██",
        "██ ████▀         ▀█▄▄ █ ▄",
        "██ ██▀██▄          ▀▀████",
        "██ ██  ▀█▄          ▄█▀██",
        "██ ██   ██        ▄███ ██",
        "██ ██   ██      ▄█▀ ██ ██",
        "██ ██   ██     ██   ██ ██",
        "██ ██   ██     ██   ██ ██",
    )
)

IKAIKA_THEME = Theme(
    name="ikaika",
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
