"""Tests for the query guard.

The agent may propose extra queries. The guard decides which of them are
searchable, because a query that carries a portal filter word matches
nothing while looking exactly like a good query.

The banned list is derived, not hardcoded: it comes from the user's own
``inputs.yaml`` and from the vocabularies in ``config/portals.yaml``. These
tests check that derivation as much as the rejection itself - a guard that
drifts away from the portals is worse than no guard.

Run them with:

    python3 -m unittest discover -s tools/tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from query_guard import (  # noqa: E402
    banned_terms,
    canonical,
    load_extra_query_file,
    validate_queries,
    validate_query,
)
from search_portals import load_extra_queries, merge_queries  # noqa: E402


INPUTS = {
    "preferences": {
        "seniority": {
            "include": ["junior", "entry level", "fresh graduate", "0-1 years"],
            "exclude": ["senior", "staff", "principal", "lead", "3+ years"],
        }
    },
    "filters": {
        "visa_block": ["must be a U.S. citizen", "no sponsorship"],
        "location_block": ["on-site only", "must relocate"],
    },
}

PORTALS = {
    "freehire-search": {
        "filters": {
            "seniority": {"supported": True, "values": ["junior", "middle", "senior", "staff", "principal", "lead"]},
            "remote": {"supported": True, "values": ["remote", "hybrid", "onsite"]},
        }
    },
    "linkedin-search": {
        "filters": {
            "remote": {"supported": True, "values": ["remote", "hybrid", "onsite"]},
        }
    },
}


def words_and_phrases():
    return banned_terms(INPUTS, PORTALS)


class DerivationTests(unittest.TestCase):
    """The banned list comes from the config, not from a hardcoded table."""

    def test_a_seniority_value_is_banned(self) -> None:
        words, _ = words_and_phrases()
        self.assertIn("junior", words)
        self.assertIn("senior", words)

    def test_a_portal_work_mode_is_banned(self) -> None:
        words, _ = words_and_phrases()
        self.assertIn("remote", words)
        self.assertIn("hybrid", words)
        self.assertIn("onsite", words)

    def test_a_multi_word_preference_is_a_phrase_not_a_word(self) -> None:
        """'head of' must not ban 'head' on its own."""
        words, phrases = words_and_phrases()
        self.assertIn(("entry", "level"), phrases)
        self.assertNotIn("entry", words)

    def test_a_visa_phrase_is_a_phrase(self) -> None:
        _, phrases = words_and_phrases()
        self.assertIn(("must", "be", "a", "us", "citizen"), phrases)

    def test_an_unsupported_filter_is_not_banned(self) -> None:
        """A portal that documents a filter but ignores it must not ban it."""
        portals = {
            "p": {"filters": {"seniority": {"supported": False, "values": ["intern"]}}}
        }
        words, _ = banned_terms(INPUTS, portals)
        self.assertNotIn("intern", words)

    def test_the_same_word_in_different_spelling_is_the_same_word(self) -> None:
        self.assertEqual(canonical("on-site"), canonical("onsite"))
        self.assertEqual(canonical("on site"), canonical("onsite"))
        self.assertEqual(canonical("0-1"), canonical("01"))


class RejectionTests(unittest.TestCase):
    """What the guard drops."""

    def test_a_plain_query_is_accepted(self) -> None:
        words, phrases = words_and_phrases()
        self.assertEqual(validate_query("Applied AI Engineer RAG", words, phrases), "")

    def test_a_seniority_word_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("Junior AI Engineer", words, phrases)
        self.assertIn("portal filter", reason)

    def test_a_work_mode_word_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("Remote AI Engineer", words, phrases)
        self.assertIn("portal filter", reason)

    def test_a_hyphenated_work_mode_is_rejected(self) -> None:
        """'on-site' and 'onsite' are the same filter to a portal."""
        words, phrases = words_and_phrases()
        self.assertNotEqual(validate_query("AI Engineer on-site", words, phrases), "")

    def test_a_filter_phrase_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("AI Engineer entry level", words, phrases)
        self.assertIn("filter phrase", reason)

    def test_a_visa_phrase_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("AI Engineer no sponsorship", words, phrases)
        self.assertIn("filter phrase", reason)

    def test_a_one_word_query_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("RAG", words, phrases)
        self.assertIn("fewer than", reason)

    def test_a_long_query_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("Applied AI Engineer RAG Python FastAPI ChromaDB", words, phrases)
        self.assertIn("more than", reason)

    def test_an_empty_query_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        self.assertEqual(validate_query("", words, phrases), "empty")

    def test_a_word_with_stray_punctuation_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        reason = validate_query("Applied AI Engineer (RAG)", words, phrases)
        self.assertNotEqual(reason, "")

    def test_a_tech_word_with_a_plus_is_accepted(self) -> None:
        words, phrases = words_and_phrases()
        self.assertEqual(validate_query("C++ Backend Engineer", words, phrases), "")


class CapTests(unittest.TestCase):
    """The agent may add two queries, not twenty."""

    def test_the_cap_is_enforced(self) -> None:
        words, phrases = words_and_phrases()
        entries = [
            {"query": "Applied AI Engineer RAG", "source": "a"},
            {"query": "LLM Application Engineer Python", "source": "b"},
            {"query": "RAG Engineer FastAPI", "source": "c"},
        ]
        accepted, rejected = validate_queries(entries, words, phrases, max_queries=2)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(rejected), 1)
        self.assertIn("cap", rejected[0]["reason"])

    def test_a_repeated_query_is_rejected(self) -> None:
        words, phrases = words_and_phrases()
        entries = [
            {"query": "Applied AI Engineer RAG", "source": "a"},
            {"query": "applied ai engineer rag", "source": "b"},
        ]
        accepted, rejected = validate_queries(entries, words, phrases)
        self.assertEqual(len(accepted), 1)
        self.assertIn("repeats", rejected[0]["reason"])

    def test_an_empty_list_accepts_nothing(self) -> None:
        words, phrases = words_and_phrases()
        accepted, rejected = validate_queries([], words, phrases)
        self.assertEqual(accepted, [])
        self.assertEqual(rejected, [])


class FileTests(unittest.TestCase):
    """Reading the agent's proposal file."""

    def test_a_missing_file_yields_nothing(self) -> None:
        self.assertEqual(load_extra_query_file(ROOT / "does-not-exist.json"), [])

    def test_the_documented_shape_is_read(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "added.json"
            path.write_text(
                json.dumps(
                    {"added_queries": [{"query": "Applied AI Engineer RAG", "source": "top_job"}]}
                ),
                encoding="utf-8",
            )
            entries = load_extra_query_file(path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["query"], "Applied AI Engineer RAG")
        self.assertEqual(entries[0]["source"], "top_job")

    def test_a_bare_list_is_read(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "added.json"
            path.write_text(json.dumps(["Applied AI Engineer RAG"]), encoding="utf-8")
            entries = load_extra_query_file(path)
        self.assertEqual(len(entries), 1)


class MergeTests(unittest.TestCase):
    """The extra queries join the base set without duplicating it."""

    def test_an_extra_query_is_appended(self) -> None:
        base = [{"query": "Applied AI Engineer RAG", "kind": "role+skill", "priority": 1, "source": []}]
        merged = merge_queries(base, [{"query": "LLM Engineer Python", "source": "top_job"}])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]["query"], "LLM Engineer Python")
        self.assertEqual(merged[1]["priority"], 3)

    def test_a_repeated_query_is_not_appended(self) -> None:
        base = [{"query": "Applied AI Engineer RAG", "kind": "role+skill", "priority": 1, "source": []}]
        merged = merge_queries(base, [{"query": "applied ai engineer rag", "source": "x"}])
        self.assertEqual(len(merged), 1)

    def test_a_missing_file_contributes_nothing(self) -> None:
        self.assertEqual(load_extra_queries(None), [])
        self.assertEqual(load_extra_queries(ROOT / "does-not-exist.json"), [])


if __name__ == "__main__":
    unittest.main()
