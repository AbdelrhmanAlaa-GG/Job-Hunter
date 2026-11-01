#!/usr/bin/env python3
"""Validate the search queries an agent proposes, before a portal sees them.

A query is keywords only: a role plus the signature skills the candidate
actually has. Seniority, work mode, geography and recency are portal flags -
the portals filter on them, so a query that carries them matches nothing. A
model that has read a run's postings will reach for those words anyway, and
"Applied AI Engineer junior remote" returns zero hits while looking exactly
like a good query.

This module is the guard. It keeps the queries that are well formed and
reports the ones it dropped, with the reason.

The banned terms are not hardcoded here. They come from two places, both of
which the user and the project already own:

    profiles/inputs.yaml     the user's own seniority preferences and the
                             visa and location blocks
    config/portals.yaml      the vocabularies the portals filter with

so a change to either is a change here too, and the guard can never drift
away from what the portals actually accept.

Usage:
    python3 tools/query_guard.py --persona ai-llm-rag \\
        --in profiles/ai-llm-rag/state/scratch/added_queries.json \\
        --out profiles/ai-llm-rag/state/scratch/validated_queries.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import ROOT, persona_yaml, profile_inputs_path  # noqa: E402

# How many extra queries a run may add on top of the base set.
DEFAULT_MAX_QUERIES = 2

# A query is a handful of keywords. Fewer than two is a bare role, which the
# base set already carries; more than four is a sentence, and a portal that
# matches on the whole string finds nothing.
MIN_WORDS = 2
MAX_WORDS = 4

# What a query word may contain. The set is small on purpose: a query is
# typed into a search box, not a sentence.
ALLOWED_WORD = re.compile(r"^[A-Za-z0-9+#./&'-]+$")
HAS_LETTER = re.compile(r"[A-Za-z]")

# Terms that are never a job title keyword and always mean a constraint. The
# user's inputs.yaml carries most of these already; the ones below are the
# ones no posting is ever titled after, so they are worth banning whether or
# not the user wrote them down.
EXTRA_WORD_BANS = (
    "visa",
    "sponsor",
    "sponsorship",
    "citizen",
    "citizenship",
    "relocation",
    "relocate",
    "clearance",
    "permit",
    "authorization",
)


def load_yaml(path: Path) -> dict:
    """Load a YAML document, returning an empty dict when it is absent."""
    try:
        import yaml
    except ImportError:
        return {}
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a broken file must not stop a run
        return {}
    return data if isinstance(data, dict) else {}


def canonical(value: str) -> str:
    """Return a token with its separators removed, for comparison.

    "on-site", "on site" and "onsite" are the same filter to a portal, and a
    query that carries any of them has to be dropped. So does "0-1 years",
    which matches "0-1" only after the hyphen is removed.
    """
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def banned_terms(inputs: dict, portals: dict) -> tuple[set[str], list[tuple[str, ...]]]:
    """Return the single-word bans and the phrase bans.

    A single-word ban is a token that must not appear as a query word. A
    phrase ban is a sequence of tokens that must not appear in order, so
    "head of" is caught without banning "head" on its own.
    """
    words: set[str] = set()
    phrases: list[tuple[str, ...]] = []

    def add(term: object) -> None:
        text = " ".join(str(term or "").split()).lower()
        if not text:
            return
        parts = text.split()
        if len(parts) == 1:
            token = canonical(parts[0])
            if token:
                words.add(token)
            return
        tokens = tuple(canonical(part) for part in parts)
        if all(tokens) and tokens not in phrases:
            phrases.append(tokens)

    seniority = ((inputs.get("preferences") or {}).get("seniority") or {})
    for key in ("include", "exclude"):
        for term in seniority.get(key) or []:
            add(term)

    filters = inputs.get("filters") or {}
    for key in ("visa_block", "location_block"):
        for term in filters.get(key) or []:
            add(term)

    for spec in (portals or {}).values():
        spec = spec or {}
        for canonical_name in ("seniority", "remote"):
            entry = (spec.get("filters") or {}).get(canonical_name) or {}
            if entry.get("supported") is False:
                continue
            for value in entry.get("values") or []:
                add(value)

    for term in EXTRA_WORD_BANS:
        add(term)

    return words, phrases


def validate_query(text: object, words: set[str], phrases: list[tuple[str, ...]]) -> str:
    """Return an empty string when the query is acceptable, else the reason.

    The reason is a short phrase meant for a run summary, not a stack trace.
    """
    query = " ".join(str(text or "").split())
    if not query:
        return "empty"

    parts = query.split(" ")
    if len(parts) < MIN_WORDS:
        return f"fewer than {MIN_WORDS} keywords"
    if len(parts) > MAX_WORDS:
        return f"more than {MAX_WORDS} keywords"

    tokens = [canonical(part) for part in parts]
    for phrase in phrases:
        width = len(phrase)
        for index in range(len(tokens) - width + 1):
            if tuple(tokens[index : index + width]) == phrase:
                return "carries a filter phrase"

    for part, token in zip(parts, tokens):
        if not ALLOWED_WORD.match(part):
            return f"'{part}' has characters a query cannot carry"
        if not HAS_LETTER.search(part):
            return f"'{part}' carries no letters"
        if token in words:
            return f"'{part}' is a portal filter, not a keyword"

    return ""


def load_extra_query_file(path: Path) -> list[dict]:
    """Read the proposed queries from a JSON file.

    Accepts a bare list or {"added_queries": [...]}. A file that is missing,
    unreadable or not JSON yields nothing: the base queries are always
    enough, so a broken proposal file must never stop a run.
    """
    if not path or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("added_queries") or []
    if not isinstance(data, list):
        return []

    entries: list[dict] = []
    for item in data:
        if isinstance(item, str):
            entries.append({"query": item, "source": ""})
        elif isinstance(item, dict) and item.get("query"):
            entries.append(
                {"query": str(item["query"]), "source": str(item.get("source") or "")}
            )
    return entries


def validate_queries(
    entries: list[dict],
    words: set[str],
    phrases: list[tuple[str, ...]],
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> tuple[list[dict], list[dict]]:
    """Return (accepted, rejected) for a list of proposed queries.

    Accepted entries keep their source. Rejected entries carry the reason
    they were dropped, so a run can say what was thrown away and why.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for entry in entries:
        text = str(entry.get("query") or "").strip()
        source = str(entry.get("source") or "")
        reason = validate_query(text, words, phrases)
        if reason:
            rejected.append({"query": text, "reason": reason})
            continue
        key = text.lower()
        if key in seen:
            rejected.append({"query": text, "reason": "repeats an earlier query"})
            continue
        if len(accepted) >= max_queries:
            rejected.append({"query": text, "reason": f"over the cap of {max_queries} queries"})
            continue
        seen.add(key)
        accepted.append({"query": text, "source": source})

    return accepted, rejected


