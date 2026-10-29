"""Tests for the market check: does a posting's own location agree?

Portals leak. A posting from the wrong market looks exactly like a hit, and
in a small market it can outrank the posting the user asked for.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from market import countries_named, matches_country, out_of_market  # noqa: E402
from places import load_catalogue  # noqa: E402


class CountriesNamedTests(unittest.TestCase):
    """Which countries a location string names."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()

    def named(self, location: str) -> set[str]:
        return countries_named(location, self.catalogue)

    def test_a_country_name_is_recognised(self) -> None:
        self.assertEqual(self.named("Cairo, Egypt"), {"EG"})

    def test_a_country_code_is_recognised(self) -> None:
        self.assertEqual(self.named("Cairo, EG"), {"EG"})

    def test_a_city_alone_names_no_country(self) -> None:
        """A city is not a contradiction, so it must not be judged."""
        self.assertEqual(self.named("Cairo"), set())

    def test_a_word_inside_a_word_is_not_a_country(self) -> None:
        """Nigeria names Nigeria and not Niger."""
        named = self.named("Lagos, Nigeria")
        self.assertIn("NG", named)
        self.assertNotIn("NE", named)

    def test_a_common_word_is_not_a_country(self) -> None:
        """"in" is a word, not India."""
        self.assertNotIn("IN", self.named("Jobs in Berlin"))

    def test_several_countries_can_be_named(self) -> None:
        named = self.named("Remote, Spain; Brazil; Egypt")
        self.assertEqual(named, {"ES", "BR", "EG"})

    def test_an_empty_location_names_nothing(self) -> None:
        self.assertEqual(self.named(""), set())


class MatchTests(unittest.TestCase):
    """Whether a posting belongs to the market that was searched."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()

    def test_a_posting_in_the_country_matches(self) -> None:
        self.assertTrue(matches_country("Cairo, Egypt", "EG", self.catalogue))

    def test_a_posting_in_another_country_does_not(self) -> None:
        self.assertFalse(matches_country("Munich, Germany", "EG", self.catalogue))
        self.assertTrue(out_of_market("Munich, Germany", "EG", self.catalogue))

    def test_a_posting_with_no_country_is_kept(self) -> None:
        self.assertTrue(matches_country("Cairo", "EG", self.catalogue))
        self.assertFalse(out_of_market("Cairo", "EG", self.catalogue))

    def test_a_posting_naming_two_countries_one_of_them_the_target_is_kept(self) -> None:
        location = "Remote, Spain; Brazil; Indonesia; Portugal; India; Bangladesh; Egypt"
        self.assertTrue(matches_country(location, "EG", self.catalogue))


if __name__ == "__main__":
    unittest.main()
