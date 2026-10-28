"""Turn a persona into search queries, target roles and ranking filters.

This is a pure function: persona YAML plus user inputs in, a JSON contract out.
Keeping it model-free means the same inputs always produce the same queries, so
a run is reproducible and the query set can be reviewed in a diff.

The one place a model is allowed to influence the result is the persona file
itself, where target roles and skills carry evidence. This module decides how
those become queries; it does not invent new ones.

Usage:
    python3 tools/profile_query.py --persona ai-llm-rag
    python3 tools/profile_query.py --persona ai-llm-rag --format markdown
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import (  # noqa: E402
    active_persona,
    list_personas,
    persona_yaml,
    profile_inputs_path,
)
from places import load_catalogue  # noqa: E402
from portal_map import build_targets, load_portals  # noqa: E402

try:
    import yaml
except ImportError:
    print("profile_query: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

# Skills that make a query more specific rather than noisier. A query built
# from two of these reads like a real job title; a query built from "C" and
# "Git" does not.
QUERY_SKILL_PRIORITY = (
    "retrieval-augmented generation (rag)",
    "rag",
    "llm apis",
    "llm",
    "fastapi",
    "chromadb",
    "document and table extraction (pymupdf)",
    "pymupdf",
    "embeddings and semantic search",
    "embeddings",
    "semantic search",
    "rag evaluation (ragas)",
    "ragas",
    "python",
)

# What each portal can filter on lives in config/portals.yaml, and what each
# place is called on each portal lives in config/places.yaml. Neither belongs
# in this file: a capability that changes should change in one place, and a
# place that was never catalogued should produce a question, not a silent
# drop.
#
# The old table in this file had four regions in it and dropped everything
# else with a bare `continue`, so a user asking for Germany, Nigeria or the UK
# got no search and no explanation.

# freehire's seniority vocabulary, in the order a preference list should be
# read. The user's own seniority preferences decide which one is sent.
SENIORITY_TOKENS = ("junior", "middle", "senior", "staff", "principal", "lead")

# Words in a persona that mark it as AI and machine-learning work. The
# canonical category is translated per portal by config/portals.yaml.
AI_CATEGORY_TOKENS = (
    "ai",
    "ml",
    "llm",
    "rag",
    "machine learning",
    "artificial intelligence",
    "data science",
    "nlp",
    "mlops",
)

# The canonical category name. Each portal maps it to its own vocabulary.
AI_CATEGORY = "ai_ml"


def load_yaml(path: Path) -> dict:
    """Load a YAML document, returning an empty dict when the file is absent."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def skill_display(name: str) -> str:
    """Return a skill name in the form a job ad would use."""
    special = {
        "retrieval-augmented generation (rag)": "RAG",
        "rag evaluation (ragas)": "RAGAS",
        "document and table extraction (pymupdf)": "PyMuPDF",
        "embeddings and semantic search": "embeddings",
        "llm apis": "LLM",
    }
    return special.get(name.lower(), name)


def overlaps(first: str, second: str) -> bool:
    """Whether two skill names are the same family (RAG and RAGAS, say)."""
    left, right = first.lower(), second.lower()
    return left in right or right in left


def pick_query_skills(skills: list[dict], limit: int = 4) -> list[dict]:
    """Return the skills most worth putting in a search query.

    Primary skills first, then the ones whose name matches the priority list.
    A skill that is merely present (weight ``weak``) is not used - it narrows
    the search without describing the role.
    """
    usable = [skill for skill in skills if skill.get("weight") in ("primary", "secondary")]
    if not usable:
        usable = list(skills)

    def rank(skill: dict) -> tuple:
        weight_rank = 0 if skill.get("weight") == "primary" else 1
        name = str(skill.get("name", "")).lower()
        priority = len(QUERY_SKILL_PRIORITY)
        for index, token in enumerate(QUERY_SKILL_PRIORITY):
            if token in name:
                priority = index
                break
        return (weight_rank, priority, name)

    return sorted(usable, key=rank)[:limit]


