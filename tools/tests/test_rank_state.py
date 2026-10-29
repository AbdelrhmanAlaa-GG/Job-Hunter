"""Tests for the home-place rule in the ranking state.

A posting in the place the candidate already lives in is not a location
failure. The scorer judges the posting's own wording; the tool holds the
deterministic fact underneath that judgement and will not let a home-place
posting be vetoed on location grounds.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import rank_state  # noqa: E402


class Args:
    """The bits of the command line the apply step reads."""

    def __init__(self, state: Path, results: Path, today, dry_run: bool = True) -> None:
        self.state = state
        self.results = results
        self.today = today
        self.dry_run = dry_run
        self.persona = None
        self.now = rank_state.datetime(2026, 1, 1, tzinfo=rank_state.timezone.utc)


def entry(**overrides) -> dict:
    base = {
        "title": "AI Engineer",
        "company": "Example",
        "url": "https://example.invalid/job",
        "location": "Cairo, Egypt",
        "status": "new",
        "portal": "freehire-search",
    }
    base.update(overrides)
    return base


def result(**overrides) -> dict:
    base = {
        "key": "example-example-ai-engineer",
        "status": "scored",
        "scores": {"technical": 70, "experience": 60, "behavioral": 60, "career": 60},
        "location_verdict": "FAIL",
        "language_gate": "PASS",
    }
    base.update(overrides)
    return base


class HomePlaceOverrideTests(unittest.TestCase):
    """A FAIL on a home-place posting is downgraded, not vetoed."""

    HOME = {"text": "Cairo, Egypt", "place": "EG", "name": "Egypt", "kind": "country", "country": "EG", "city": "Cairo"}

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "seen_jobs.json"
        self.results = Path(self.temp.name) / "results.json"
        self.state.write_text(
            json.dumps({"seen": {"example-example-ai-engineer": entry()}}),
            encoding="utf-8",
        )
        self.results.write_text(json.dumps([result()]), encoding="utf-8")
        # The home place comes from the user's own inputs, which are not in
        # the repository. The rule is what is under test, not the address.
        self.original = rank_state.home_place_for
        rank_state.home_place_for = lambda persona: self.HOME

    def tearDown(self) -> None:
        rank_state.home_place_for = self.original
        self.temp.cleanup()

    def apply(self, results: list[dict]) -> dict:
        self.results.write_text(json.dumps(results), encoding="utf-8")
        args = Args(self.state, self.results, rank_state.date(2026, 1, 1))
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rank_state.cmd_apply(args)
        return json.loads(buffer.getvalue())

    def test_a_home_place_failure_is_downgraded(self) -> None:
        out = self.apply([result()])
        self.assertEqual(len(out["location_overrides"]), 1)
        self.assertEqual(out["location_overrides"][0]["from"], "FAIL")
        self.assertEqual(out["location_overrides"][0]["to"], "FLAG")
        self.assertEqual(len(out["vetoed"]), 0)
        self.assertEqual(len(out["ranked"]), 1)

    def test_the_override_is_reported_with_the_reason(self) -> None:
        out = self.apply([result()])
        self.assertIn("home", out["location_overrides"][0]["reason"].lower())

    def test_a_failure_elsewhere_is_left_alone(self) -> None:
        self.state.write_text(
            json.dumps(
                {"seen": {"example-example-ai-engineer": entry(location="Munich, Germany")}}
            ),
            encoding="utf-8",
        )
        out = self.apply([result()])
        self.assertEqual(out["location_overrides"], [])
        self.assertEqual(len(out["vetoed"]), 1)


if __name__ == "__main__":
    unittest.main()
