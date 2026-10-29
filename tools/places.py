"""Resolve the places a user names into the catalogue's own keys.

The catalogue in ``config/places.yaml`` is the single source of truth for
geography: which places exist, how they are named, and what each portal calls
them. This module turns what a person typed - "Germany", "the Gulf", "MENA",
"work from anywhere" - into a catalogue key.

Two rules matter more than the matching itself:

**Never guess.** A place the catalogue does not know is not quietly widened to
something nearby. :func:`resolve` returns an unresolved result carrying
near-misses, and the caller asks the user. A wrong geography that returns
plausible postings is worse than no search at all, because it looks like it
worked.

**Never narrow silently either.** The catalogue's hierarchy is a ladder
(``tools/portal_map.py``), and each rung it lands on is reported.

Usage:
    python3 tools/places.py --resolve "the Gulf"
    python3 tools/places.py --list regions
    python3 tools/places.py --search german
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import ROOT  # noqa: E402

try:
    import yaml
except ImportError:
    print("places: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

PLACES_FILE = ROOT / "config" / "places.yaml"

# Words that carry no meaning in a place name and are dropped before matching.
# "jobs in the Netherlands" is a search sentence, not a place name.
STOPWORDS = {
    "a",
    "an",
    "the",
    "in",
    "at",
    "on",
    "of",
    "and",
    "or",
    "for",
    "to",
    "from",
    "with",
    "near",
    "around",
    "jobs",
    "job",
    "roles",
    "role",
    "positions",
    "position",
    "vacancies",
    "vacancy",
    "work",
    "working",
    "based",
    "located",
    "area",
    "region",
    "country",
    "countries",
    "city",
    "cities",
}

# Words that mean "no geographic restriction", wherever they appear.
REMOTE_WORDS = {
    "remote",
    "anywhere",
    "worldwide",
    "world",
    "global",
    "international",
    "offshore",
    "distributed",
}


def normalise(text: str) -> str:
    """Fold a place name into a comparable form.

    Lowercase, strip accents, drop punctuation, collapse whitespace. "N'Djamena",
    "Cote d'Ivoire" and "cote divoire" all fold to the same shape.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = stripped.lower()
    out: list[str] = []
    for ch in lowered:
        if ch.isalnum() or ch.isspace():
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def strip_stopwords(text: str) -> str:
    """Remove the words that carry no place information."""
    tokens = [token for token in normalise(text).split() if token]
    kept = [token for token in tokens if token not in STOPWORDS]
    return " ".join(kept) if kept else normalise(text)


@dataclass
class Place:
    """One entry in the catalogue."""

    key: str
    kind: str  # "country" or "region"
    name: str
    aliases: list[str] = field(default_factory=list)
    parent: str | None = None
    values: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    # A region may name the countries it covers when the hierarchy cannot say
    # it. The European Union is the case that needs it: its members are
    # children of "europe", not of "european_union".
    countries: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """A human-readable label, e.g. "Egypt" or "Middle East and North Africa"."""
        return self.name

    def label_with_kind(self) -> str:
        return f"{self.name} ({self.kind})"


@dataclass
class Resolution:
    """The outcome of resolving one piece of free text."""

    text: str
    place: Place | None = None
    candidates: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""
    remote: bool = False

    @property
    def resolved(self) -> bool:
        return self.place is not None

    def to_dict(self) -> dict:
        payload: dict = {
            "text": self.text,
            "resolved": self.resolved,
        }
        if self.place is not None:
            payload["place"] = {
                "key": self.place.key,
                "kind": self.place.kind,
                "name": self.place.name,
                "parent": self.place.parent,
            }
        if self.remote:
            payload["remote"] = True
        if self.candidates:
            payload["candidates"] = [
                {"key": key, "name": name, "kind": kind} for key, name, kind in self.candidates
            ]
        if self.note:
            payload["note"] = self.note
        return payload


