"""What the interface looks like, as a value rather than as constants.

The colours, the window it opens at, and the order and shape of the menu grid -
the three things about the interface that are arrangement rather than behaviour.
Every default here is what the code held before, so a toolbox with no layout of its
own draws exactly what it always drew. `docs/decisions/0007` is why.

Nothing here imports a terminal framework: this is a document, and `branding.py`
turns the palette into a `Theme` on the other side of the boundary.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

SCHEMA = 1

COLOUR = "0123456789abcdefABCDEF"
"""What may follow the `#`. Checked here because an unreadable colour reaches
Textual as a theme it refuses, and an app with no theme is an unstyled one."""

MIN_CARDS_PER_ROW = 1
MAX_CARDS_PER_ROW = 6
"""More than six cards abreast is a row nobody reads; fewer than one is no menu."""

SMALLEST = 320
LARGEST = 10_000
"""Pixels. A window outside this was a typo, not a choice."""

DEFAULT_THEME = "default"
NAME_LENGTH = 32
NAME_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
"""A theme's name is a table key in the settings file, so it is spelled like one."""


@dataclass(frozen=True, slots=True)
class Palette:
    """The colours the interface is drawn from, as `#rrggbb`."""

    primary: str = "#123A63"
    secondary: str = "#3E6E9E"
    accent: str = "#E3A857"
    foreground: str = "#EAF1F8"
    background: str = "#081521"
    surface: str = "#0F2438"
    panel: str = "#153148"
    success: str = "#4CAF7D"
    warning: str = "#E3A857"
    error: str = "#D9534F"

    @property
    def colours(self) -> dict[str, str]:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "foreground": self.foreground,
            "background": self.background,
            "surface": self.surface,
            "panel": self.panel,
            "success": self.success,
            "warning": self.warning,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class Window:
    """The size to open at, and the size to hold to."""

    start_width: int = 1080
    start_height: int = 980
    min_width: int = 900
    min_height: int = 700


@dataclass(frozen=True, slots=True)
class Menu:
    """How the cards are laid out, and which of them there are."""

    cards_per_row: int = 3

    order: tuple[str, ...] = ()
    """Capability keys, first to last. Empty is the order they were registered in.

    Registration order is what the numbers people have learned follow, so the menu
    only departs from it where somebody has said to."""

    hidden: tuple[str, ...] = ()
    """Keys left off the menu. Never all of them - see `arrange`."""


@dataclass(frozen=True, slots=True)
class Layout:
    """Everything the builder edits about the interface itself."""

    themes: Mapping[str, Palette] = field(
        default_factory=lambda: {DEFAULT_THEME: Palette()}
    )
    """Named palettes. There is always at least one; which is which is a name."""

    theme: str = DEFAULT_THEME
    """Whichever of them the interface draws itself in."""

    window: Window = field(default_factory=Window)
    menu: Menu = field(default_factory=Menu)

    @property
    def palette(self) -> Palette:
        """The colours in use. Never raises: a theme can be deleted out from under
        the name pointing at it, and an interface with no colours is not an answer."""
        if self.theme in self.themes:
            return self.themes[self.theme]
        return next(iter(self.themes.values()), Palette())


