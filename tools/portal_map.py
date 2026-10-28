"""Turn a place into the flags each portal needs, without ever guessing wrong.

Two data files drive this:

``config/places.yaml``
    The catalogue. Which places exist, and what each portal calls them.

``config/portals.yaml``
    The mechanism. Which filters a portal has, and the flag each one uses.

The problem this module exists to solve is that portals disagree about
geography. freehire takes an ISO country code and a closed set of macro
regions. LinkedIn takes a free-text place string, and silently answers with
the wrong market when it does not recognise one. Jobicy takes a slug from its
own taxonomy of 55, which has no Egypt and no Saudi Arabia.

So a place cannot be translated once. It has to be translated *per portal*, and
when a portal cannot express it, the search must widen in a way the user can
see. The ladder is:

    exact place  ->  parent region  ->  ...  ->  anywhere

Every target records which rung it landed on. A search that quietly became
"everywhere" looks exactly like a search that found nothing, and the user
cannot tell the difference unless the tool says so.

Usage:
    python3 tools/portal_map.py --place EG --mode remote
    python3 tools/portal_map.py --place EG --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import ROOT  # noqa: E402
from places import Catalogue, Place  # noqa: E402

try:
    import yaml
except ImportError:
    print("portal_map: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

PORTALS_FILE = ROOT / "config" / "portals.yaml"

# The work mode the user asked for, and the value each portal's `remote`
# filter takes. LinkedIn takes one mode at a time; freehire takes a
# comma-separated list as an OR group.
WORK_MODES: dict[str, str] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "onsite_remote_hybrid": "remote,hybrid",
    "remote_or_relocation": "remote,hybrid",
}

# The rung of the ladder a target landed on.
SCOPE_EXACT = "exact"
SCOPE_WIDER = "wider"
SCOPE_FLOOR = "floor"


@dataclass
class Target:
    """One portal call's worth of flags."""

    portal: str
    label: str
    flags: dict[str, str] = field(default_factory=dict)
    scope: str = SCOPE_EXACT
    rung: str = ""
    place_key: str = ""
    place_name: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "portal": self.portal,
            "label": self.label,
            "flags": dict(self.flags),
            "scope": self.scope,
            "rung": self.rung,
            "place": self.place_key,
            "place_name": self.place_name,
            "note": self.note,
        }


@dataclass
class Skip:
    """A portal that could not be searched, and why."""

    portal: str
    place: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "portal": self.portal,
            "place": self.place,
            "reason": self.reason,
            "detail": self.detail,
        }


def load_portals(path: Path | None = None) -> dict:
    """Load the portal capability matrix."""
    target = path or PORTALS_FILE
    if not target.exists():
        print(f"portal_map: no portal matrix at {target}.", file=sys.stderr)
        raise SystemExit(1)
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return data.get("portals") or {}


def flag_for(portals: dict, portal: str, canonical: str) -> str | None:
    """Return the flag a portal uses for a canonical filter name.

    Returns None when the portal does not have the filter, or when the filter
    is one the portal documents but does not honour.
    """
    spec = (portals.get(portal) or {}).get("filters") or {}
    entry = spec.get(canonical)
    if not entry:
        return None
    if entry.get("supported") is False:
        return None
    return entry.get("flag")


def supports_filter(portals: dict, portal: str, canonical: str) -> bool:
    """Whether a portal can actually filter on something."""
    return flag_for(portals, portal, canonical) is not None


def ladder(catalogue: Catalogue, place: Place) -> list[Place]:
    """Return the places to try for one request, nearest first.

    The requested place, then each parent region, then "anywhere". "Anywhere"
    is always last because it is the floor, not a choice.
    """
    chain: list[Place] = [place]
    for parent in catalogue.parent_chain(place.key):
        chain.append(parent)
    floor = catalogue.get("anywhere")
    if floor is not None and floor.key != place.key:
        chain.append(floor)
    return chain


