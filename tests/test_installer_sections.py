"""A section constant used before its `Section` is compiled reads as index 0: SecCore."""

import re
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "installer.nsi"

DECLARATION = re.compile(r"^\s*Section\b[^;\n]*?\b(Sec\w+)\s*$", re.MULTILINE)
REFERENCE = re.compile(r"\$\{(Sec\w+)\}")


def _lines(text):
    return text.splitlines()


def declarations(text):
    """Each section's name and the line its `Section` is on."""
    found = {}
    for number, line in enumerate(_lines(text), start=1):
        match = DECLARATION.match(line)
        if match:
            found.setdefault(match.group(1), number)
    return found


def used_too_early(text):
    """Every `${SecX}` that appears before the line declaring SecX."""
    declared = declarations(text)
    offenders = []
    for number, line in enumerate(_lines(text), start=1):
        if line.lstrip().startswith(";"):
            continue
        for name in REFERENCE.findall(line):
            if name in declared and number < declared[name]:
                offenders.append(f"line {number} uses ${{{name}}}, declared at {declared[name]}")
    return offenders


class SectionConstantsAreDeclaredBeforeUse(unittest.TestCase):
    """The installer ran, installed nothing, and exited 0.

    `${SecDesktop}` and friends are defines the compiler creates when it reaches each
    Section. `.onInit` and `RestoreChoice` sat above them, so the constants did not exist
    yet - `warning 6000: unknown variable/constant "{SecDesktop}" detected, ignoring` on
    every build - and NSIS read the literal text as section index 0, which is SecCore.

    `RestoreOne "Desktop"` then read the recorded "0" that an unwanted desktop shortcut
    leaves behind and UNSELECTED THE REQUIRED COMPONENT. Every update after the first
    install silently did nothing. docs/pitfalls.md 7.3.
    """

    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_the_walk_finds_the_sections(self):
        found = declarations(self.text)
        self.assertIn("SecCore", found)
        self.assertGreaterEqual(len(found), 4, "the sections are no longer being found")

    def test_no_section_constant_is_used_before_it_exists(self):
        self.assertEqual([], used_too_early(self.text))

    def test_the_detector_still_catches_one(self):
        """A check of the form "nothing does X" needs X to still be detectable."""
        broken = 'Function .onInit\n  !insertmacro UnselectSection ${SecCore}\nFunctionEnd\n'
        broken += 'Section "!Thing" SecCore\nSectionEnd\n'
        self.assertTrue(used_too_early(broken), "the detector has stopped detecting")

    def test_a_comment_mentioning_one_is_not_a_use(self):
        # The fix left a note above the moved block naming ${SecPath}; a comment is prose.
        commented = '; talks about ${SecCore}\nSection "!Thing" SecCore\nSectionEnd\n'
        self.assertEqual([], used_too_early(commented))