def is_name(value: Any) -> bool:
    """Whether this can be a theme's name, which is to say a key in a settings file."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= NAME_LENGTH
        and all(letter in NAME_CHARACTERS for letter in value)
    )


def arrange(keys: tuple[str, ...], menu: Menu) -> tuple[str, ...]:
    """The menu's keys, in the order and selection `menu` asks for.

    Keys it has never heard of keep their registered position rather than being
    dropped: a layout written before a capability existed must not be able to hide
    one. And hiding everything is refused outright - a menu with no cards is an app
    with no way in, and the file saying so would have to be edited by hand to
    escape it.
    """
    wanted = [key for key in menu.order if key in keys]
    wanted += [key for key in keys if key not in wanted]
    shown = tuple(key for key in wanted if key not in menu.hidden)
    return shown or tuple(wanted)


def write_layout(layout: Layout) -> dict[str, Any]:
    """The whole layout as a document, including what equals the defaults."""
    return {
        "schema": SCHEMA,
        "theme": layout.theme,
        "themes": {
            name: dict(palette.colours)
            for name, palette in sorted(layout.themes.items())
        },
        "window": {
            "start_width": layout.window.start_width,
            "start_height": layout.window.start_height,
            "min_width": layout.window.min_width,
            "min_height": layout.window.min_height,
        },
        "menu": {
            "cards_per_row": layout.menu.cards_per_row,
            "order": list(layout.menu.order),
            "hidden": list(layout.menu.hidden),
        },
    }


def read_layout(
    document: Any, current: Layout | None = None
) -> tuple[Layout, tuple[str, ...]]:
    """Read what can be read, keep `current` for the rest, and report the gaps.

    Forgiving in the same way importing settings is, and for the same reason: a
    layout half of which was skipped silently is a screen somebody has to guess
    about. Every fallback is named.
    """
    settled = current or Layout()
    problems: list[str] = []
    if not isinstance(document, Mapping):
        return settled, ("that is not a layout - expected a JSON object",)

    schema = document.get("schema")
    if isinstance(schema, int) and schema > SCHEMA:
        problems.append(
            f"written for schema {schema}; this build understands {SCHEMA}, so "
            "anything newer than that was ignored"
        )

    themes = _themes(document, settled, problems)
    return (
        Layout(
            themes=themes,
            theme=_active(document, themes, settled.theme, problems),
            window=_window(document.get("window"), settled.window, problems),
            menu=_menu(document.get("menu"), settled.menu, problems),
        ),
        tuple(problems),
    )


def _themes(
    document: Mapping[str, Any], settled: Layout, problems: list[str]
) -> dict[str, Palette]:
    """The named palettes, never empty.

    A document carrying a bare `palette` and no `themes` is one written before
    there was more than one, and it reads as the default theme's colours - a file
    from an older shape has to keep working, the same as a line from an older
    command does.

    Never empty, because an interface has to be drawn in something and the name in
    `theme` has to have something to point at.
    """
    declared = document.get("themes")
    if declared is None:
        if "palette" not in document:
            return dict(settled.themes)
        return {
            DEFAULT_THEME: _palette(
                document.get("palette"), settled.palette, problems
            )
        }
    if not isinstance(declared, Mapping):
        problems.append("'themes' is not an object, so it was ignored")
        return dict(settled.themes)

    read: dict[str, Palette] = {}
    for name, colours in declared.items():
        if not is_name(name):
            problems.append(
                f"'{name}' is not a usable theme name, so that theme was ignored"
            )
            continue
        read[name] = _palette(colours, settled.themes.get(name, Palette()), problems)
    if not read:
        problems.append("no theme could be read, so the default one was put back")
        return {DEFAULT_THEME: Palette()}
    return read


def _active(
    document: Mapping[str, Any],
    themes: Mapping[str, Palette],
    fallback: str,
    problems: list[str],
) -> str:
    if "theme" not in document:
        return fallback if fallback in themes else next(iter(themes))
    wanted = document.get("theme")
    if wanted in themes:
        return wanted
    problems.append(f"theme '{wanted}' is not one of the themes, so it was ignored")
    return fallback if fallback in themes else next(iter(themes))


def is_colour(value: Any) -> bool:
    """A `#rgb` or `#rrggbb`, which is the whole of what a theme will take."""
    if not isinstance(value, str) or not value.startswith("#"):
        return False
    digits = value[1:]
    return len(digits) in (3, 6) and all(digit in COLOUR for digit in digits)


def _palette(value: Any, fallback: Palette, problems: list[str]) -> Palette:
    if value is None:
        return fallback
    if not isinstance(value, Mapping):
        problems.append("'palette' is not an object, so it was ignored")
        return fallback

    read = dict(fallback.colours)
    for key in fallback.colours:
        if key not in value:
            continue
        colour = value.get(key)
        if is_colour(colour):
            read[key] = colour
            continue
        problems.append(f"palette.{key} is not a colour like #1E8AC0, so it was ignored")
    return Palette(**read)


def _window(value: Any, fallback: Window, problems: list[str]) -> Window:
    """The sizes, with a floor that cannot end up above the size it is the floor for -
    that one would resize the window for opening at the size it was told to."""
    if value is None:
        return fallback
    if not isinstance(value, Mapping):
        problems.append("'window' is not an object, so it was ignored")
        return fallback

    read = {
        "start_width": _size(value, "start_width", fallback.start_width, problems),
        "start_height": _size(value, "start_height", fallback.start_height, problems),
        "min_width": _size(value, "min_width", fallback.min_width, problems),
        "min_height": _size(value, "min_height", fallback.min_height, problems),
    }
    window = Window(**read)
    if window.min_width > window.start_width or window.min_height > window.start_height:
        problems.append(
            "the smallest size was larger than the opening size, so it was brought down"
        )
        window = replace(
            window,
            min_width=min(window.min_width, window.start_width),
            min_height=min(window.min_height, window.start_height),
        )
    return window


def _size(value: Mapping[str, Any], key: str, fallback: int, problems: list[str]) -> int:
    if key not in value:
        return fallback
    size = value.get(key)
    if isinstance(size, bool) or not isinstance(size, int):
        problems.append(f"window.{key} is not a whole number of pixels, so it was ignored")
        return fallback
    if not SMALLEST <= size <= LARGEST:
        problems.append(
            f"window.{key} is {size}, which is outside {SMALLEST}-{LARGEST}, "
            "so it was ignored"
        )
        return fallback
    return size


def _menu(value: Any, fallback: Menu, problems: list[str]) -> Menu:
    if value is None:
        return fallback
    if not isinstance(value, Mapping):
        problems.append("'menu' is not an object, so it was ignored")
        return fallback

    across = fallback.cards_per_row
    if "cards_per_row" in value:
        asked = value.get("cards_per_row")
        if isinstance(asked, bool) or not isinstance(asked, int):
            problems.append("menu.cards_per_row is not a number, so it was ignored")
        elif not MIN_CARDS_PER_ROW <= asked <= MAX_CARDS_PER_ROW:
            problems.append(
                f"menu.cards_per_row is {asked}, which is outside "
                f"{MIN_CARDS_PER_ROW}-{MAX_CARDS_PER_ROW}, so it was ignored"
            )
        else:
            across = asked

    return Menu(
        cards_per_row=across,
        order=_keys(value, "order", fallback.order, problems),
        hidden=_keys(value, "hidden", fallback.hidden, problems),
    )


def _keys(
    value: Mapping[str, Any], key: str, fallback: tuple[str, ...], problems: list[str]
) -> tuple[str, ...]:
    if key not in value:
        return fallback
    listed = value.get(key)
    if not isinstance(listed, list) or any(
        not isinstance(entry, str) or not entry for entry in listed
    ):
        problems.append(f"menu.{key} is not a list of capability keys, so it was ignored")
        return fallback
    return tuple(dict.fromkeys(listed))
