"""Monochrome line art for menu cards.

Emoji were dropped here on purpose: terminals disagree about their width, which
shifts card layout, and their built-in colour competes with the accent colour
that marks selection. Box-drawing art is single-width and takes the theme colour.

Every line of an entry is left-padded relative to a shared centre, so the art is
rendered left-aligned inside an auto-width box and that box is centred as a unit.
"""

DEFAULT_ART = "\n".join(
    (
        " ╭─────╮",
        " │     │",
        " │  ·  │",
        " ╰─────╯",
    )
)

_ART = {
    "scaffold": "\n".join(
        (
            "    ╭╌╌╌╮",
            "    ╰─┬─╯",
            "  ╭───┴───╮",
            "╭╌┴╌╮   ╭╌┴╌╮",
            "╰╌╌╌╯   ╰╌╌╌╯",
        )
    ),
    "build": "\n".join(
        (
            "    ╭─╮",
            " ╭──┤◯├──╮",
            " │ ╭╯ ╰╮ │",
            " ╰─┤ ╳ ├─╯",
            "   ╰───╯",
        )
    ),
    "deploy": "\n".join(
        (
            "    ╱╲",
            "   ╱◯ ╲",
            "  ╱____╲",
            " ╱╱│  │╲╲",
            "   ╵  ╵",
        )
    ),
    "scripts": "\n".join(
        (
            " ╭────────╮",
            " │ ❯_     │",
            " │        │",
            " ╰────────╯",
        )
    ),
    "settings": "\n".join(
        (
            " ╶─●──────╴",
            " ╶──────●─╴",
            " ╶───●────╴",
            " ╶─────●──╴",
        )
    ),
    "doctor": "\n".join(
        (
            " ╭╮    ╭╮",
            " ╰╮    ╭╯",
            "  ╰─┬──╯ ─╱╲─",
            "    ╰──╮  ╲╱",
            "       ╰○",
        )
    ),
    "new_project": "\n".join(
        (
            " ╭──╮",
            " │  ╰────╮",
            " │  ─┼─  │",
            " ╰───────╯",
        )
    ),
    "controller": "\n".join(
        (
            "  ╭───╮",
            " ─┤ ● ├─",
            "  ╰─┬─╯",
            "    ╵",
        )
    ),
    "python": "\n".join(
        (
            " ╭───╮",
            " ╰─╮ │",
            " ╭─╯ │",
            " │ ╭─╯",
            " ╰─╯",
        )
    ),
    "flutter": "\n".join(
        (
            "    ╱╲",
            "   ╱  ╲",
            "  ╱ ╱╲ ╲",
            " ╱ ╱  ╲ ╲",
        )
    ),
    "react": "\n".join(
        (
            "  ╭───╮",
            " ╱  ●  ╲",
            " ╲     ╱",
            "  ╰───╯",
        )
    ),
    "react_native": "\n".join(
        (
            "  ╭─────╮",
            "  │ ╭─╮ │",
            "  │ │●│ │",
            "  │ ╰─╯ │",
            "  ╰─────╯",
        )
    ),
    "skeleton": "\n".join(
        (
            " ╭╌╌╌╌╌╌╮",
            " ╎ ───  ╎",
            " ╎ ──   ╎",
            " ╰╌╌╌╌╌╌╯",
        )
    ),
}


TERMINAL_ART = "\n".join(
    (
        "╭──────────╮",
        "│ ❯_       │",
        "╰──────────╯",
    )
)
"""Shown in the middle of a run panel's terminal while it has nothing in it —
the same line-art vocabulary the cards use, for the same reason."""


def art_for(key: str) -> str:
    return _ART.get(key, DEFAULT_ART)
