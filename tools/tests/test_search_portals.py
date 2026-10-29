"""Tests for the search step: what is sent, and what comes back.

Two things are checked here. The relaxation ladder - a portal's facets are
ANDed, and in a small market the stack can be empty, so a facet is dropped
when a search finds nothing. And the market check - a portal that answers a
country filter with postings from another country is not answering the
question.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from search_portals import in_market, relaxed_call  # noqa: E402


CALL = {
    "portal": "freehire-search",
    "query": "AI Engineer",
    "scope": "exact",
    "place": "EG",
    "place_name": "Egypt",
    "rung": "EG",
    "flags": {
        "country": "EG",
        "remote": "remote",
        "jobage": "14",
        "limit": "20",
        "seniority": "junior",
        "category": "ml_ai",
    },
    "argv": ["search", "--country", "EG"],
}


class RelaxationTests(unittest.TestCase):
    """Dropping a facet widens the search, and only the facet."""

    def test_the_named_facet_is_dropped(self) -> None:
        relaxed = relaxed_call(CALL, ("category",))
        self.assertNotIn("category", relaxed["flags"])
        self.assertIn("seniority", relaxed["flags"])

    def test_the_geography_and_the_query_stay(self) -> None:
        relaxed = relaxed_call(CALL, ("category", "seniority"))
        self.assertEqual(relaxed["flags"]["country"], "EG")
        self.assertEqual(relaxed["query"], "AI Engineer")
        self.assertIn("--country", relaxed["argv"])
        self.assertIn("AI Engineer", relaxed["argv"])

    def test_the_argv_matches_the_flags(self) -> None:
        relaxed = relaxed_call(CALL, ("category",))
        self.assertNotIn("--category", relaxed["argv"])
        self.assertNotIn("ml_ai", relaxed["argv"])

    def test_nothing_to_drop_gives_nothing(self) -> None:
        self.assertIsNone(relaxed_call(CALL, ("industry",)))


class MarketTests(unittest.TestCase):
    """A posting from the wrong market is not a hit."""

    def test_a_posting_in_the_country_is_kept(self) -> None:
        hit = {"location": "Cairo, Egypt"}
        self.assertTrue(in_market(hit, CALL))

    def test_a_posting_from_another_country_is_dropped(self) -> None:
        hit = {"location": "Munich, Germany"}
        self.assertFalse(in_market(hit, CALL))

    def test_a_posting_with_no_country_is_kept(self) -> None:
        hit = {"location": "Cairo"}
        self.assertTrue(in_market(hit, CALL))

    def test_a_widened_search_is_not_checked(self) -> None:
        """The widening is already reported; the scope note explains it."""
        call = dict(CALL, scope="wider")
        self.assertTrue(in_market({"location": "Munich, Germany"}, call))

    def test_a_region_target_is_not_checked(self) -> None:
        call = dict(CALL, place="mena")
        self.assertTrue(in_market({"location": "Munich, Germany"}, call))


if __name__ == "__main__":
    unittest.main()
