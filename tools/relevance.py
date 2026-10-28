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
    """
    roles: list[tuple[str, float]] = []
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
    preferences = inputs.get("preferences", {}) or {}
    for entry in preferences.get("locations", []) or []:
        if not isinstance(entry, dict):
            continue
        for key in ("region", "city", "country"):
            value = entry.get(key)
            if value:
                for phrase in _phrases(value):
                    locations.append((phrase, 6.0))

    return {
        "roles": roles,
        "skills": skills,
        "locations": locations,
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
    for phrase, weight in terms.get("skills", []):
        if phrase in title:
            total += weight * 0.6
        elif phrase in body:
            total += weight * 0.25
    if any(phrase in title for phrase, _ in terms.get("skills", [])):
        reasons.append("a persona skill appears in the title")

    for phrase, weight in terms.get("locations", []):
        if phrase in location or phrase in title:
            total += weight
            reasons.append(f"location '{phrase}' matches")
            break

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