class Catalogue:
    """The loaded place catalogue."""

    def __init__(self, data: dict) -> None:
        self.version = data.get("version", 1)
        self.places: dict[str, Place] = {}
        self._index: dict[str, str] = {}
        self._keys: dict[str, str] = {}

        for key, entry in (data.get("regions") or {}).items():
            self._add("region", key, entry)
        for key, entry in (data.get("countries") or {}).items():
            self._add("country", key, entry)

    def _add(self, kind: str, key: str, entry: dict) -> None:
        place = Place(
            key=key,
            kind=kind,
            name=str(entry.get("name") or key),
            aliases=[str(item) for item in entry.get("aliases") or []],
            parent=entry.get("parent"),
            values=entry.get("values") or {},
            notes=entry.get("notes") or {},
            countries=[str(item) for item in entry.get("countries") or []],
        )
        self.places[key] = place
        folded_key = normalise(key)
        if folded_key:
            self._keys.setdefault(folded_key, key)
        for label in [place.name] + place.aliases:
            folded = normalise(label)
            if folded:
                # First definition wins, so a region is never shadowed by a
                # country that happens to share an alias.
                self._index.setdefault(folded, key)

    def get(self, key: str) -> Place | None:
        return self.places.get(key)

    def parent_chain(self, key: str) -> list[Place]:
        """Return the place's ancestors, nearest first, without the place itself."""
        chain: list[Place] = []
        seen: set[str] = set()
        current = self.places.get(key)
        while current is not None and current.parent:
            if current.parent in seen:
                break
            seen.add(current.parent)
            parent = self.places.get(current.parent)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        return chain

    def children_of(self, key: str) -> list[Place]:
        """Return the places whose parent is this one."""
        return [place for place in self.places.values() if place.parent == key]

    def countries_under(self, key: str) -> list[str]:
        """Return the country keys a place covers.

        A country covers itself. A region covers its children, and every
        country beneath them. A region may also name its members directly,
        for the places the hierarchy cannot express - the European Union's
        members are children of "europe", not of "european_union".

        This is what turns "MENA" into the list of countries a posting has to
        be in to count as a MENA posting.
        """
        if key not in self.places:
            return []
        place = self.places[key]
        if place.kind == "country":
            return [key]
        found: list[str] = []
        seen: set[str] = set()

        def add(candidate_key: str) -> None:
            if candidate_key in seen:
                return
            candidate = self.places.get(candidate_key)
            if candidate is None or candidate.kind != "country":
                return
            seen.add(candidate_key)
            found.append(candidate_key)

        def walk(current_key: str, depth: int) -> None:
            current = self.places.get(current_key)
            if current is None or depth > 12:
                return
            for code in current.countries:
                add(code)
            for child in self.children_of(current_key):
                add(child.key)
                walk(child.key, depth + 1)

        walk(key, 0)
        return sorted(found)

    def search(self, text: str, limit: int = 8) -> list[tuple[str, str, str]]:
        """Return catalogue entries matching a fragment of free text.

        Each result is ``(key, name, kind)``.
        """
        needle = normalise(text)
        if not needle:
            return []
        hits: list[tuple[int, str, str, str]] = []
        for folded, key in self._index.items():
            if needle in folded:
                place = self.places[key]
                # An exact label is a better match than a fragment.
                score = 0 if folded == needle else len(folded) - len(needle)
                hits.append((score, place.name, key, place.kind))
        for folded, key in self._keys.items():
            if needle in folded:
                place = self.places[key]
                score = -1 if folded == needle else len(folded) - len(needle)
                hits.append((score, place.name, key, place.kind))
        hits.sort(key=lambda item: (item[0], item[1]))
        seen: set[str] = set()
        unique: list[tuple[str, str, str]] = []
        for _score, name, key, kind in hits:
            if key in seen:
                continue
            seen.add(key)
            unique.append((key, name, kind))
        return unique[:limit]

    def resolve(self, text: str) -> Resolution:
        """Resolve free text to a catalogue place.

        The order of attempts is deliberate:

        1. An exact match on a name or alias.
        2. The last comma-separated segment that resolves, so "Cairo, Egypt"
           finds Egypt. Cities are not a level this catalogue holds, but the
           country a city sits in is not lost because of it.
        3. The text with any remote phrase removed, so "remote jobs in Europe"
           finds Europe rather than throwing the whole sentence away.
        4. A remote phrase on its own means no geographic restriction.
        5. The same text with the sentence words removed.
        6. A unique fragment match, otherwise near-misses for the user to choose
           from.
        """
        original = str(text or "")
        folded = normalise(original)
        if not folded:
            return Resolution(text=original)

        tokens = folded.split()
        remote = bool(set(tokens) & REMOTE_WORDS)

        # 0. The catalogue key itself, so "EG" and "mena" work.
        key = self._keys.get(folded)
        if key:
            return Resolution(text=original, place=self.places[key], remote=remote)

        # 1. Exact name or alias.
        key = self._index.get(folded)
        if key:
            return Resolution(text=original, place=self.places[key], remote=remote)

        # 2. The country in a "City, Country" string.
        segments = [part.strip() for part in str(original).split(",") if part.strip()]
        if len(segments) > 1:
            for segment in reversed(segments):
                hit = self._index.get(normalise(segment))
                if hit and hit != "anywhere":
                    return Resolution(
                        text=original,
                        place=self.places[hit],
                        remote=remote,
                        note=f"Read as {self.places[hit].name}.",
                    )

        # 3. The text with the remote phrase taken out.
        remainder = " ".join(
            token for token in tokens if token not in REMOTE_WORDS and token not in STOPWORDS
        )
        if remainder:
            hit = self._index.get(remainder)
            if hit:
                return Resolution(
                    text=original,
                    place=self.places[hit],
                    remote=remote,
                    note=f"Read as {self.places[hit].name}.",
                )

        # 4. A remote phrase on its own means no geographic restriction.
        if remote:
            return Resolution(
                text=original,
                place=self.places.get("anywhere"),
                remote=True,
                note="Read as 'no geographic restriction'.",
            )

        # 5. The same text with the sentence words removed.
        trimmed = strip_stopwords(original)
        key = self._index.get(trimmed)
        if key:
            return Resolution(text=original, place=self.places[key])

        # 6. A fragment match. Only a unique one is accepted.
        hits = self.search(trimmed)
        if len(hits) == 1:
            hit_key, _name, _kind = hits[0]
            return Resolution(text=original, place=self.places[hit_key])

        # 7. Nothing certain. Offer the options rather than guessing.
        if not hits:
            hits = [
                (key, self.places[key].name, "region") for key in self.keys_of_kind("region")
            ]
        return Resolution(
            text=original,
            candidates=[(key, name, kind) for key, name, kind in hits],
            note=(
                "This place is not in the catalogue. Ask the user which one they "
                "mean, or add it to config/places.yaml."
            ),
        )

    def keys_of_kind(self, kind: str) -> list[str]:
        return sorted(key for key, place in self.places.items() if place.kind == kind)