def base_query_texts(persona_slug: str) -> list[str]:
    """Return the base queries, so a proposal that repeats one can be dropped."""
    try:
        from profile_query import build_queries

        persona = load_yaml(persona_yaml(persona_slug))
        if not persona:
            return []
        inputs = load_yaml(profile_inputs_path())
        return [str(item.get("query") or "") for item in build_queries(persona, inputs)]
    except Exception:  # noqa: BLE001 - the base set is optional for the guard
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", help="persona slug (default: the active persona)")
    parser.add_argument("--in", dest="source", type=Path, help="the agent's proposed queries")
    parser.add_argument("--out", dest="destination", type=Path, help="where to write the accepted queries")
    parser.add_argument("--max", dest="maximum", type=int, default=DEFAULT_MAX_QUERIES)
    args = parser.parse_args()

    from paths import active_persona
    from portal_map import load_portals

    persona_slug = args.persona or active_persona()
    inputs = load_yaml(profile_inputs_path())
    try:
        portals = load_portals()
    except SystemExit:
        portals = {}

    words, phrases = banned_terms(inputs, portals)
    entries = load_extra_query_file(args.source)
    accepted, rejected = validate_queries(entries, words, phrases, args.maximum)

    known = {text.strip().lower() for text in base_query_texts(persona_slug)}
    kept: list[dict] = []
    for item in accepted:
        key = item["query"].strip().lower()
        if key in known:
            rejected.append({"query": item["query"], "reason": "repeats a base query"})
            continue
        known.add(key)
        kept.append(item)

    if args.destination is not None:
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        args.destination.write_text(
            json.dumps({"added_queries": kept}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "persona": persona_slug,
                "proposed": len(entries),
                "accepted": [item["query"] for item in kept],
                "rejected": rejected,
                "out": str(args.destination) if args.destination else "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
