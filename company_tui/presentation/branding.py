import sys
from pathlib import Path

from textual.theme import Theme

from company_tui.domain import naming

APP_NAME = naming.APP_NAME
APP_TAGLINE = naming.APP_TAGLINE
APP_SIGNATURE = naming.APP_SIGNATURE

VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def _version_candidates() -> tuple[Path, ...]:
    """Everywhere VERSION might be, in the order worth looking.

    Three places because the app runs three ways. In a checkout it is two
    directories up from this module. FROZEN, that path is inside the bundle and
    does not exist - PyInstaller unpacks bundled data under `sys._MEIPASS` for a
    onefile build and puts it beside the executable for a onedir one, and the
    build script adds VERSION as data precisely so one of those answers.

    Getting this wrong is quiet: the fallback below is a valid-looking version, so
    an installer built without it would ship a header reading v0.0.0+0 and nothing
    would fail.
    """
    frozen: list[Path] = []
    bundled = getattr(sys, "_MEIPASS", "")
    if bundled:
        frozen.append(Path(bundled) / "VERSION")
    if getattr(sys, "frozen", False):
        frozen.append(Path(sys.executable).resolve().parent / "VERSION")
    # A frozen app trusts its own bundle FIRST. The module-relative path can still
    # resolve to something inside the bundle, and reading a stray file there over
    # the one the build deliberately included is a version nobody chose.
    return (*frozen, VERSION_FILE)


def _version() -> str:
    """The one place the version is written, read rather than restated.

    A release rewrites `VERSION` and nothing else. The alternative was a literal
    here, which is a second copy of a fact — and the copy the header shows, so it
    is the one that goes stale while the file everything else derives from moves.

    Falls back rather than raising: the version decorates a header, and an app
    that refuses to start because it cannot find a text file is worse than one
    whose title bar is vague. An installed wheel has no repository around it.
    """
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
"""The product name, letter-spaced, for the splash screen.

Built from `APP_NAME` rather than written out: it was a second copy of the name,
and it was the copy on the first screen anybody sees - so it is the one that
would still say the old name after a rename.
"""

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

# A PLACEHOLDER, and deliberately abstract.
#
# What was here was one company's logo, converted from `assets/icons/ikaika.png`.
# This product is a generic toolbox, so a company mark is exactly the thing it
# should not open with - and an abstract mark is honest about there not being a
# logo yet, where a different company's logo would not be.
#
# It echoes LOGO_MARK above, scaled up. Block elements only: the geometric shapes
# and box-drawing characters are East Asian Ambiguous, so a terminal may draw them
# two cells wide and slide the whole line out of true. Blocks are always one cell,
# which `tests/test_glyphs.py` enforces.
#
# To put a real mark here, regenerate it from an image:
#   python -m tools.blockify <image>.png --rows 13 --name SPLASH_MARK
#
# The lines are ragged, so whatever shows this must not centre them one by one -
# see `SplashScreen #mark`.
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
"""The colour of a switch that is on.

Its own colour because neither of the two it sits between will do. `$error` is
red and red is for something that cannot be undone, which an option being ticked
is not; `$accent` is gold and gold already means focus, so a box that is both on
and focused would have nothing left to say the difference with. Orange is
between them in the palette as well as in what it means.

A constant rather than a theme variable, because a widget's `DEFAULT_CSS` is
parsed before any theme is active and `$toggle-on` would be an undefined
reference at that point. Interpolate this into an f-string of CSS instead — a
theme variable that resolves on some screens and not others is worse than not
having one.
"""

APP_THEME = Theme(
    # Named from APP_SLUG, so `self.theme = naming.APP_SLUG` in tui_console cannot
    # drift from what was registered - a mismatch there is an unstyled app.
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
