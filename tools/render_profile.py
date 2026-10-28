"""Render the generated profile aggregate for a persona.

The aggregate (``profiles/<persona>/PROFILE.md``) is a **view**, not a source
of truth. It is regenerated from three files:

    profiles/<persona>/profile.yaml   derived facts, each with its evidence
    profiles/inputs.yaml               the user's own preferences
    profiles/index.json                the persona registry

Everything the user writes into the aggregate lives under the ``## User Notes``
heading. That section is preserved verbatim across regeneration, so the file
can be both generated and editable without the two fighting each other.

Usage:
    python3 tools/render_profile.py --persona ai-llm-rag
    python3 tools/render_profile.py --persona ai-llm-rag --check
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import (  # noqa: E402
    active_persona,
    list_personas,
    persona_yaml,
    profile_file,
    profile_inputs_path,
)

try:
    import yaml
except ImportError:
    print("render_profile: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

USER_NOTES_HEADING = "## User Notes"

GENERATED_BANNER = (
    "<!-- GENERATED FILE - the sections below are rebuilt from your resumes and\n"
    "     your inputs. Edit the files listed under \"Sources\" instead. The one\n"
    "     exception is the \"User Notes\" section at the bottom, which is\n"
    "     preserved exactly as you write it. -->"
)


def load_yaml(path: Path) -> dict:
    """Load a YAML document, returning an empty dict when the file is absent."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_user_notes(path: Path) -> str:
    """Return the User Notes section of an existing aggregate, if any.

    The last occurrence of the heading wins, and the section runs to the end
    of the file. Taking the last occurrence means an edit that appends a
    second copy of the heading is not silently ignored, and running to the end
    means anything the user adds below the heading survives a rebuild.
    """
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if USER_NOTES_HEADING not in text:
        return ""
    tail = text.rsplit(USER_NOTES_HEADING, 1)[1]
    body = tail.strip("\n")
    if not body.strip():
        return ""
    return body


def value_of(entry) -> str:
    """Return the readable value from either a scalar or a {value: ...} map."""
    if isinstance(entry, dict):
        return str(entry.get("value", "")).strip()
    return str(entry).strip()


def source_of(entry) -> str:
    """Return the evidence string from a {value, source} map."""
    if isinstance(entry, dict):
        return str(entry.get("source", "")).strip()
    return ""


