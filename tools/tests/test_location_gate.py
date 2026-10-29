"""Tests for the location gate: where the candidate lives, and where they can serve.

The gate is what stops a search for "roles in Egypt" from coming back with
nothing because the candidate is in Egypt. Being in a place is not a reason to
be gated out of it.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from location_gate import (  # noqa: E402
    DEFAULT_LOCATIONS,
    home_place,
    location_entries,
    names_home,
    servable_places,
)
from places import load_catalogue  # noqa: E402


def inputs_with(locations, location="Cairo, Egypt") -> dict:
    """Build the smallest inputs document the gate reads."""
    return {
        "identity": {"location": location},
        "preferences": {"locations": locations},
    }


class DefaultTests(unittest.TestCase):
    """An empty list is a search, not a hole in one."""

    def test_no_locations_means_remote_anywhere(self) -> None:
        entries, defaulted = location_entries({})
        self.assertTrue(defaulted)
        self.assertEqual(entries, DEFAULT_LOCATIONS)
        self.assertEqual(entries[0]["place"], "anywhere")
        self.assertEqual(entries[0]["mode"], "remote")

    def test_a_given_list_is_not_defaulted(self) -> None:
        entries, defaulted = location_entries(
            inputs_with([{"place": "Egypt", "mode": "remote"}])
        )
        self.assertFalse(defaulted)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["place"], "Egypt")


class HomePlaceTests(unittest.TestCase):
    """Where the candidate lives is a fact, not a preference."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()

    def test_a_city_and_country_resolves_to_the_country(self) -> None:
        home = home_place(inputs_with([]), {}, self.catalogue)
        self.assertEqual(home["place"], "EG")
        self.assertEqual(home["country"], "EG")
        self.assertEqual(home["city"], "Cairo")

    def test_the_persona_can_supply_the_home_place(self) -> None:
        persona = {"identity": {"location": {"value": "Cairo, Egypt"}}}
        home = home_place({}, persona, self.catalogue)
        self.assertEqual(home["country"], "EG")

    def test_no_location_means_no_home_place(self) -> None:
        self.assertIsNone(home_place({"identity": {"location": ""}}, {}, self.catalogue))

    def test_an_unknown_home_place_is_not_guessed(self) -> None:
        home = home_place(inputs_with([], location="Atlantis"), {}, self.catalogue)
        self.assertIsNone(home)


class ServablePlaceTests(unittest.TestCase):
    """The places the candidate can serve, and what each one carries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()

    def test_the_home_place_is_marked_as_such(self) -> None:
        entries = servable_places(
            inputs_with([{"place": "Egypt", "mode": "onsite_remote_hybrid"}]),
            {},
            self.catalogue,
        )
        egypt = [entry for entry in entries if entry["place"] == "EG"]
        self.assertEqual(len(egypt), 1)
        self.assertTrue(egypt[0]["home"])

    def test_the_home_place_is_added_when_it_is_not_listed(self) -> None:
        entries = servable_places(
            inputs_with([{"place": "Germany", "mode": "remote"}]),
            {},
            self.catalogue,
        )
        home = [entry for entry in entries if entry["home"]]
        self.assertEqual(len(home), 1)
        self.assertEqual(home[0]["place"], "EG")

    def test_a_region_names_the_countries_it_covers(self) -> None:
        entries = servable_places(
            inputs_with([{"place": "MENA", "mode": "remote"}]),
            {},
            self.catalogue,
        )
        mena = [entry for entry in entries if entry["place"] == "mena"][0]
        self.assertIn("EG", mena["countries"])
        self.assertIn("SA", mena["countries"])
        self.assertIn("AE", mena["countries"])

    def test_the_european_union_names_its_members(self) -> None:
        """The hierarchy cannot say this one, so the catalogue does."""
        entries = servable_places(
            inputs_with([{"place": "European Union", "mode": "remote"}]),
            {},
            self.catalogue,
        )
        eu = [entry for entry in entries if entry["place"] == "european_union"][0]
        self.assertIn("DE", eu["countries"])
        self.assertIn("FR", eu["countries"])
        self.assertNotIn("GB", eu["countries"])

    def test_a_country_covers_only_itself(self) -> None:
        entries = servable_places(
            inputs_with([{"place": "Egypt", "mode": "remote"}]),
            {},
            self.catalogue,
        )
        egypt = [entry for entry in entries if entry["place"] == "EG"][0]
        self.assertEqual(egypt["countries"], ["EG"])

    def test_the_conditions_come_through(self) -> None:
        entries = servable_places(
            inputs_with(
                [
                    {
                        "place": "United States",
                        "mode": "remote",
                        "requires_sponsorship": True,
                        "remote_from_home": "conditional",
                    }
                ]
            ),
            {},
            self.catalogue,
        )
        us = [entry for entry in entries if entry["place"] == "US"][0]
        self.assertTrue(us["requires_sponsorship"])
        self.assertEqual(us["remote_from_home"], "conditional")


class NamesHomeTests(unittest.TestCase):
    """Recognising a posting that is in the candidate's own place."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()
        cls.home = home_place(inputs_with([]), {}, cls.catalogue)

    def test_a_posting_in_the_home_country_is_recognised(self) -> None:
        self.assertTrue(names_home("Cairo, Cairo, Egypt", self.home, self.catalogue))

    def test_a_posting_in_the_home_city_is_recognised(self) -> None:
        """A city with no country named is still the candidate's city."""
        self.assertTrue(names_home("Cairo", self.home, self.catalogue))

    def test_a_posting_elsewhere_is_not(self) -> None:
        self.assertFalse(names_home("Munich, Germany", self.home, self.catalogue))

    def test_no_home_place_means_nothing_matches(self) -> None:
        self.assertFalse(names_home("Cairo, Egypt", None, self.catalogue))


if __name__ == "__main__":
    unittest.main()