def load_catalogue(path: Path | None = None) -> Catalogue:
    """Load the place catalogue."""
    target = path or PLACES_FILE
    if not target.exists():
        print(f"places: no catalogue at {target}.", file=sys.stderr)
        raise SystemExit(1)
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return Catalogue(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resolve", help="resolve one piece of free text")
    parser.add_argument("--list", choices=("regions", "countries", "all"), help="list catalogue keys")
    parser.add_argument("--search", help="list places matching a fragment")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    args = parser.parse_args()

    catalogue = load_catalogue()

    if args.list:
        keys = []
        if args.list in ("regions", "all"):
            keys += [(key, catalogue.places[key].name, "region") for key in catalogue.keys_of_kind("region")]
        if args.list in ("countries", "all"):
            keys += [(key, catalogue.places[key].name, "country") for key in catalogue.keys_of_kind("country")]
        if args.format == "table":
            for key, name, kind in keys:
                print(f"{key:<6} {kind:<8} {name}")
        else:
            print(json.dumps([{"key": k, "name": n, "kind": kd} for k, n, kd in keys], indent=2))
        return 0

    if args.search:
        hits = catalogue.search(args.search, limit=20)
        if args.format == "table":
            for key, name, kind in hits:
                print(f"{key:<6} {kind:<8} {name}")
        else:
            print(json.dumps([{"key": k, "name": n, "kind": kd} for k, n, kd in hits], indent=2))
        return 0

    if args.resolve:
        resolution = catalogue.resolve(args.resolve)
        print(json.dumps(resolution.to_dict(), ensure_ascii=False, indent=2))
        return 0 if resolution.resolved else 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
