"""Nothing the interface draws may be an emoji.

CLAUDE.md and AGENT.md both say this file enforces the rule. It did not exist -
`tests/` was gitignored, so the enforcement the documentation promised had
quietly not been there. This is that test.

Why the rule: a codepoint a terminal treats as emoji is drawn from an emoji font
rather than a text one. It comes out double width, so every column after it on
the line is wrong; in a colour that ignores the theme; and at a weight nothing
like the box-drawing art beside it. They read perfectly well in an editor, which
is exactly how a stop mark on the Run button and a stopwatch on each run's
timestamp both got in.


WHY RANGES AND AN ALLOWLIST, RATHER THAN A WIDTH TEST

Width does not separate them. U+23F1 STOPWATCH is East Asian Narrow and is an
emoji; U+2715 MULTIPLICATION X is Narrow and is not; U+274C CROSS MARK is Wide
and is. A width test passes the exact glyph the docs name as one that got in.

So the emoji BLOCKS are banned outright and the handful of text-presentation
glyphs inside them are allowed by name. Four characters, each one already in use
and each one legible in a terminal font - which is the whole test. Adding a
fifth means writing down why it is text and not a picture.

Width is still checked, as a second net: card art is laid out by counting
characters, so one wide glyph from any block shifts every column after it.

Read from the SOURCE with `ast`, not from a rendered screen. A string reachable
only from an error path never appears in a snapshot, and that is the one somebody
sees on the day something has already gone wrong. `ast` also resolves escapes, so
`"\\U0001F600"` is caught however innocent it looks in the file.
"""

import ast
import unicodedata
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "company_tui"

EMOJI_RANGES = (
    (0x231A, 0x231B),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F000, 0x1FAFF),
    (0xFE0F, 0xFE0F),
    (0x200D, 0x200D),
)
"""Blocks a terminal may draw from an emoji font.

The last two are the variation selector and the zero-width joiner: neither draws
anything itself, and both exist to turn the codepoint beside them into a picture.
"""

TEXT_GLYPHS = {
    "✓": "CHECK MARK - a run that succeeded",
    "✕": "MULTIPLICATION X - the close mark on a run tab",
    "✗": "BALLOT X - a run that failed",
    "❯": "HEAVY RIGHT-POINTING ANGLE QUOTATION MARK - a prompt caret",
}
"""Inside those blocks but drawn from a text font. Narrow, monochrome, themed.

Every entry is a character already in use. A new one belongs here only with a
reason, because the default answer to "can I use this symbol" is no.
"""

ALLOWED_WIDE: frozenset[str] = frozenset()
"""Codepoints permitted to occupy two cells. Empty, and adding one needs a reason."""


def is_emoji(char: str) -> bool:
    if char in TEXT_GLYPHS:
        return False
    code = ord(char)
    return any(low <= code <= high for low, high in EMOJI_RANGES)


def is_wide(char: str) -> bool:
    return unicodedata.east_asian_width(char) in ("W", "F") and char not in ALLOWED_WIDE


def drawn_strings() -> list[tuple[Path, int, str]]:
    """Every non-docstring string literal in the package, and where it was written."""
    found: list[tuple[Path, int, str]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, holders)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            found.append((path, node.lineno, node.value))
    return found


def offenders(predicate) -> list[str]:
    return sorted(
        {
            f"{path.relative_to(PACKAGE.parent)}:{line} {char!r} (U+{ord(char):04X})"
            for path, line, text in drawn_strings()
            for char in text
            if predicate(char)
        }
    )


class GlyphTest(unittest.TestCase):
    def test_the_package_has_strings_to_check(self):
        # Guards the guard: a broken walk makes every test below vacuous.
        self.assertGreater(len(drawn_strings()), 200)

    def test_no_emoji_anywhere_in_the_interface(self):
        self.assertEqual([], offenders(is_emoji))

    def test_nothing_drawn_is_double_width(self):
        self.assertEqual([], offenders(is_wide))

    def test_it_would_actually_catch_one(self):
        # Both directions. A detector that finds nothing passes the two tests
        # above forever, which is how the rule went unenforced in the first place.
        for name in ("GRINNING FACE", "STOPWATCH", "CROSS MARK", "ROCKET", "WATCH"):
            self.assertTrue(is_emoji(unicodedata.lookup(name)), name)
        for char, why in TEXT_GLYPHS.items():
            self.assertFalse(is_emoji(char), why)
            self.assertFalse(is_wide(char), why)
        for name in ("BLACK CIRCLE", "BOX DRAWINGS LIGHT HORIZONTAL"):
            self.assertFalse(is_emoji(unicodedata.lookup(name)), name)

    def test_every_allowed_glyph_is_one_the_package_still_uses(self):
        # An allowlist outlives what it was written for. An entry nothing draws
        # any more is permission nobody asked for.
        drawn = {char for _, _, text in drawn_strings() for char in text}
        unused = sorted(c for c in TEXT_GLYPHS if c not in drawn)
        self.assertEqual([], unused)


class CardArtTest(unittest.TestCase):
    def test_every_card_art_entry_is_single_width(self):
        from company_tui.presentation.icons import DEFAULT_ART, _ART

        for key, art in list(_ART.items()) + [("__default__", DEFAULT_ART)]:
            for line in art.splitlines():
                wide = [c for c in line if is_wide(c)]
                self.assertEqual([], wide, f"{key} draws {wide} wider than one cell")

    def test_art_is_no_taller_than_a_card_shows(self):
        from company_tui.presentation.icons import _ART

        for key, art in _ART.items():
            self.assertLessEqual(len(art.splitlines()), 6, f"{key} has too many rows")


if __name__ == "__main__":
    unittest.main()
