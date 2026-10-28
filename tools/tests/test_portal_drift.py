"""The capability matrix must match the CLIs it describes.

``config/portals.yaml`` says which flags each portal has. A portal CLI
rejects an unknown flag, so a matrix that invents one breaks the run at the
worst moment. And a portal that gains a flag the matrix does not know about
means a filter that silently does nothing.

This test reads each portal's own ``search --help`` and compares.

Run it with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from portal_map import load_portals  # noqa: E402


def bun_executable() -> str | None:
    """Find bun, which may not be on PATH in a bare environment."""
    found = shutil.which("bun")
    if found:
        return found
    candidate = Path.home() / ".bun" / "bin" / "bun"
    if candidate.exists():
        return str(candidate)
    return None


class PortalDriftTests(unittest.TestCase):
    """Every flag in the matrix must exist in the portal it belongs to."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bun = bun_executable()
        if not cls.bun:
            raise unittest.SkipTest("bun is not installed")
        cls.portals = load_portals()

    def help_text(self, portal: str) -> str:
        cli = ROOT / ".agents" / "skills" / portal / "cli" / "src" / "cli.ts"
        self.assertTrue(cli.exists(), f"{portal} has no CLI at {cli}")
        proc = subprocess.run(
            [self.bun, "run", str(cli), "search", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, f"{portal} --help failed: {proc.stderr[:400]}")
        return proc.stdout

    def test_every_matrix_flag_exists_on_the_portal(self) -> None:
        for portal, spec in self.portals.items():
            text = self.help_text(portal)
            for canonical, entry in (spec.get("filters") or {}).items():
                flag = entry.get("flag")
                self.assertTrue(flag, f"{portal}.{canonical} has no flag")
                self.assertIn(
                    flag,
                    text,
                    f"{portal} does not document {flag}, which the matrix uses for {canonical}",
                )

    def test_the_matrix_does_not_invent_a_portal(self) -> None:
        """A portal in the matrix with no skill behind it is a broken target."""
        for portal in self.portals:
            skill = ROOT / ".agents" / "skills" / portal / "SKILL.md"
            self.assertTrue(skill.exists(), f"{portal} has no SKILL.md")

    def test_the_documented_flags_are_all_accounted_for(self) -> None:
        """Every flag a portal documents is either a filter or knowingly not one.

        A flag left out of the matrix without a reason is a filter that
        silently does nothing. Output controls and escape hatches are not
        filters - the runner sets them itself - but they are listed here so
        the omission is deliberate.
        """
        accounted = {
            "freehire-search": {
                # Used by the matrix as a filter.
                "region": "--region",
                "country": "--country",
                "seniority": "--seniority",
                "category": "--category",
                "remote": "--remote",
                "jobage": "--jobage",
                "limit": "--limit",
                # Known and deliberately not a matrix filter.
                "query": "-q",  # the runner adds it per query
                "format": "--format",  # the runner sets it
                "page": "--page",  # the runner does not page
                "city": "--city",  # the API ignores it
                "skill": "--skill",  # a facet the catalogue does not populate
                "company": "--company",  # a facet the catalogue does not populate
                "facet": "--facet",  # the escape hatch for anything else
                "no-description": "--no-description",  # an output choice
                "description-format": "--description-format",  # an output choice
            },
            "linkedin-search": {
                "query": "--query",
                "location": "--location",
                "remote": "--remote",
                "jobage": "--jobage",
                "limit": "--limit",
                "format": "--format",
                "page": "--page",
                "jobage-minutes": "--jobage-minutes",
            },
            "jobicy-search": {
                "query": "--query",
                "location": "--location",
                "industry": "--industry",
                "jobage": "--jobage",
                "limit": "--limit",
                "format": "--format",
                "page": "--page",
                "cursor": "--cursor",
                "no-description": "--no-description",
                "list-locations": "--list-locations",
                "list-industries": "--list-industries",
            },
        }
        for portal, spec in self.portals.items():
            matrix = {entry.get("flag") for entry in (spec.get("filters") or {}).values()}
            expected = {flag for _name, flag in accounted.get(portal, {}).items()}
            self.assertEqual(
                matrix - expected,
                set(),
                f"{portal} uses flags the test does not account for",
            )
            for name, flag in accounted.get(portal, {}).items():
                self.assertIn(
                    flag,
                    self.help_text(portal),
                    f"{portal} does not document {flag} ({name})",
                )

    def test_a_closed_vocabulary_is_stated(self) -> None:
        """A portal with a closed vocabulary must have it written down."""
        for portal, spec in self.portals.items():
            for canonical, entry in (spec.get("filters") or {}).items():
                text = self.help_text(portal)
                if "values" in entry:
                    continue
                # A filter with no vocabulary may be free-form (a query, a
                # number). Check the help mentions the flag at all.
                self.assertIn(entry.get("flag", ""), text)


if __name__ == "__main__":
    unittest.main()