def build_queries(persona: dict, inputs: dict, limit: int = 12) -> list[dict]:
    """Build the search-query set for a persona.

    A query is **keywords only**: the role plus the signature skills the
    candidate actually has. Seniority, work mode, geography and recency are
    not part of the query - the portals filter those with flags, and a query
    like "Applied AI Engineer junior remote" matches nothing because no job
    title contains the word "remote".

    Several query shapes are generated so that portals which match on
    different parts of a posting each get something that fits.
    """
    roles = [role for role in persona.get("target_roles", []) if role.get("title")]
    roles.sort(key=lambda role: role.get("priority", 99))
    skills = pick_query_skills(persona.get("skills", []))
    if not roles or not skills:
        return []

    queries: list[dict] = []
    seen: set[str] = set()
    per_role: dict[str, int] = {}
    max_per_role = 2

    def add(text: str, kind: str, priority: int, sources: list[str], role: str = "") -> None:
        normalized = " ".join(text.split()).lower()
        if normalized in seen:
            return
        if role and per_role.get(role, 0) >= max_per_role:
            return
        seen.add(normalized)
        if role:
            per_role[role] = per_role.get(role, 0) + 1
        queries.append({"query": " ".join(text.split()), "kind": kind, "priority": priority, "source": sources})

    primary = roles[0]["title"]
    secondary = roles[1]["title"] if len(roles) > 1 else primary

    # Shape 1: role first, then the signature skills. This reads like a real
    # job title and matches postings that mention both.
    for skill in skills[:3]:
        name = skill_display(str(skill.get("name", "")))
        add(f"{primary} {name}", "role+skill", 1, ["persona:skills", "persona:target_roles"], primary)

    # Shape 2: role plus two non-overlapping skills, for postings that spell
    # out a stack.
    for index, skill in enumerate(skills[:4]):
        name = skill_display(str(skill.get("name", "")))
        for other in skills[index + 1:4]:
            other_name = skill_display(str(other.get("name", "")))
            if overlaps(name, other_name):
                continue
            add(f"{primary} {name} {other_name}", "role+skills", 1, ["persona:skills"], primary)
            break

    # Shape 3: the bare top role, so a portal that rewards an exact title
    # match still gets a chance.
    add(primary, "role", 2, ["persona:target_roles"], primary)

    # Shape 4: the next roles in the priority list, so a persona is not
    # narrowed to a single title. Each gets a bare form and a form carrying
    # the candidate's strongest skill.
    best_skill = skill_display(str(skills[0].get("name", ""))) if skills else ""
    for role in roles[1:5]:
        title = str(role["title"])
        add(title, "role", 2, ["persona:target_roles"], title)
        if best_skill and not overlaps(best_skill, title):
            add(f"{title} {best_skill}", "role+skill", 2, ["persona:skills"], title)

    queries.sort(key=lambda item: (item["priority"], item["query"]))
    return queries[:limit]


def seniority_value(inputs: dict) -> str:
    """Return the seniority level to filter on, if the user expressed one.

    The user's own seniority preferences decide. A preference list that says
    "junior" sends junior; one that does not mention any level a portal knows
    sends nothing, rather than guessing.
    """
    preferences = inputs.get("preferences", {}) or {}
    seniority = preferences.get("seniority", {}) or {}
    wanted = {str(token).strip().lower() for token in seniority.get("include", []) or []}
    for token in SENIORITY_TOKENS:
        if token in wanted:
            return token
    return ""


def category_value(persona: dict) -> str:
    """Return the canonical job category for a persona, if it has one.

    Only AI and machine-learning work is recognised. A persona in another
    field gets no category filter rather than a wrong one - a category that
    does not match the persona silently removes every good posting.
    """
    haystack: list[str] = []
    for key in ("title", "persona"):
        value = persona.get(key)
        if isinstance(value, str):
            haystack.append(value)
    for role in persona.get("target_roles", []) or []:
        if isinstance(role, dict) and role.get("title"):
            haystack.append(str(role["title"]))
    text = " ".join(haystack).lower()

    for token in AI_CATEGORY_TOKENS:
        if token in text:
            return AI_CATEGORY
    return ""


