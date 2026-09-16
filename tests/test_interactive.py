"""The list protocol, and the rule that an unreadable line is only ever text."""

import json
import unittest

from company_tui.domain.interactive import (
    END,
    INTERACTIVE_VAR,
    PICK,
    ROWS,
    Finished,
    Listing,
    Row,
    parse,
    pick,
)

COUNTDOWN_ROWS = [{"id": "go", "label": "Keep going"}, {"id": "stop", "label": "Stop"}]


def _rows(**document):
    return f"{ROWS} {json.dumps(document)}"


class ReadingALine(unittest.TestCase):
    def test_ordinary_output_is_ordinary_output(self):
        for line in ("Cloning into 'x'...", "", "  @dti:rows leading space", "@ dti:rows"):
            self.assertIsNone(parse(line), line)

    def test_a_listing_comes_back_whole(self):
        listing = parse(_rows(
            title="ACC / Project Files",
            hint="Enter opens",
            rows=[
                {"id": "1", "label": "00_BIM", "kind": "folder"},
                {"id": "10", "label": "Deck.pptx", "kind": "file", "detail": "v1  97 MB"},
            ],
        ))
        self.assertIsInstance(listing, Listing)
        self.assertEqual("ACC / Project Files", listing.title)
        self.assertEqual("Enter opens", listing.hint)
        self.assertEqual(
            (Row("1", "00_BIM", "folder", ""), Row("10", "Deck.pptx", "file", "v1  97 MB")),
            listing.rows,
        )

    def test_only_id_and_label_are_required(self):
        listing = parse(_rows(rows=[{"id": "a", "label": "A"}]))
        self.assertEqual((Row("a", "A"),), listing.rows)

    def test_an_empty_listing_is_still_a_listing(self):
        self.assertEqual(Listing(), parse(_rows(rows=[])))

    def test_end_closes_the_view(self):
        self.assertIsInstance(parse(END), Finished)

    def test_a_pick_is_the_id_verbatim(self):
        self.assertEqual(f"{PICK} 10", pick("10"))
        self.assertEqual(f"{PICK} a b/c", pick("a b/c"))

    def test_the_variable_is_named_after_the_app(self):
        self.assertEqual("DTI_INTERACTIVE", INTERACTIVE_VAR)


class AMalformedLineIsPrintedNotRaised(unittest.TestCase):
    """A command from a future version must not be able to break an older toolbox."""

    def test_broken_json_is_text(self):
        self.assertIsNone(parse(f"{ROWS} {{not json"))
        self.assertIsNone(parse(f"{ROWS} "))
        self.assertIsNone(parse(ROWS))

    def test_a_verb_this_build_does_not_know_is_text(self):
        self.assertIsNone(parse("@dti:tree {}"))
        self.assertIsNone(parse("@dti:"))

    def test_a_payload_that_is_not_an_object_is_text(self):
        for payload in ("[]", '"rows"', "null", "7"):
            self.assertIsNone(parse(f"{ROWS} {payload}"), payload)

    def test_rows_that_are_not_a_list_is_text(self):
        self.assertIsNone(parse(_rows(rows={"id": "1"})))
        self.assertIsNone(parse(_rows(title="no rows key")))

    def test_a_row_missing_what_is_required_is_text(self):
        self.assertIsNone(parse(_rows(rows=[{"label": "no id"}])))
        self.assertIsNone(parse(_rows(rows=[{"id": "no label"}])))
        self.assertIsNone(parse(_rows(rows=[{"id": "", "label": "blank"}])))
        self.assertIsNone(parse(_rows(rows=[{"id": 10, "label": "not a string"}])))
        self.assertIsNone(parse(_rows(rows=["just a string"])))

    def test_an_id_cannot_smuggle_a_newline(self):
        # It is written back on stdin as one line; a second line would be a second
        # command as far as the process is concerned.
        self.assertIsNone(parse(_rows(rows=[{"id": "a\nb", "label": "x"}])))

    def test_an_absurd_payload_is_refused_rather_than_parsed(self):
        self.assertIsNone(parse(f"{ROWS} " + '{"rows":[]}' + " " * (512 * 1024)))

    def test_keys_it_does_not_know_are_ignored(self):
        listing = parse(_rows(
            rows=[{"id": "1", "label": "A", "icon": "x", "children": [1, 2]}],
            footer="from a later version",
        ))
        self.assertEqual((Row("1", "A"),), listing.rows)


class TheCountdown(unittest.TestCase):
    """Two optional fields on the same payload, and they travel together."""

    def _listing(self, **document):
        return parse(_rows(rows=COUNTDOWN_ROWS, **document))

    def test_a_listing_says_so_when_it_carries_one(self):
        listing = self._listing(timeout=20, default="stop")
        self.assertEqual(20, listing.timeout)
        self.assertEqual("stop", listing.default)
        self.assertTrue(listing.counts_down)

    def test_a_listing_that_says_nothing_waits(self):
        listing = self._listing()
        self.assertEqual(0, listing.timeout)
        self.assertEqual("", listing.default)
        self.assertFalse(listing.counts_down)

    def test_a_timeout_naming_no_row_is_dropped_whole(self):
        # Not aimed at row zero. A command that meant "give up" and got "retry"
        # because its id had a typo in it is the failure this rule exists for.
        for default in ("keep", "", "GO", None, 0, ["stop"]):
            listing = self._listing(timeout=20, default=default)
            self.assertEqual((0, ""), (listing.timeout, listing.default), repr(default))

    def test_a_timeout_with_no_default_at_all_is_dropped(self):
        listing = self._listing(timeout=20)
        self.assertEqual((0, ""), (listing.timeout, listing.default))

    def test_a_default_with_no_timeout_is_dropped(self):
        listing = self._listing(default="stop")
        self.assertEqual((0, ""), (listing.timeout, listing.default))

    def test_zero_and_below_is_todays_behaviour(self):
        for seconds in (0, -1, -900):
            listing = self._listing(timeout=seconds, default="stop")
            self.assertFalse(listing.counts_down, seconds)

    def test_a_timeout_that_is_not_a_number_is_dropped_not_fatal(self):
        # The rows are still a perfectly good listing; only the countdown is lost.
        for seconds in ("20", None, True, False, [20], {"seconds": 20}):
            listing = self._listing(timeout=seconds, default="stop")
            self.assertIsInstance(listing, Listing, repr(seconds))
            self.assertEqual(2, len(listing.rows))
            self.assertFalse(listing.counts_down, repr(seconds))

    def test_part_of_a_second_still_counts_as_one(self):
        self.assertEqual(1, self._listing(timeout=0.4, default="stop").timeout)
        self.assertEqual(20, self._listing(timeout=20.9, default="stop").timeout)

    def test_the_countdown_can_be_taken_back_out(self):
        listing = self._listing(timeout=20, default="stop")
        waiting = listing.untimed()
        self.assertFalse(waiting.counts_down)
        self.assertEqual(listing.rows, waiting.rows)
        self.assertEqual(listing.title, waiting.title)
        self.assertEqual(listing.hint, waiting.hint)

    def test_an_absurd_timeout_is_still_only_a_timeout(self):
        self.assertEqual(10**9, self._listing(timeout=10**9, default="stop").timeout)
