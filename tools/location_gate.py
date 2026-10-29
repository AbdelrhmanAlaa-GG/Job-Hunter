"""Work out which places the candidate can actually serve.

The search says where to look. The location gate decides whether a posting
that comes back is somewhere the candidate could take the job. Those are
different questions, and conflating them is what makes a search for "roles in
Egypt" come back with nothing: the candidate is *in* Egypt, so Egypt is a
place they can serve, not a place they have to be gated out of.

Two lists describe it.

``home_place``
    Where the candidate lives, from ``identity.location``. A place the
    candidate already lives in is never gated: an on-site role in Cairo is
    not a location problem for someone in Cairo. It needs no sponsorship and
    no relocation.

``servable_places``
    The places the user listed, with the work modes they accept and the
    conditions attached to each one - sponsorship, relocation, remote from
    home. Every country a listed place covers is named too, so "MENA" says
    which countries count as MENA rather than leaving the model to guess.

Both are deterministic. The model reads them and judges the posting's own
wording; it never works out the geography itself.

Usage:
    python3 tools/location_gate.py --persona ai-llm-rag --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import persona_yaml, profile_inputs_path  # noqa: E402
from places import Catalogue, load_catalogue, normalise  # noqa: E402

try:
    import yaml
except ImportError:
    print("location_gate: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


# What a run searches when the user has not said where to look. Remote, and
# nowhere in particular. It is a real search - not an empty one - and it is
# reported in the contract so it is never a silent default.
DEFAULT_LOCATIONS = [
    {
        "place": "anywhere",
        "mode": "remote",
        "note": "No location was given, so the search is remote roles anywhere.",
    }
]


def load_yaml(path: Path) -> dict:
    """Load a YAML document, returning an empty dict when the file is absent."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def location_entries(inputs: dict) -> tuple[list[dict], bool]:
    """Return the user's location preferences, and whether they were defaulted.

    An empty preference list is not an error and it is not a search that
    finds nothing. It is a search for remote roles anywhere, and the second
    value in the return says so.
    """
    preferences = inputs.get("preferences", {}) or {}
    raw = preferences.get("locations", []) or []
    entries = [entry for entry in raw if isinstance(entry, dict)]
    if not entries:
        return [dict(entry) for entry in DEFAULT_LOCATIONS], True
    return entries, False


def identity_location(inputs: dict, persona: dict) -> str:
    """Return where the candidate lives.

    The user's own inputs come first; the persona's copy of the same fact is
    the fallback. Nothing else is consulted.
    """
    identity = inputs.get("identity", {}) or {}
    value = identity.get("location")
    if isinstance(value, str) and value.strip():
        return value.strip()

    persona_identity = persona.get("identity", {}) or {}
    value = persona_identity.get("location")
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def home_place(inputs: dict, persona: dict, catalogue: Catalogue) -> dict | None:
    """Return the candidate's home place, resolved against the catalogue.

    ``city`` is the part before the first comma, so a posting that says only
    "Cairo" can still be recognised as the candidate's own city.
    """
    text = identity_location(inputs, persona)
    if not text:
        return None

    resolution = catalogue.resolve(text)
    if not resolution.resolved or resolution.place is None:
        return None

    place = resolution.place
    country = place.key if place.kind == "country" else None
    if country is None:
        countries = catalogue.countries_under(place.key)
        country = countries[0] if countries else None

    city = ""
    for segment in str(text).split(","):
        segment = segment.strip()
        if segment:
            city = segment
            break

    return {
        "text": text,
        "place": place.key,
        "name": place.name,
        "kind": place.kind,
        "country": country,
        "city": city,
    }


def servable_places(inputs: dict, persona: dict, catalogue: Catalogue) -> list[dict]:
    """Return the places the candidate can serve, with their conditions.

    The user's list comes first, in the order they wrote it. The home place
    is added when it is not already covered, because the candidate can always
    serve the place they live in.
    """
    entries, _defaulted = location_entries(inputs)
    servable: list[dict] = []
    home = home_place(inputs, persona, catalogue)

    for entry in entries:
        name = str(entry.get("place") or entry.get("region") or "").strip()
        if not name:
            continue
        resolution = catalogue.resolve(name)
        if not resolution.resolved or resolution.place is None:
            continue
        place = resolution.place

        remote_from_home = entry.get("remote_from_home")
        if remote_from_home is None:
            remote_from_home = entry.get("allowed_from_egypt")

        servable.append(
            {
                "place": place.key,
                "name": place.name,
                "kind": place.kind,
                "mode": str(entry.get("mode") or "").strip(),
                "countries": catalogue.countries_under(place.key),
                "requires_sponsorship": bool(entry.get("requires_sponsorship")),
                "allows_relocation": bool(entry.get("allows_relocation")),
                "remote_from_home": remote_from_home,
                "home": False,
                "note": str(entry.get("note") or ""),
            }
        )

    if home:
        covered = False
        for entry in servable:
            if entry["place"] == home["place"] or entry["place"] == home.get("country"):
                entry["home"] = True
                covered = True
        if not covered:
            servable.append(
                {
                    "place": home["place"],
                    "name": home["name"],
                    "kind": home["kind"],
                    "mode": "",
                    "countries": catalogue.countries_under(home["place"]),
                    "requires_sponsorship": False,
                    "allows_relocation": False,
                    "remote_from_home": None,
                    "home": True,
                    "note": "Where the candidate lives. On-site work here is never a location failure.",
                }
            )

    return servable


def names_home(location: str, home: dict | None, catalogue: Catalogue) -> bool:
    """Whether a posting's location is the candidate's home place.

    Both the home country and the home city count. A posting in "Cairo" with
    no country named is still a posting in the candidate's own city.
    """
    if not home:
        return False
    text = str(location or "").strip()
    if not text:
        return False

    country = home.get("country")
    if country:
        from market import countries_named

        if country in countries_named(text, catalogue):
            return True

    city = normalise(home.get("city") or "")
    if len(city) >= 3 and f" {city} " in f" {normalise(text)} ":
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", help="persona slug (default: the active persona)")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    args = parser.parse_args()

    from paths import active_persona

    persona_slug = args.persona or active_persona()
    catalogue = load_catalogue()
    inputs = load_yaml(profile_inputs_path())
    persona = load_yaml(persona_yaml(persona_slug))

    home = home_place(inputs, persona, catalogue)
    servable = servable_places(inputs, persona, catalogue)

    if args.format == "table":
        print(f"home: {home['name'] if home else 'not stated'}")
        for entry in servable:
            marker = " (home)" if entry["home"] else ""
            print(f"  {entry['name']} - {entry['mode'] or 'any work mode'}{marker}")
        return 0

    print(
        json.dumps(
            {"home_place": home, "servable_places": servable},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