def render(persona: dict, inputs: dict, index: dict, user_notes: str) -> str:
    """Render the aggregate Markdown for a persona."""
    slug = persona.get("persona", "")
    title = persona.get("title", "")
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        f"# Job Hunter Profile - {title or slug}",
        "",
        GENERATED_BANNER,
        "",
        f"- **Persona:** `{slug}`",
        f"- **Active persona:** `{index.get('active_persona', '')}`",
        f"- **Built:** {built_at}",
        "",
        "## Sources",
        "",
        "| File | Role | Editable by you |",
        "|---|---|---|",
        f"| `profiles/{slug}/profile.yaml` | Resume-derived facts, with evidence | No - rebuilt from your resumes |",
        "| `profiles/inputs.yaml` | Your preferences, locations, dealbreakers | **Yes** |",
        "| `profiles/index.json` | Persona registry | Rarely |",
        "",
        "## Resumes",
        "",
    ]

    resumes = persona.get("resumes", []) or []
    if resumes:
        lines.append("| Slug | File | SHA-256 | Extracted text |")
        lines.append("|---|---|---|---|")
        for resume in resumes:
            digest = str(resume.get("sha256", ""))[:12]
            lines.append(
                f"| `{resume.get('slug', '')}` | `{resume.get('file', '')}` | `{digest}` | "
                f"`{resume.get('extracted_text', '')}` |"
            )
    else:
        lines.append("_No resume linked to this persona yet._")

    lines.extend(["", "## Target roles", ""])
    for role in persona.get("target_roles", []) or []:
        rationale = " ".join(str(role.get("rationale", "")).split())
        lines.append(f"- **{role.get('title', '')}** (priority {role.get('priority', '?')}) - {rationale}")

    lines.extend(["", "## Skills", ""])
    for weight, label in (("primary", "Primary"), ("secondary", "Secondary"), ("weak", "Present but not a differentiator")):
        names = [
            str(skill.get("name", ""))
            for skill in persona.get("skills", []) or []
            if skill.get("weight") == weight
        ]
        if names:
            lines.append(f"- **{label}:** {', '.join(names)}")

    identity = persona.get("identity", {}) or {}
    name = value_of(identity.get("name", ""))
    location = value_of(identity.get("location", ""))
    headline = value_of(identity.get("headline", ""))
    if name or location:
        lines.extend(["", "## Identity", ""])
        if name:
            lines.append(f"- **Name:** {name}")
        if location:
            lines.append(f"- **Location:** {location}")
        if headline:
            lines.append(f"- **Headline:** {headline}")

    education = [value_of(item) for item in persona.get("education", []) or []]
    if education:
        lines.extend(["", "## Education", ""])
        for item in education:
            lines.append(f"- {item}")
    experience = [value_of(item) for item in persona.get("experience", []) or []]
    if experience:
        lines.extend(["", "## Experience", ""])
        for item in experience:
            lines.append(f"- {item}")

    evidence = persona.get("evidence_bullets", []) or []
    if evidence:
        lines.extend(["", "## Evidence", "", "Claims a report may quote. Each is backed by a line of your resume.", ""])
        for bullet in evidence:
            text = " ".join(str(bullet.get("text", "")).split())
            source = source_of(bullet)
            lines.append(f"- {text}  _(source: `{source}`)_")

    projects = persona.get("projects", []) or []
    if projects:
        lines.extend(["", "## Projects", ""])
        for project in projects:
            lines.append(f"- **{project.get('name', '')}** - {project.get('detail', '')}")

    preferences = inputs.get("preferences", {}) or {}
    seniority = preferences.get("seniority", {}) or {}
    lines.extend(["", "## Preferences", ""])
    lines.append(f"- **Seniority sought:** {', '.join(str(token) for token in seniority.get('include', []) or [])}")
    lines.append(f"- **Seniority refused:** {', '.join(str(token) for token in seniority.get('exclude', []) or [])}")
    work_auth = str(preferences.get("work_authorization", "") or "")
    if work_auth:
        lines.append(f"- **Work authorization:** {' '.join(work_auth.split())}")

    locations = preferences.get("locations", []) or []
    if locations:
        lines.extend(["", "## Locations", "", "| Region | Mode | Notes |", "|---|---|---|"])
        for location_entry in locations:
            if not isinstance(location_entry, dict):
                continue
            lines.append(
                f"| {location_entry.get('region', '')} | {location_entry.get('mode', '')} | "
                f"{location_entry.get('note', '')} |"
            )

    dealbreakers = inputs.get("dealbreakers", []) or []
    if dealbreakers:
        lines.extend(["", "## Dealbreakers", ""])
        for item in dealbreakers:
            lines.append(f"- {item}")

    persona_exclusions = persona.get("persona_exclusions", []) or []
    if persona_exclusions:
        lines.extend(["", "## Excluded by this persona", ""])
        for entry in persona_exclusions:
            reason = str(entry.get("reason", ""))
            source = source_of(entry)
            lines.append(f"- {reason}" + (f"  _(source: `{source}`)_" if source else ""))

    conflicts = persona.get("conflicts", []) or []
    if conflicts:
        lines.extend(["", "## Conflicts", "", "These need your decision.", ""])
        for conflict in conflicts:
            lines.append(f"- **{conflict.get('field', '')}**: {conflict.get('detail', '')}")
    else:
        lines.extend(["", "## Conflicts", "", "_None - every source resume agrees on the facts it states._"])

    lines.extend(["", USER_NOTES_HEADING, ""])
    if user_notes:
        lines.append(user_notes)
    else:
        lines.append("_Nothing here yet. Anything you write in this section is preserved when the")
        lines.append("profile is rebuilt._")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", help="persona slug (default: the active persona)")
    parser.add_argument("--check", action="store_true", help="report staleness without writing")
    args = parser.parse_args()

    slug = args.persona or active_persona()
    known = list_personas()
    if known and slug not in known:
        print(f"render_profile: unknown persona '{slug}'. Known: {', '.join(known)}", file=sys.stderr)
        return 1

    persona = load_yaml(persona_yaml(slug))
    if not persona:
        print(f"render_profile: no persona file at {persona_yaml(slug)}", file=sys.stderr)
        return 1
    inputs = load_yaml(profile_inputs_path())
    index_path = Path(__file__).resolve().parent.parent / "profiles" / "index.json"
    index = {}
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}

    target = profile_file(slug)
    content = render(persona, inputs, index, read_user_notes(target))

    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        stale = current != content
        print(json.dumps({"persona": slug, "path": str(target), "stale": stale}, ensure_ascii=False))
        return 1 if stale else 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(json.dumps({"persona": slug, "written": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
