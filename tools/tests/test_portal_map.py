"""Tests for the place-to-portal ladder.

The ladder is what stops a search from quietly answering the wrong question.
Exact place, then parent region, then anywhere - and the rung it landed on is
always reported.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from places import load_catalogue  # noqa: E402
from portal_map import (  # noqa: E402
    SCOPE_EXACT,
    SCOPE_FLOOR,
    SCOPE_WIDER,
    build_targets,
    flags_to_argv,
    load_portals,
    supports_filter,
)


class LadderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = load_catalogue()
        cls.portals = load_portals()

    def targets_for(self, key: str, mode: str = "remote"):
        place = self.catalogue.get(key)
        self.assertIsNotNone(place, f"{key} is not in the catalogue")
        targets, skips = build_targets(self.catalogue, self.portals, place, mode)
        return targets, skips

    def one(self, key: str, portal: str, mode: str = "remote"):
        targets, _ = self.targets_for(key, mode)
        for target in targets:
            if target.portal == portal:
                return target
        self.fail(f"{portal} produced no target for {key}")

    # -- the exact rung ---------------------------------------------------

    def test_a_country_is_searched_exactly_where_the_portal_can(self) -> None:
        target = self.one("DE", "freehire-search")
        self.assertEqual(target.flags["country"], "DE")
        self.assertEqual(target.scope, SCOPE_EXACT)

    def test_linkedin_gets_the_place_string_not_the_code(self) -> None:
        target = self.one("DE", "linkedin-search")
        self.assertEqual(target.flags["location"], "Germany")

    def test_the_floor_is_used_only_when_nothing_else_fits(self) -> None:
        """CIS is a region freehire has and the other two do not."""
        self.assertEqual(self.one("cis", "freehire-search").scope, SCOPE_EXACT)
        self.assertEqual(self.one("cis", "linkedin-search").scope, SCOPE_FLOOR)
        self.assertEqual(self.one("cis", "jobicy-search").scope, SCOPE_FLOOR)

    def test_the_floor_carries_its_own_reason(self) -> None:
        target = self.one("cis", "linkedin-search")
        self.assertEqual(target.flags["location"], "Remote")
        self.assertEqual(target.rung, "anywhere")

    # -- the wider rung ----------------------------------------------------

    def test_a_portal_without_the_country_widens_to_the_parent(self) -> None:
        """Jobicy's taxonomy has no Egypt, so it widens to MENA's EMEA."""
        target = self.one("EG", "jobicy-search")
        self.assertEqual(target.scope, SCOPE_WIDER)
        self.assertEqual(target.rung, "mena")
        self.assertEqual(target.flags["location"], "emea")
        self.assertTrue(target.note)

    def test_a_widened_search_still_explains_itself(self) -> None:
        target = self.one("EG", "jobicy-search")
        self.assertIn("MENA", target.note)

    def test_a_declared_wider_value_is_reported_as_wider(self) -> None:
        """Jobicy's EMEA covers Europe and the Middle East, not MENA."""
        target = self.one("mena", "jobicy-search")
        self.assertEqual(target.scope, SCOPE_WIDER)

    # -- several searches for one place ------------------------------------

    def test_a_list_value_becomes_several_searches(self) -> None:
        targets, _ = self.targets_for("north_america")
        jobicy = [target for target in targets if target.portal == "jobicy-search"]
        self.assertEqual(len(jobicy), 2)
        self.assertEqual(
            sorted(target.flags["location"] for target in jobicy),
            ["canada", "usa"],
        )

    def test_a_portal_with_no_such_region_gets_several_searches(self) -> None:
        """LinkedIn has no EMEA, so EMEA is Europe, the Middle East and Africa."""
        targets, _ = self.targets_for("emea")
        linkedin = [target for target in targets if target.portal == "linkedin-search"]
        self.assertEqual(len(linkedin), 3)
        self.assertEqual(
            sorted(target.flags["location"] for target in linkedin),
            sorted(["Europe", "Middle East", "Africa"]),
        )

    # -- work mode ---------------------------------------------------------

    def test_a_single_work_mode_becomes_the_portal_filter(self) -> None:
        targets, _ = self.targets_for("EG", "onsite")
        linkedin = [target for target in targets if target.portal == "linkedin-search"]
        self.assertEqual(len(linkedin), 1)
        self.assertEqual(linkedin[0].flags["remote"], "onsite")

    def test_several_work_modes_send_no_work_mode_filter(self) -> None:
        """"Remote, hybrid or on-site" is the absence of a filter, not one.

        Sending `--remote remote,hybrid,onsite` drops every posting that
        declares no work mode, and in a market such as Egypt that is most of
        them.
        """
        targets, _ = self.targets_for("EG", "onsite_remote_hybrid")
        for portal in ("freehire-search", "linkedin-search"):
            made = [target for target in targets if target.portal == portal]
            self.assertEqual(len(made), 1, f"{portal} made {len(made)} searches")
            self.assertNotIn("remote", made[0].flags)
            self.assertEqual(made[0].work_mode, "onsite_remote_hybrid")

    def test_a_multi_work_mode_says_why_it_sent_no_filter(self) -> None:
        targets, _ = self.targets_for("EG", "remote_or_relocation")
        freehire = [target for target in targets if target.portal == "freehire-search"][0]
        self.assertIn("work-mode", freehire.note)

    def test_a_multi_work_mode_overrides_the_place_default(self) -> None:
        """"Anywhere" carries a remote filter of its own; the mode wins."""
        targets, _ = self.targets_for("anywhere", "onsite_remote_hybrid")
        for target in targets:
            self.assertNotIn("remote", target.flags)

    def test_a_single_work_mode_overrides_the_place_default(self) -> None:
        targets, _ = self.targets_for("anywhere", "hybrid")
        for target in targets:
            if target.portal == "freehire-search":
                self.assertEqual(target.flags["remote"], "hybrid")

    def test_a_portal_without_a_work_mode_filter_gets_none(self) -> None:
        target = self.one("EG", "jobicy-search")
        self.assertNotIn("remote", target.flags)

    # -- filters that do not apply -----------------------------------------

    def test_an_unsupported_filter_is_never_sent(self) -> None:
        """freehire documents --city but the API ignores it."""
        self.assertFalse(supports_filter(self.portals, "freehire-search", "city"))
        self.assertNotIn("city", flags_to_argv(self.portals, "freehire-search", {"city": "Berlin"}))

    def test_the_argv_uses_each_portal_own_flag(self) -> None:
        argv = flags_to_argv(self.portals, "freehire-search", {"country": "EG", "remote": "remote"})
        self.assertEqual(argv, ["--country", "EG", "--remote", "remote"])

        argv = flags_to_argv(self.portals, "linkedin-search", {"location": "Egypt"})
        self.assertEqual(argv, ["--location", "Egypt"])

    def test_an_empty_value_is_not_sent(self) -> None:
        self.assertEqual(flags_to_argv(self.portals, "freehire-search", {"country": ""}), [])

    # -- the category ------------------------------------------------------

    def test_the_canonical_category_is_translated_per_portal(self) -> None:
        targets, _ = build_targets(
            self.catalogue,
            self.portals,
            self.catalogue.get("DE"),
            "remote",
            extra_flags={"category": "ai_ml"},
        )
        freehire = [t for t in targets if t.portal == "freehire-search"][0]
        jobicy = [t for t in targets if t.portal == "jobicy-search"][0]
        linkedin = [t for t in targets if t.portal == "linkedin-search"][0]
        self.assertEqual(freehire.flags.get("category"), "ml_ai")
        self.assertEqual(jobicy.flags.get("industry"), "data-science")
        self.assertNotIn("category", linkedin.flags)


if __name__ == "__main__":
    unittest.main()
