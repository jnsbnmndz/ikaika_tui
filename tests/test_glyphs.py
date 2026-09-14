"""Nothing the interface draws may be an emoji."""

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
"""Blocks a terminal may draw from an emoji font."""

TEXT_GLYPHS = {
    "✓": "CHECK MARK - a run that succeeded",
    "✕": "MULTIPLICATION X - the close mark on a run tab",
    "✗": "BALLOT X - a run that failed",
    "❯": "HEAVY RIGHT-POINTING ANGLE QUOTATION MARK - a prompt caret",
}
"""Inside those blocks but drawn from a text font. Narrow, monochrome, themed."""

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
        self.assertGreater(len(drawn_strings()), 200)

    def test_no_emoji_anywhere_in_the_interface(self):
        self.assertEqual([], offenders(is_emoji))

    def test_nothing_drawn_is_double_width(self):
        self.assertEqual([], offenders(is_wide))

    def test_it_would_actually_catch_one(self):
        for name in ("GRINNING FACE", "STOPWATCH", "CROSS MARK", "ROCKET", "WATCH"):
            self.assertTrue(is_emoji(unicodedata.lookup(name)), name)
        for char, why in TEXT_GLYPHS.items():
            self.assertFalse(is_emoji(char), why)
            self.assertFalse(is_wide(char), why)
        for name in ("BLACK CIRCLE", "BOX DRAWINGS LIGHT HORIZONTAL"):
            self.assertFalse(is_emoji(unicodedata.lookup(name)), name)

    def test_every_allowed_glyph_is_one_the_package_still_uses(self):
        drawn = {char for _, _, text in drawn_strings() for char in text}
        unused = sorted(c for c in TEXT_GLYPHS if c not in drawn)
        self.assertEqual([], unused)


class CardArtTest(unittest.TestCase):
    def test_every_card_art_entry_is_single_width(self):
        from company_tui.presentation.icons import _ART, DEFAULT_ART

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
