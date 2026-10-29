"""Tests for the search contract.

The contract is what the run consumes. Two things in it were wrong and both
of them emptied a run:

* An empty ``preferences.locations`` produced no portal call at all.
* The location terms were built from ``region``, ``city`` and ``country``,
  while the entries are written with ``place`` - so every location term was
  empty and no posting got credit for being in the place that was asked for.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import relevance  # noqa: E402
from profile_query import build_contract, build_filters  # noqa: E402


PERSONA = {
    "persona": "ai-llm-rag",
    "title": "AI / ML Engineer",
    "target_roles": [
        {"title": "Applied AI Engineer", "priority": 1},
        {"title": "RAG Engineer", "priority": 2},
    ],
    "skills": [
        {"name": "Python", "weight": "primary"},
        {"name": "Retrieval-Augmented Generation (RAG)", "weight": "primary"},
    ],
    "identity": {"location": {"value": "Cairo, Egypt"}},
}


def inputs_with(locations, location="Cairo, Egypt") -> dict:
    return {
        "identity": {"location": location},
        "preferences": {"locations": locations},
        "search": {"portals": {}},
    }


class DefaultLocationTests(unittest.TestCase):
    """A user who named no place still gets a search."""

    def test_no_locations_still_produce_targets(self) -> None:
        contract = build_contract(PERSONA, inputs_with([]))
        self.assertTrue(contract["portal_targets"])
        self.assertTrue(contract["locations_defaulted"])

    def test_the_default_is_remote_anywhere(self) -> None:
        contract = build_contract(PERSONA, inputs_with([]))
        places = {target["place"] for target in contract["portal_targets"]}
        self.assertEqual(places, {"anywhere"})

    def test_a_given_list_is_not_defaulted(self) -> None:
        contract = build_contract(PERSONA, inputs_with([{"place": "Egypt", "mode": "remote"}]))
        self.assertFalse(contract["locations_defaulted"])


class FilterTests(unittest.TestCase):
    """The filters the scorer is handed."""

    def test_the_home_place_is_in_the_contract(self) -> None:
        filters = build_filters(inputs_with([]), PERSONA)
        self.assertEqual(filters["home_place"]["country"], "EG")

    def test_the_servable_places_are_in_the_contract(self) -> None:
        filters = build_filters(
            inputs_with([{"place": "Egypt", "mode": "onsite_remote_hybrid"}]), PERSONA
        )
        egypt = [entry for entry in filters["servable_places"] if entry["place"] == "EG"]
        self.assertEqual(len(egypt), 1)
        self.assertTrue(egypt[0]["home"])

    def test_a_resolved_location_carries_its_key(self) -> None:
        filters = build_filters(inputs_with([{"place": "Egypt", "mode": "remote"}]), PERSONA)
        self.assertEqual(filters["locations"][0]["place_key"], "EG")
        self.assertEqual(filters["locations"][0]["place_name"], "Egypt")


class RelevanceLocationTests(unittest.TestCase):
    """The ordering has to know where a posting is."""

    def terms(self, locations):
        return relevance.build_terms(PERSONA, inputs_with(locations))

    def test_a_place_key_produces_location_terms(self) -> None:
        """The bug: the terms were read from keys the entries never used."""
        terms = self.terms([{"place": "Egypt", "mode": "remote"}])
        self.assertTrue(terms["locations"])
        self.assertIn("egypt", [phrase for phrase, _ in terms["locations"]])

    def test_the_place_is_servable(self) -> None:
        terms = self.terms([{"place": "Egypt", "mode": "remote"}])
        self.assertIn("EG", terms["servable"])

    def test_a_region_names_its_countries(self) -> None:
        terms = self.terms([{"place": "MENA", "mode": "remote"}])
        phrases = [phrase for phrase, _ in terms["locations"]]
        self.assertIn("egypt", phrases)
        self.assertIn("saudi arabia", phrases)

    def test_the_home_country_is_always_servable(self) -> None:
        terms = self.terms([{"place": "Germany", "mode": "remote"}])
        self.assertIn("EG", terms["servable"])

    def test_a_posting_in_the_searched_place_scores_above_one_elsewhere(self) -> None:
        terms = self.terms([{"place": "Egypt", "mode": "remote"}])
        here = {
            "title": "AI Engineer",
            "location": "Cairo, Egypt",
            "target_place": "EG",
            "target_scope": "exact",
        }
        elsewhere = {
            "title": "AI Engineer",
            "location": "Munich, Germany",
            "target_place": "DE",
            "target_scope": "exact",
        }
        self.assertGreater(relevance.score(here, terms)[0], relevance.score(elsewhere, terms)[0])

    def test_a_widened_search_carries_less_weight(self) -> None:
        terms = self.terms([{"place": "MENA", "mode": "remote"}])
        exact = {
            "title": "AI Engineer",
            "location": "Remote - Multiple Locations",
            "target_place": "mena",
            "target_scope": "exact",
        }
        wider = dict(exact, target_scope="wider")
        self.assertGreater(relevance.score(exact, terms)[0], relevance.score(wider, terms)[0])

    def test_a_location_counts_once(self) -> None:
        """The location string and the target say the same thing."""
        terms = self.terms([{"place": "Egypt", "mode": "remote"}])
        here = {
            "title": "AI Engineer",
            "location": "Cairo, Egypt",
            "target_place": "EG",
            "target_scope": "exact",
        }
        elsewhere = dict(here, location="Munich, Germany", target_place="DE")

        score, reasons = relevance.score(here, terms)
        location_reasons = [reason for reason in reasons if "location" in reason or "found in" in reason]
        self.assertEqual(len(location_reasons), 1)
        # The home place's weight, once - not once per signal.
        self.assertEqual(score - relevance.score(elsewhere, terms)[0], 16.0)

    def test_the_home_place_outranks_a_remote_place(self) -> None:
        """A role the candidate can walk into beats the same role abroad."""
        terms = self.terms([{"place": "United States", "mode": "remote"}])
        here = {
            "title": "AI Engineer",
            "location": "Cairo, Egypt",
            "target_place": "EG",
            "target_scope": "exact",
        }
        there = {
            "title": "AI Engineer",
            "location": "Remote - Multiple Locations",
            "target_place": "US",
            "target_scope": "exact",
        }
        self.assertGreater(relevance.score(here, terms)[0], relevance.score(there, terms)[0])


if __name__ == "__main__":
    unittest.main()
