"""Tests for the place catalogue and the free-text resolver.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from places import Catalogue, load_catalogue, normalise  # noqa: E402


class CatalogueTests(unittest.TestCase):
    """The catalogue's own data must be sound."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()

    def test_every_place_has_a_name(self) -> None:
        for key, place in self.catalogue.places.items():
            self.assertTrue(place.name, f"{key} has no name")

    def test_every_parent_exists(self) -> None:
        for key, place in self.catalogue.places.items():
            if place.parent is None:
                continue
            self.assertIn(place.parent, self.catalogue.places, f"{key} points at a missing parent")

    def test_the_parent_chain_terminates(self) -> None:
        for key in self.catalogue.places:
            chain = self.catalogue.parent_chain(key)
            self.assertLess(len(chain), 20, f"{key} has a parent cycle")

    def test_there_is_an_anywhere_floor(self) -> None:
        self.assertIsNotNone(self.catalogue.get("anywhere"))

    def test_no_two_places_share_an_alias(self) -> None:
        owners: dict[str, str] = {}
        for key, place in self.catalogue.places.items():
            for label in [place.name] + place.aliases:
                folded = normalise(label)
                if not folded:
                    continue
                other = owners.get(folded)
                # The same place naming itself twice is harmless. Two
                # different places claiming one label is not: one of them
                # becomes unresolvable.
                self.assertTrue(
                    other is None or other == key,
                    f"'{label}' is claimed by both {other} and {key}",
                )
                owners[folded] = key

    def test_every_country_has_a_parent_region(self) -> None:
        for key, place in self.catalogue.places.items():
            if place.kind != "country":
                continue
            self.assertIsNotNone(place.parent, f"{key} has no parent region")

    def test_country_keys_are_iso_alpha_two(self) -> None:
        for key, place in self.catalogue.places.items():
            if place.kind != "country":
                continue
            self.assertEqual(len(key), 2, f"{key} is not an ISO alpha-2 code")
            self.assertTrue(key.isalpha(), f"{key} is not an ISO alpha-2 code")

    def test_no_value_is_a_boolean(self) -> None:
        """A YAML `NO` becomes False, which would be sent as a flag value."""
        for key, place in self.catalogue.places.items():
            for portal, values in (place.values or {}).items():
                for canonical, value in values.items():
                    self.assertNotIsInstance(
                        value,
                        bool,
                        f"{key}/{portal}/{canonical} parsed as a boolean",
                    )

    def test_values_only_use_declared_filters(self) -> None:
        from portal_map import load_portals

        portals = load_portals()
        # `scope` and `note` describe the value, they are not filters.
        metadata = {"scope", "note"}
        for key, place in self.catalogue.places.items():
            for portal, values in (place.values or {}).items():
                self.assertIn(portal, portals, f"{key} names an unknown portal {portal}")
                filters = (portals[portal] or {}).get("filters") or {}
                for canonical in values:
                    if canonical in metadata:
                        continue
                    self.assertIn(
                        canonical,
                        filters,
                        f"{key}/{portal} uses {canonical}, which the portal does not have",
                    )

    def test_no_value_is_a_mapping(self) -> None:
        """An unquoted comma in YAML turns a value into a mapping.

        `{location: Amman, Jordan}` parses as two keys, and the second one -
        "Jordan" - then looks like a filter name the portal does not have.
        """
        for key, place in self.catalogue.places.items():
            for portal, values in (place.values or {}).items():
                for canonical, value in values.items():
                    self.assertNotIsInstance(
                        value,
                        dict,
                        f"{key}/{portal}/{canonical} parsed as a mapping - quote the value",
                    )
                    self.assertIsInstance(
                        value,
                        (str, list),
                        f"{key}/{portal}/{canonical} is neither a string nor a list",
                    )

    def test_every_portal_can_reach_every_place(self) -> None:
        """No place is left without a target on a portal.

        The ladder ends at "anywhere", so every portal can express every place
        one way or another. A place that cannot be reached at all would be a
        silent gap.
        """
        from portal_map import build_targets, load_portals

        portals = load_portals()
        for key, place in self.catalogue.places.items():
            targets, skips = build_targets(self.catalogue, portals, place)
            self.assertTrue(targets, f"{key} produced no target")
            self.assertEqual(skips, [], f"{key} was skipped: {skips}")


class ResolveTests(unittest.TestCase):
    """What people type has to land on the right place."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()

    def resolve(self, text: str):
        return self.catalogue.resolve(text)

    def test_a_country_name_resolves(self) -> None:
        resolution = self.resolve("Germany")
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.place.key, "DE")

    def test_a_catalogue_key_resolves(self) -> None:
        self.assertEqual(self.resolve("EG").place.key, "EG")

    def test_a_region_alias_resolves(self) -> None:
        self.assertEqual(self.resolve("the Gulf").place.key, "mena")
        self.assertEqual(self.resolve("MENA").place.key, "mena")
        self.assertEqual(self.resolve("EU").place.key, "european_union")

    def test_accents_do_not_matter(self) -> None:
        self.assertEqual(self.resolve("Türkiye").place.key, "TR")
        self.assertEqual(self.resolve("Turkiye").place.key, "TR")

    def test_a_city_falls_back_to_its_country(self) -> None:
        resolution = self.resolve("Cairo, Egypt")
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.place.key, "EG")

    def test_a_sentence_resolves_to_the_place_in_it(self) -> None:
        self.assertEqual(self.resolve("jobs in the Netherlands").place.key, "NL")

    def test_remote_alone_means_nowhere_in_particular(self) -> None:
        resolution = self.resolve("Remote")
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.place.key, "anywhere")

    def test_remote_with_a_place_keeps_the_place(self) -> None:
        resolution = self.resolve("remote jobs in Europe")
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.place.key, "europe")
        self.assertTrue(resolution.remote)

    def test_an_unknown_place_is_not_guessed(self) -> None:
        resolution = self.resolve("atlantis")
        self.assertFalse(resolution.resolved)
        self.assertTrue(resolution.candidates)
        self.assertIn("ask the user", resolution.note.lower())

    def test_an_exact_match_beats_a_fragment(self) -> None:
        resolution = self.resolve("guinea")
        self.assertTrue(resolution.resolved)
        self.assertEqual(resolution.place.key, "GN")

    def test_an_ambiguous_fragment_is_not_guessed(self) -> None:
        resolution = self.resolve("guine")
        self.assertFalse(resolution.resolved)
        self.assertGreater(len(resolution.candidates), 1)

    def test_empty_text_is_unresolved(self) -> None:
        self.assertFalse(self.resolve("").resolved)


if __name__ == "__main__":
    unittest.main()
