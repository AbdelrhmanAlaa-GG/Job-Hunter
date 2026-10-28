"""Validate a persona, refresh the registry, and rebuild the profile aggregate.

The semantic part of building a profile - reading a resume and deciding which
skills and roles it supports - is done by the model and lands in
``profiles/<persona>/profile.yaml``. This tool does the mechanical part:

    validate   the persona file's shape and every fact's provenance
    freshness  whether each resume on disk still matches the recorded hash
    registry   write profiles/index.json
    aggregate  regenerate profiles/<persona>/PROFILE.md

Usage:
    python3 tools/profile_build.py --persona ai-llm-rag --check
    python3 tools/profile_build.py --persona ai-llm-rag --finalize

Exit codes:
    0 - valid, and (with --finalize) written
    1 - invalid persona, or a resume that no longer matches its hash
    2 - bad usage
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import (  # noqa: E402
    ROOT,
    active_persona,
    list_personas,
    persona_dir,
    persona_yaml,
    profile_file,
    profile_index_path,
    profile_inputs_path,
)

try:
    import yaml
except ImportError:
    print("profile_build: PyYAML is required. Install it with: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

VALID_WEIGHTS = {"primary", "secondary", "weak"}


def load_yaml(path: Path) -> dict:
    """Load a YAML document, returning an empty dict when the file is absent."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def sha256_of(path: Path) -> str:
    """Return the hex sha256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(persona: dict, slug: str) -> list[str]:
    """Return the list of problems in a persona file. Empty means valid."""
    problems: list[str] = []

    if not persona:
        return [f"persona file is empty or missing (expected {persona_yaml(slug)})"]

    declared = persona.get("persona")
    if declared != slug:
        problems.append(f"persona key is {declared!r} but the file is for {slug!r}")
    if not persona.get("title"):
        problems.append("missing title")

    resumes = persona.get("resumes")
    if not isinstance(resumes, list) or not resumes:
        problems.append("missing resumes list")
    else:
        for index, resume in enumerate(resumes):
            if not isinstance(resume, dict):
                problems.append(f"resumes[{index}] is not a mapping")
                continue
            for field in ("slug", "file", "sha256"):
                if not resume.get(field):
                    problems.append(f"resumes[{index}] is missing {field}")

    skills = persona.get("skills")
    if not isinstance(skills, list) or not skills:
        problems.append("missing skills list")
    else:
        for index, skill in enumerate(skills):
            if not isinstance(skill, dict):
                problems.append(f"skills[{index}] is not a mapping")
                continue
            if not skill.get("name"):
                problems.append(f"skills[{index}] is missing name")
            weight = skill.get("weight")
            if weight not in VALID_WEIGHTS:
                problems.append(f"skills[{index}] ({skill.get('name')}) has invalid weight {weight!r}")
            if not skill.get("evidence"):
                problems.append(f"skills[{index}] ({skill.get('name')}) has no evidence")

    roles = persona.get("target_roles")
    if not isinstance(roles, list) or not roles:
        problems.append("missing target_roles list")
    else:
        for index, role in enumerate(roles):
            if not isinstance(role, dict):
                problems.append(f"target_roles[{index}] is not a mapping")
                continue
            if not role.get("title"):
                problems.append(f"target_roles[{index}] is missing title")
            if not isinstance(role.get("priority"), int):
                problems.append(f"target_roles[{index}] ({role.get('title')}) needs an integer priority")

    bullets = persona.get("evidence_bullets", [])
    if bullets:
        for index, bullet in enumerate(bullets):
            if not isinstance(bullet, dict):
                problems.append(f"evidence_bullets[{index}] is not a mapping")
                continue
            if not bullet.get("text"):
                problems.append(f"evidence_bullets[{index}] is missing text")
            if not bullet.get("source"):
                problems.append(f"evidence_bullets[{index}] is missing source")

    return problems


def check_freshness(persona: dict) -> tuple[list[dict], list[str]]:
    """Compare each resume on disk with its recorded hash.

    Returns (status rows, problems). A resume whose hash no longer matches is
    stale: the persona was built from an older version of it.
    """
    rows: list[dict] = []
    problems: list[str] = []
    for resume in persona.get("resumes", []) or []:
        if not isinstance(resume, dict):
            continue
        relative = str(resume.get("file", ""))
        recorded = str(resume.get("sha256", ""))
        path = ROOT / relative if relative else None
        if not path or not path.exists():
            rows.append({"slug": resume.get("slug", ""), "file": relative, "state": "missing"})
            problems.append(f"resume file not found: {relative}")
            continue
        actual = sha256_of(path)
        state = "current" if actual == recorded else "stale"
        rows.append({"slug": resume.get("slug", ""), "file": relative, "state": state, "sha256": actual})
        if state == "stale":
            problems.append(
                f"resume changed since the profile was built: {relative} "
                "(re-run the profile build to refresh it)"
            )
    return rows, problems


def write_registry(slug: str, persona: dict, inputs: dict) -> Path:
    """Write profiles/index.json with this persona registered and active."""
    index_path = profile_index_path()
    index: dict = {}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                index = loaded
        except (OSError, json.JSONDecodeError):
            index = {}

    personas = index.get("personas")
    if not isinstance(personas, dict):
        personas = {}

    resumes = persona.get("resumes", []) or []
    personas[slug] = {
        "file": f"profiles/{slug}/profile.yaml",
        "title": persona.get("title", ""),
        "resumes": [resume.get("slug", "") for resume in resumes if isinstance(resume, dict)],
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    index["schema_version"] = 1
    index["personas"] = personas
    index["active_persona"] = slug
    index["inputs"] = "profiles/inputs.yaml"

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", help="persona slug (default: the active persona)")
    parser.add_argument("--check", action="store_true", help="validate and report only")
    parser.add_argument("--finalize", action="store_true", help="validate, then write registry and aggregate")
    args = parser.parse_args()

    if not args.check and not args.finalize:
        parser.error("choose --check or --finalize")

    slug = args.persona or active_persona()
    known = list_personas()
    if known and slug not in known:
        print(f"profile_build: unknown persona '{slug}'. Known: {', '.join(known)}", file=sys.stderr)
        return 1

    persona = load_yaml(persona_yaml(slug))
    problems = validate(persona, slug)
    freshness, fresh_problems = check_freshness(persona)
    problems.extend(fresh_problems)

    inputs = load_yaml(profile_inputs_path())
    if not inputs:
        problems.append(f"no user inputs at {profile_inputs_path()}")

    result = {
        "persona": slug,
        "valid": not problems,
        "problems": problems,
        "resumes": freshness,
        "skills": len(persona.get("skills", []) or []),
        "target_roles": len(persona.get("target_roles", []) or []),
    }

    if args.finalize and not problems:
        registry = write_registry(slug, persona, inputs)
        result["registry"] = str(registry)
        # The aggregate is rendered by a separate tool so the rendering stays
        # a pure function of the three source files.
        import subprocess

        render = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "render_profile.py"), "--persona", slug],
            capture_output=True,
            text=True,
        )
        if render.returncode != 0:
            problems.append(f"render_profile failed: {render.stderr.strip()}")
            result["valid"] = False
        else:
            result["aggregate"] = str(profile_file(slug))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