def build_portal_targets(inputs: dict, persona: dict) -> dict:
    """Build the concrete per-portal search invocations.

    Each target is one portal plus the flag values that express the user's
    location preferences and filters. The command turns each target into a
    CLI invocation, one per query.

    A user who wants finer control can write explicit targets into
    ``profiles/inputs.yaml`` under ``search.targets``; those replace the
    derived ones entirely.

    Returns a dict with three lists:

    ``targets``
        The searches to run.
    ``skipped``
        Portals that could not be searched for a place, and why.
    ``unresolved``
        Places the catalogue does not know. The agent asks the user about
        these rather than searching somewhere else.
    """
    search = inputs.get("search", {}) or {}
    explicit = search.get("targets")
    if isinstance(explicit, list) and explicit:
        return {
            "targets": [target for target in explicit if isinstance(target, dict)],
            "skipped": [],
            "unresolved": [],
        }

    portal_settings = search.get("portals") or {}
    if isinstance(portal_settings, list):
        # Legacy shape: a plain list of portal names.
        portal_settings = {name: {} for name in portal_settings}
    if not isinstance(portal_settings, dict):
        portal_settings = {}

    enabled = [
        name
        for name, settings in portal_settings.items()
        if not isinstance(settings, dict) or settings.get("enabled") is not False
    ]

    recency = int(search.get("recency_days", 14) or 14)
    limit = int(search.get("limit_per_query", 20) or 20)
    preferences = inputs.get("preferences", {}) or {}
    locations = preferences.get("locations", []) or []

    catalogue = load_catalogue()
    portals = load_portals()

    common: dict[str, str] = {"jobage": str(recency), "limit": str(limit)}
    seniority = seniority_value(inputs)
    if seniority:
        common["seniority"] = seniority
    category = category_value(persona)
    if category:
        common["category"] = category

    targets: list[dict] = []
    skipped: list[dict] = []
    unresolved: list[dict] = []

    for entry in locations:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("place") or entry.get("region") or "").strip()
        mode = str(entry.get("mode") or "").strip()
        if not name:
            skipped.append(
                {
                    "portal": "",
                    "place": "",
                    "reason": "no_place",
                    "detail": "the location entry has neither 'place' nor 'region'",
                }
            )
            continue

        resolution = catalogue.resolve(name)
        if not resolution.resolved or resolution.place is None:
            unresolved.append(
                {
                    "text": name,
                    "candidates": [
                        {"key": key, "name": candidate_name, "kind": kind}
                        for key, candidate_name, kind in resolution.candidates
                    ],
                    "note": resolution.note,
                }
            )
            continue

        place = resolution.place
        place_targets, place_skips = build_targets(
            catalogue, portals, place, mode, enabled, common
        )

        for target in place_targets:
            payload = target.to_dict()
            payload["mode"] = mode
            if resolution.remote:
                payload["remote_requested"] = True
            targets.append(payload)

        for skip in place_skips:
            payload = skip.to_dict()
            payload["place"] = place.key
            skipped.append(payload)

    return {"targets": targets, "skipped": skipped, "unresolved": unresolved}


def build_filters(inputs: dict, persona: dict) -> dict:
    """Build the ranking filters from the user's inputs and the persona."""
    preferences = inputs.get("preferences", {}) or {}
    seniority = preferences.get("seniority", {}) or {}
    filters_block = inputs.get("filters", {}) or {}

    locations = []
    for entry in preferences.get("locations", []) or []:
        if not isinstance(entry, dict):
            continue
        # `allowed_from_egypt` was the old name of this key. It named one
        # candidate's home country; the key now says what it actually means.
        remote_from_home = entry.get("remote_from_home")
        if remote_from_home is None:
            remote_from_home = entry.get("allowed_from_egypt")
        locations.append(
            {
                "place": entry.get("place") or entry.get("region", ""),
                "mode": entry.get("mode", ""),
                "requires_sponsorship": bool(entry.get("requires_sponsorship")),
                "allows_relocation": bool(entry.get("allows_relocation")),
                "remote_from_home": remote_from_home,
                "note": entry.get("note", ""),
            }
        )

    return {
        "seniority": {
            "include": [str(token) for token in seniority.get("include", []) or []],
            "exclude": [str(token) for token in seniority.get("exclude", []) or []],
        },
        "visa_block": [str(token) for token in filters_block.get("visa_block", []) or []],
        "location_block": [str(token) for token in filters_block.get("location_block", []) or []],
        "locations": locations,
        "dealbreakers": [str(item) for item in inputs.get("dealbreakers", []) or []],
        "persona_exclusions": [
            str(entry.get("reason", ""))
            for entry in persona.get("persona_exclusions", []) or []
            if isinstance(entry, dict)
        ],
        "work_authorization": preferences.get("work_authorization", "") or inputs.get("preferences", {}).get("work_authorization", ""),
    }


def build_contract(persona: dict, inputs: dict) -> dict:
    """Return the full JSON contract the command and agent consume."""
    roles = [role for role in persona.get("target_roles", []) if role.get("title")]
    roles.sort(key=lambda role: role.get("priority", 99))
    search = inputs.get("search", {}) or {}
    portal_targets = build_portal_targets(inputs, persona)
    return {
        "persona": persona.get("persona", ""),
        "title": persona.get("title", ""),
        "provenance": {
            "resumes": [
                {
                    "slug": resume.get("slug", ""),
                    "file": resume.get("file", ""),
                    "sha256": resume.get("sha256", ""),
                }
                for resume in persona.get("resumes", []) or []
            ],
            "evidence_bullets": persona.get("evidence_bullets", []) or [],
            "projects": persona.get("projects", []) or [],
            "identity": persona.get("identity", {}) or {},
            "education": persona.get("education", []) or [],
            "experience": persona.get("experience", []) or [],
        },
        "target_roles": roles,
        "search_queries": build_queries(persona, inputs),
        "portal_targets": portal_targets["targets"],
        "portal_skipped": portal_targets["skipped"],
        "locations_unresolved": portal_targets["unresolved"],
        "filters": build_filters(inputs, persona),
        "search": {
            "recency_days": int((inputs.get("search", {}) or {}).get("recency_days", 14) or 14),
            "limit_per_query": int((inputs.get("search", {}) or {}).get("limit_per_query", 20) or 20),
            "site_queries": [str(query) for query in search.get("site_queries", []) or []],
        },
    }


