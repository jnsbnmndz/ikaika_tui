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
    # What a script repository declares. Keyed by the manifest's own words, so a
    # repository that adds a section gets a placeholder rather than nothing —
    # `art_for` already falls back, and these are the ones the stacks use today.
    "android": "\n".join(
        (
            "  ╲     ╱",
            " ╭───────╮",
            " │ ●   ● │",
            " ╰───────╯",
        )
    ),
    "ios": "\n".join(
        (
            " ╭─────╮",
            " │     │",
            " │     │",
            " ╰──▭──╯",
        )
    ),
    "web": "\n".join(
        (
            " ╭───────╮",
            " │ ● ● ● │",
            " ├───────┤",
            " ╰───────╯",
        )
    ),
    "window": "\n".join(
        (
            " ╭──┬────╮",
            " ├──┼────┤",
            " │  │    │",
            " ╰──┴────╯",
        )
    ),
    "macos": "\n".join(
        (
            " ╭───────╮",
            " │       │",
            " ╰──┬─┬──╯",
            "  ──┴─┴──",
        )
    ),
    "linux": "\n".join(
        (
            "  ╭───╮",
            "  │● ●│",
            " ╭╯ ▾ ╰╮",
            " ╰─────╯",
        )
    ),
    "screen": "\n".join(
        (
            " ╭────────╮",
            " │        │",
            " ╰───┬────╯",
            "   ──┴──",
        )
    ),
    "layout": "\n".join(
        (
            " ╭───┬────╮",
            " ├───┼────┤",
            " │   │    │",
            " ╰───┴────╯",
        )
    ),
    "widget": "\n".join(
        (
            "   ╭───╮",
            " ╭─┤   ├─╮",
            " │ ╰───╯ │",
            " ╰───────╯",
        )
    ),
    "apiEndpoint": "\n".join(
        (
            " ●───╮",
            "     ╰──▸",
            " ●───╮",
            "     ╰──▸",
        )
    ),
    "apiModel": "\n".join(
        (
            " ╭───────╮",
            " ├───────┤",
            " ├───────┤",
            " ╰───────╯",
        )
    ),
    "service": "\n".join(
        (
            "  ╭─╮ ╭─╮",
            " ─┤ ├─┤ ├─",
            "  ╰─╯ ╰─╯",
        )
    ),
    "storage": "\n".join(
        (
            " ╭───────╮",
            " ╰───────╯",
            " ╭───────╮",
            " ╰───────╯",
        )
    ),
    "utility": "\n".join(
        (
            "  ╭─╮",
            " ─┤ ├───╮",
            "  ╰─╯   │",
            "      ──╯",
        )
    ),
    "state": "\n".join(
        (
            " ╭─╮   ╭─╮",
            " ╰┬╯───╯ │",
            "  ╰──────╯",
        )
    ),
    "manager": "\n".join(
        (
            "    ╭─╮",
            "  ╭─┴─┴─╮",
            " ╭┴╮   ╭┴╮",
            " ╰─╯   ╰─╯",
        )
    ),
    "constant": "\n".join(
        (
            " ╭───────╮",
            " │ ══ ══ │",
            " ╰───────╯",
        )
    ),
    "enum": "\n".join(
        (
            " ● ─────",
            " ● ───",
            " ● ───────",
        )
    ),
    # The three ways out of a store that has fallen behind.
    # Sections of a project's own script config, keyed by the domain names the
    # IKAIKA PowerShell toolkit emits. A document naming its sections anything
    # else gets DEFAULT_ART, which is what art_for's fallback exists for.
    # A branch leaving a line of commits and coming back to it.
    "git": "\n".join(
        (
            "    ╭─●─╮",
            " ─●─╯   ╰─●─",
            "  │       │",
            "  ╰───────╯",
        )
    ),
    # A ribboned seal: a signature, which is what these commands produce.
    "windows": "\n".join(
        (
            " ╭─────╮",
            " │  ✓  │",
            " ╰──┬──╯",
            "   ╱ ╲",
            "  ╵   ╵",
        )
    ),
    # A prompt with a caret, for a project's own commands.
    "commands": "\n".join(
        (
            " ╭────────╮",
            " │ ❯ ▁▁▁  │",
            " │ ❯ ▁▁   │",
            " ╰────────╯",
        )
    ),
    # Plates coming off a compiler and stacking up.
    "dotnet": "\n".join(
        (
            "  ╭─────╮",
            "  ╰──┬──╯",
            " ╭───┴───╮",
            " ╰───┬───╯",
            "     ╵",
        )
    ),
    # A wireframe solid - a model, which is what the host add-in works on.
    "navisworks": "\n".join(
        (
            "   ╭───╮",
            "  ╱│  ╱│",
            " ╭───╮ │",
            " │ ╰─│─╯",
            " ╰───╯",
        )
    ),
    # A crate with a version band: the tooling as the thing being shipped.
    "toolkit": "\n".join(
        (
            " ╭───────╮",
            " │═══════│",
            " │  ┼┼   │",
            " ╰───────╯",
        )
    ),
    # An elephant's head in profile, the way the language is usually drawn.
    "php": "\n".join(
        (
            " ╭──────╮",
            " │ ●  ● │",
            " ╰──┬───╯",
            "    │╲",
            "    ╵ ╲",
        )
    ),
    "reclone": "\n".join(
        (
            " ╭───────╮",
            " ╵       ▾",
            " ▴       ╷",
            " ╰───────╯",
        )
    ),
    "keep": "\n".join(
        (
            " ╭───────╮",
            " │  ═══  │",
            " │  ═══  │",
            " ╰───────╯",
        )
    ),
    "silence": "\n".join(
        (
            " ╭───────╮",
            " │ ╲   ╱ │",
            " │   ╳   │",
            " ╰───────╯",
        )
    ),
}


TERMINAL_ART = "\n".join(
    (
        "╭─────╮",
        "│ ❯_  │",
        "╰─────╯",
    )
)
"""Shown in the middle of a run panel's terminal while it has nothing in it —
the same line-art vocabulary the cards use, for the same reason."""


def art_for(key: str) -> str:
    return _ART.get(key, DEFAULT_ART)