def _expand(value: object) -> list[str]:
    """A catalogue value may be one string or a list of alternatives."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def build_targets(
    catalogue: Catalogue,
    portals: dict,
    place: Place,
    mode: str = "",
    enabled: list[str] | None = None,
    extra_flags: dict[str, str] | None = None,
) -> tuple[list[Target], list[Skip]]:
    """Build every portal target for one place, and record what was skipped.

    ``enabled`` restricts the portals to consider; None means all of them.
    ``extra_flags`` are canonical filters that do not come from the place -
    the query, the recency, the category.
    """
    targets: list[Target] = []
    skips: list[Skip] = []

    work_mode = WORK_MODES.get(str(mode or "").strip().lower(), "")

    for portal in (portals or {}):
        if enabled is not None and portal not in enabled:
            continue

        spec = portals.get(portal) or {}
        geography = spec.get("geography") or {}
        country_filter = geography.get("country")
        region_filter = geography.get("region")

        chosen: Target | None = None
        alternatives: list[str] = []
        attempts: list[str] = []

        for rung in ladder(catalogue, place):
            value = (rung.values or {}).get(portal)
            if not value:
                attempts.append(f"{rung.key}: no value for this portal")
                continue

            kind = "country" if rung.kind == "country" else "region"
            canonical = country_filter if kind == "country" else region_filter
            if not canonical:
                attempts.append(f"{rung.key}: this portal has no {kind} filter")
                continue
            if not supports_filter(portals, portal, canonical):
                attempts.append(f"{rung.key}: this portal does not support {canonical}")
                continue

            raw = value.get(canonical)
            if raw is None or raw == "":
                attempts.append(f"{rung.key}: no value for {canonical}")
                continue

            scope = value.get("scope")
            if not scope:
                if rung.key == place.key:
                    scope = SCOPE_EXACT
                elif rung.key == "anywhere":
                    scope = SCOPE_FLOOR
                else:
                    scope = SCOPE_WIDER

            alternatives = _expand(raw)
            chosen = Target(
                portal=portal,
                label=f"{portal}: {place.name}",
                flags={canonical: alternatives[0]},
                scope=scope,
                rung=rung.key,
                place_key=place.key,
                place_name=place.name,
                note=str(value.get("note") or ""),
            )
            break

        if chosen is None:
            skips.append(
                Skip(
                    portal=portal,
                    place=place.key,
                    reason="no_geography",
                    detail="; ".join(attempts) or "the place and every parent have no value",
                )
            )
            continue

        canonical = canonical_value(chosen, portals)

        # The work mode, unless the place already fixed it.
        if work_mode and "remote" not in chosen.flags:
            if supports_filter(portals, portal, "remote"):
                chosen.flags["remote"] = work_mode

        # Non-geography filters the caller supplied.
        for canonical_name, value in (extra_flags or {}).items():
            if not value:
                continue
            if canonical_name == "category":
                # The canonical category is translated into each portal's own
                # vocabulary, and into its own filter name.
                category_filter = spec.get("category_filter")
                if not category_filter:
                    continue
                alias_value = (spec.get("category_aliases") or {}).get(str(value), str(value))
                chosen.flags[category_filter] = alias_value
                continue
            if not supports_filter(portals, portal, canonical_name):
                continue
            chosen.flags[canonical_name] = str(value)

        # A list value means several searches for the same place.
        variants: list[tuple[dict[str, str], str]] = []
        for alternative in alternatives:
            variant = dict(chosen.flags)
            variant[canonical] = alternative
            variants.append((variant, str(alternative)))

        # LinkedIn takes one work mode at a time; freehire takes an OR list.
        expanded: list[tuple[dict[str, str], str]] = []
        for variant, label_part in variants:
            remote_value = variant.get("remote")
            if (
                remote_value
                and "," in remote_value
                and not (spec.get("filters", {}).get("remote", {}) or {}).get("comma_or", False)
            ):
                for single in remote_value.split(","):
                    single = single.strip()
                    if not single:
                        continue
                    split = dict(variant)
                    split["remote"] = single
                    expanded.append((split, single))
            else:
                expanded.append((variant, label_part))

        for variant, label_part in expanded:
            targets.append(
                Target(
                    portal=chosen.portal,
                    label=(
                        chosen.label
                        if len(expanded) == 1
                        else f"{chosen.label} ({label_part})"
                    ),
                    flags=variant,
                    scope=chosen.scope,
                    rung=chosen.rung,
                    place_key=chosen.place_key,
                    place_name=chosen.place_name,
                    note=chosen.note,
                )
            )

    return targets, skips


def canonical_value(target: Target, portals: dict) -> str:
    """Return the canonical name of the geography filter a target carries."""
    spec = portals.get(target.portal) or {}
    geography = spec.get("geography") or {}
    for kind in ("country", "region"):
        name = geography.get(kind)
        if name and name in target.flags:
            return name
    return ""


def flags_to_argv(portals: dict, portal: str, flags: dict[str, str]) -> list[str]:
    """Turn canonical flags into a portal's own argv.

    Only filters the portal actually supports are emitted. A flag it documents
    but ignores is never sent, because sending it hides a gap.
    """
    argv: list[str] = []
    for canonical, value in flags.items():
        if value in (None, ""):
            continue
        flag = flag_for(portals, portal, canonical)
        if not flag:
            continue
        argv += [flag, str(value)]
    return argv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--place", help="catalogue key or a place name")
    parser.add_argument("--mode", default="", help="work mode: remote, hybrid, onsite")
    parser.add_argument("--portals", help="comma-separated portal names to include")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    args = parser.parse_args()

    from places import load_catalogue

    catalogue = load_catalogue()
    portals = load_portals()

    if not args.place:
        parser.print_help()
        return 1

    resolution = catalogue.resolve(args.place)
    if not resolution.resolved or resolution.place is None:
        print(json.dumps(resolution.to_dict(), ensure_ascii=False, indent=2))
        print(
            "portal_map: the place could not be resolved. Ask the user which one "
            "they mean.",
            file=sys.stderr,
        )
        return 2

    enabled = [name.strip() for name in args.portals.split(",")] if args.portals else None
    targets, skips = build_targets(catalogue, portals, resolution.place, args.mode, enabled)

    if args.format == "table":
        for target in targets:
            rendered = " ".join(f"{k}={v}" for k, v in target.flags.items())
            print(f"{target.portal:<18} {target.scope:<6} {target.rung:<8} {rendered}")
        for skip in skips:
            print(f"{skip.portal:<18} SKIPPED ({skip.reason}) {skip.detail}")
    else:
        print(
            json.dumps(
                {
                    "place": resolution.place.key,
                    "targets": [target.to_dict() for target in targets],
                    "skipped": [skip.to_dict() for skip in skips],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
