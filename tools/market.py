"""Check that a posting's own location agrees with the place that was searched.

Portals leak. freehire answers ``--country EG`` with postings in the UAE and
Kazakhstan; LinkedIn answers ``--location United States`` with Toronto. A
posting from the wrong market is worse than no posting at all, because it looks
like a hit - and in a small market it can outrank the posting the user asked
for.

The rule is deliberately narrow:

* Only an **exact country** target is checked. A region target is already
  reported as widened, and its own scope note explains what it covers.
* Only a posting that **names a country** is judged. "Cairo" names no country,
  so it is left alone - a city is not a contradiction, and throwing it away
  would lose exactly the postings that matter in a small market.

Usage:
    python3 tools/market.py --location "Cairo, Egypt" --country EG
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from places import Catalogue, load_catalogue, normalise  # noqa: E402

# Aliases shorter than this are not matched as words. "us" is a real alias of
# the United States, but as a word it would turn "roles for us" into an
# American posting. Two-letter codes are matched by a different rule - as an
# uppercase segment - so they do not need to be words at all.
MIN_WORD_LENGTH = 3

# A country written as a two-letter code, standing alone in a segment:
# "Cairo, EG". These are matched case-sensitively, because a lower-case "in"
# is a word and not India.
CODE_SEGMENT = re.compile(r"^[A-Z]{2}$")

# Separators a portal uses between the parts of a location string.
SEGMENT_SPLIT = re.compile(r"[,;/|&\n\r]+")


def _word_phrases(place) -> list[str]:
    """Return the names a location string may use for a country.

    The country name and its aliases, but only the ones long enough to be
    matched as a word.
    """
    phrases: list[str] = []
    for label in [place.name] + list(place.aliases or []):
        folded = normalise(label)
        if len(folded) >= MIN_WORD_LENGTH:
            phrases.append(folded)
    return phrases


def countries_named(location: str, catalogue: Catalogue) -> set[str]:
    """Return the catalogue country keys a location string names.

    Two rules, and both of them matter:

    * A name or alias is matched as a whole word. "Nigeria" names Nigeria and
      not Niger, and "Egypt" does not hide inside "Egyptian".
    * A two-letter code is matched only where it stands alone as a segment,
      and only in the case the portal wrote it in. Otherwise "in" would turn
      every sentence with the word "in" into an Indian posting.
    """
    text = str(location or "").strip()
    if not text:
        return set()

    found: set[str] = set()
    padded = f" {normalise(text)} "

    for key, place in catalogue.places.items():
        if place.kind != "country":
            continue
        for phrase in _word_phrases(place):
            if f" {phrase} " in padded:
                found.add(key)
                break

    for segment in SEGMENT_SPLIT.split(text):
        segment = segment.strip()
        if not segment or not CODE_SEGMENT.match(segment):
            continue
        candidate = catalogue.places.get(segment.upper())
        if candidate is not None and candidate.kind == "country":
            found.add(candidate.key)

    return found


def matches_country(location: str, country_key: str, catalogue: Catalogue) -> bool:
    """Whether a posting's location agrees with the country that was searched.

    A posting that names no country is kept: there is nothing to contradict.
    """
    if not country_key:
        return True
    named = countries_named(location, catalogue)
    if not named:
        return True
    return country_key in named


def out_of_market(location: str, country_key: str, catalogue: Catalogue) -> bool:
    """Whether a posting's location names a country other than the one searched."""
    if not country_key:
        return False
    named = countries_named(location, catalogue)
    if not named:
        return False
    return country_key not in named


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--location", required=True, help="the posting's location string")
    parser.add_argument("--country", required=True, help="the catalogue country key that was searched")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    args = parser.parse_args()

    catalogue = load_catalogue()
    named = countries_named(args.location, catalogue)
    matches = matches_country(args.location, args.country.upper(), catalogue)

    if args.format == "table":
        print(f"location: {args.location}")
        print(f"countries named: {', '.join(sorted(named)) or 'none'}")
        print(f"matches {args.country.upper()}: {matches}")
        return 0

    print(
        json.dumps(
            {
                "location": args.location,
                "country": args.country.upper(),
                "countries_named": sorted(named),
                "matches": matches,
                "out_of_market": out_of_market(args.location, args.country.upper(), catalogue),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