def render_markdown(contract: dict) -> str:
    """Render the contract as the human-readable search-queries file."""
    persona = contract.get("persona", "")
    title = contract.get("title", "")
    lines = [
        f"# Search queries - {persona}",
        "",
        f"**Persona:** {persona} ({title})",
        "",
        "GENERATED by tools/profile_query.py from the persona file and the user",
        "inputs. Edit profiles/inputs.yaml or the persona file, then rebuild.",
        "",
        "## Queries",
        "",
    ]
    for index, item in enumerate(contract.get("search_queries", []), start=1):
        lines.append(f"{index}. `{item['query']}`  _{item['kind']}_")
    lines.extend(["", "## Target roles", ""])
    for role in contract.get("target_roles", []):
        lines.append(f"- **{role['title']}** (priority {role.get('priority', '?')})")

    lines.extend(["", "## Portal targets", ""])
    for target in contract.get("portal_targets", []):
        flags = " ".join(f"--{key} {value}" for key, value in target.get("flags", {}).items())
        scope = target.get("scope", "")
        suffix = f" [{scope}]" if scope and scope != "exact" else ""
        lines.append(f"- **{target['portal']}** ({target.get('label', '')}){suffix}: `{flags}`")
        note = target.get("note", "")
        if note:
            lines.append(f"  - {note}")

    skipped = contract.get("portal_skipped", []) or []
    if skipped:
        lines.extend(["", "## Skipped targets", ""])
        for skip in skipped:
            lines.append(
                f"- **{skip.get('portal', '')}** ({skip.get('place', '')}): "
                f"{skip.get('reason', '')} - {skip.get('detail', '')}"
            )

    unresolved = contract.get("locations_unresolved", []) or []
    if unresolved:
        lines.extend(["", "## Locations needing a word from the user", ""])
        for entry in unresolved:
            options = ", ".join(str(item.get("name", "")) for item in entry.get("candidates", [])[:8])
            lines.append(f"- **{entry.get('text', '')}** - not in the catalogue. Candidates: {options}")

    lines.extend(["", "## Filters", ""])
    filters = contract.get("filters", {})
    seniority = filters.get("seniority", {})
    lines.append(f"- **Seniority include:** {', '.join(seniority.get('include', []))}")
    lines.append(f"- **Seniority exclude:** {', '.join(seniority.get('exclude', []))}")
    lines.append(f"- **Visa block:** {', '.join(filters.get('visa_block', []))}")
    lines.append("")
    lines.append("## Locations")
    for entry in filters.get("locations", []):
        flags = []
        if entry.get("requires_sponsorship"):
            flags.append("sponsorship required")
        if entry.get("allows_relocation"):
            flags.append("relocation possible")
        if entry.get("remote_from_home"):
            flags.append(f"remote from home: {entry['remote_from_home']}")
        suffix = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"- **{entry['place']}** - {entry['mode']}{suffix}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", help="persona slug (default: the active persona)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--limit", type=int, default=12, help="maximum queries to emit")
    parser.add_argument(
        "--out",
        type=Path,
        help="write the output to this file instead of stdout",
    )
    args = parser.parse_args()

    persona_slug = args.persona or active_persona()
    known = list_personas()
    if known and persona_slug not in known:
        print(
            f"profile_query: unknown persona '{persona_slug}'. Known personas: {', '.join(known)}",
            file=sys.stderr,
        )
        return 1

    persona = load_yaml(persona_yaml(persona_slug))
    if not persona:
        print(
            f"profile_query: no persona file at {persona_yaml(persona_slug)}. "
            "Run the profile build first.",
            file=sys.stderr,
        )
        return 1
    inputs = load_yaml(profile_inputs_path())

    contract = build_contract(persona, inputs)
    contract["search_queries"] = build_queries(persona, inputs, limit=args.limit)

    if args.format == "markdown":
        rendered = render_markdown(contract)
    else:
        rendered = json.dumps(contract, ensure_ascii=False, indent=2)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(f"saved={args.out}")
    elif args.format == "markdown":
        print(rendered, end="")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
