#!/usr/bin/env python3
"""Order postings by how well they fit the persona, with no model involved.

The persona's target roles, its skills and the user's location preferences
become keyword weights; each posting is scored against them. Senior postings
are pushed down and junior ones pulled up, because a persona aimed at junior
roles should not have its review budget spent on a staff posting.

This decides *which* postings are worth the model scoring. The model still
decides how well each one actually fits - this only decides the order they
are presented in, so that a run with a tight ``--limit`` spends its budget on
the most promising postings first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from location_gate import home_place, location_entries  # noqa: E402
from places import load_catalogue  # noqa: E402

# Words that mark a posting as above the seniority this project targets.
SENIOR_MARKERS = (
    "senior",
    "lead",
    "staff",
    "principal",
    "head of",
    "director",
    "vp ",
    "sr.",
    "sr ",
    "iii",
    "manager",
)

# Words that mark a posting as within reach of a junior candidate.
JUNIOR_MARKERS = (
    "junior",
    "entry",
    "graduate",
    "new grad",
    "fresher",
    "trainee",
    "intern",
    "associate",
    "early career",
    "apprentice",
    "0-1",
    "0-2",
)

# A posting whose text is this long already carries the evidence the scorer
# needs. Anything shorter needs a detail fetch before it can be judged.
DESCRIPTION_ENOUGH = 400

# How much a location preference is worth. The place the candidate lives in
# is worth more than the others: it is the one place they can take an on-site
# job in without a visa, a sponsor or a suitcase.
LOCATION_WEIGHTS = {
    "country": 12.0,
    "region": 9.0,
    "anywhere": 2.0,
}

# The home place, where the candidate already lives.
HOME_LOCATION_WEIGHT = 16.0

# A country inside a region the user named counts for less than the region
# itself.
MEMBER_COUNTRY_FACTOR = 0.8

# A search that had to widen to a parent region is a weaker signal than an
# exact one, so it carries less weight.
WIDER_SCOPE_FACTOR = 0.75

# Words that say nothing about what a role is. "Applied AI Engineer" and "AI
# Engineer" are the same job family, and a posting that uses the shorter name
# is still a match - but a weaker one.
GENERIC_ROLE_WORDS = {"applied", "software"}

# How much a role match is worth when only the distinctive words match.
FALLBACK_ROLE_FACTOR = 0.6


def _tokens(text: str) -> list[str]:
    """Split a phrase into the words worth searching for in a job ad."""
    cleaned = re.sub(r"[^a-z0-9+#./-]+", " ", str(text or "").lower())
    words = [word.strip() for word in cleaned.split() if len(word.strip()) > 1]
    return words


def _phrases(text: str) -> list[str]:
    """Return the lower-case word sequences that make up a phrase."""
    words = _tokens(text)
    return [" ".join(words)] if words else []


def build_terms(persona: dict, inputs: dict) -> dict:
    """Build the keyword weights used to order postings.

    ``persona`` is the persona's profile.yaml content and ``inputs`` is the
    user's inputs.yaml content. Both are read for hints only - no fact here
    comes from anywhere else.

    The location block used to read ``region``, ``city`` and ``country`` from
    each preference entry, and the entries are written with ``place``. Every
    location term was therefore empty, every posting scored the same on
    location, and the postings the user had asked for were pushed out of the
    limit by the ones they had not. The place is resolved through the
    catalogue now, so a region also names the countries inside it.
    """
    roles: list[tuple[str, float]] = []
    role_fallbacks: list[tuple[set[str], float]] = []
    for role in persona.get("target_roles", []) or []:
        title = str(role.get("title", "") if isinstance(role, dict) else role)
        priority = role.get("priority", 5) if isinstance(role, dict) else 5
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 5
        # Priority 1 is the best-fitting role, so it carries the most weight.
        weight = max(2.0, 16.0 - float(priority))
        for phrase in _phrases(title):
            roles.append((phrase, weight))
        distinctive = {
            token
            for token in _tokens(title)
            if token not in GENERIC_ROLE_WORDS
        }
        if distinctive and len(distinctive) < len(_tokens(title)):
            role_fallbacks.append((distinctive, weight * FALLBACK_ROLE_FACTOR))

    skills: list[tuple[str, float]] = []
    for skill in persona.get("skills", []) or []:
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("name", ""))
        weight = str(skill.get("weight", "secondary"))
        score = 10.0 if weight == "primary" else 6.0 if weight == "secondary" else 2.0
        for phrase in _phrases(name):
            skills.append((phrase, score))
            # "retrieval-augmented generation (rag)" should also match a post
            # that only says "RAG".
            for token in _tokens(name):
                if len(token) >= 3 and token not in phrase.split():
                    skills.append((token, score * 0.6))

    locations: list[tuple[str, float]] = []
    servable: dict[str, float] = {}
    servable_names: dict[str, str] = {}

    catalogue = load_catalogue()
    entries, _defaulted = location_entries(inputs)

    for entry in entries:
        name = str(
            entry.get("place")
            or entry.get("region")
            or entry.get("city")
            or entry.get("country")
            or ""
        ).strip()
        if not name:
            continue

        resolution = catalogue.resolve(name)
        if not resolution.resolved or resolution.place is None:
            # A place the catalogue does not know still counts for something:
            # it is the user's own words, and the portal may well use them.
            for phrase in _phrases(name):
                locations.append((phrase, 6.0))
            continue

        place = resolution.place
        weight = LOCATION_WEIGHTS.get(place.key, LOCATION_WEIGHTS.get(place.kind, 6.0))
        servable[place.key] = max(servable.get(place.key, 0.0), weight)
        servable_names[place.key] = place.name

        for phrase in _phrases(place.name):
            locations.append((phrase, weight))

        # A region names its countries, so a posting in one of them counts.
        if place.kind == "region" and place.key != "anywhere":
            for code in catalogue.countries_under(place.key):
                member = catalogue.get(code)
                if member is None:
                    continue
                for phrase in _phrases(member.name):
                    locations.append((phrase, weight * MEMBER_COUNTRY_FACTOR))

    # The place the candidate lives in is one they can serve, and it is worth
    # more than the other places on the list: it is the one place they can
    # take an on-site job in without a visa, a sponsor or a suitcase.
    home = home_place(inputs, persona, catalogue)
    if home and home.get("country"):
        country = home["country"]
        servable[country] = max(servable.get(country, 0.0), HOME_LOCATION_WEIGHT)
        servable_names.setdefault(country, home.get("name") or country)
        member = catalogue.get(country)
        if member is not None:
            for phrase in _phrases(member.name):
                locations.append((phrase, HOME_LOCATION_WEIGHT))

    return {
        "roles": roles,
        "role_fallbacks": role_fallbacks,
        "skills": skills,
        "locations": locations,
        "servable": servable,
        "servable_names": servable_names,
        "senior": SENIOR_MARKERS,
        "junior": JUNIOR_MARKERS,
    }


def score(job: dict, terms: dict) -> tuple[float, list[str]]:
    """Score one posting against the terms. Returns the score and the reasons."""
    title = str(job.get("title", "") or "").lower()
    body = str(job.get("description", "") or "").lower()
    location = str(job.get("location", "") or "").lower()
    reasons: list[str] = []
    total = 0.0

    for phrase, weight in terms.get("roles", []):
        if phrase in title:
            total += weight
            reasons.append(f"role '{phrase}' in the title")
            break
    else:
        # A posting may name the role in the shorter form. "AI Engineer" is an
        # "Applied AI Engineer" - a weaker match, but the same job family.
        title_tokens = set(_tokens(title))
        for distinctive, weight in terms.get("role_fallbacks", []):
            if distinctive and distinctive.issubset(title_tokens):
                total += weight
                reasons.append("the title names the target role family")
                break
    for phrase, weight in terms.get("skills", []):
        if phrase in title:
            total += weight * 0.6
        elif phrase in body:
            total += weight * 0.25
    if any(phrase in title for phrase, _ in terms.get("skills", [])):
        reasons.append("a persona skill appears in the title")

    # The location is one signal, counted once. A posting's own location
    # string and the place the portal found it in are two ways of saying the
    # same thing, and adding them together would let one posting count its
    # location twice.
    best_location = 0.0
    location_reason = ""
    for phrase, weight in terms.get("locations", []):
        if phrase in location or phrase in title:
            if weight > best_location:
                best_location = weight
                location_reason = f"location '{phrase}' matches"

    target_key = str(job.get("target_place") or "")
    target_weight = terms.get("servable", {}).get(target_key)
    if target_weight:
        scope = str(job.get("target_scope") or "")
        effective = target_weight
        if scope and scope != "exact":
            effective *= WIDER_SCOPE_FACTOR
        if effective > best_location:
            best_location = effective
            name = terms.get("servable_names", {}).get(target_key, target_key)
            location_reason = f"the posting was found in {name}"

    if best_location:
        total += best_location
        if location_reason:
            reasons.append(location_reason)

    if any(marker in title for marker in terms.get("senior", [])):
        total -= 18.0
        reasons.append("the title is above the persona's seniority")
    if any(marker in title for marker in terms.get("junior", [])):
        total += 8.0
        reasons.append("the title is within the persona's seniority")
    elif any(marker in body for marker in terms.get("junior", [])):
        total += 3.0

    if len(body) >= DESCRIPTION_ENOUGH:
        total += 2.0
    if job.get("posted_date"):
        total += 1.0

    return round(total, 2), reasons


def order(jobs: list[dict], terms: dict) -> list[dict]:
    """Return the postings in fit order, most promising first.

    The sort is stable, so postings that score the same keep the order the
    portals returned them in.
    """
    scored = []
    for index, job in enumerate(jobs):
        value, reasons = score(job, terms)
        scored.append((-value, index, value, reasons, job))
    scored.sort(key=lambda row: (row[0], row[1]))

    ordered = []
    for _, _, value, reasons, job in scored:
        enriched = dict(job)
        enriched["relevance"] = value
        enriched["relevance_reasons"] = reasons
        ordered.append(enriched)
    return ordered


__all__ = ["build_terms", "score", "order", "DESCRIPTION_ENOUGH"]
