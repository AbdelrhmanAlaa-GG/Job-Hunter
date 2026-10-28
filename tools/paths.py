"""Central path resolution for Job Hunter.

Every tool that touches the filesystem resolves its paths through this module so
the layout is defined in exactly one place.

A *persona* is one search identity: a resume variant aimed at a role family,
plus the preferences that apply to it. A persona is a directory. The active
persona is chosen by the ``JOB_HUNTER_PERSONA`` environment variable, falling
back to ``profiles/index.json`` and then to ``default``.

Layout (see docs/architecture.md):

    resumes/                      user-supplied resume files (gitignored)
    resumes/extracted/            extracted-text cache (gitignored)
    profiles/inputs.yaml          user-authored preferences (gitignored)
    profiles/index.json           persona registry (gitignored)
    profiles/<persona>/profile.yaml   derived facts with provenance (gitignored)
    profiles/<persona>/PROFILE.md     generated aggregate (gitignored)
    profiles/<persona>/state/         per-persona job state (gitignored)
    reports/<persona>/                generated reports (gitignored)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PERSONA = "default"

ENV_VAR = "JOB_HUNTER_PERSONA"


def personas_dir() -> Path:
    """Return the directory holding persona data."""
    return ROOT / "profiles"


def profile_index_path() -> Path:
    """Return the persona registry."""
    return personas_dir() / "index.json"


def profile_inputs_path() -> Path:
    """Return the user-authored inputs file."""
    return personas_dir() / "inputs.yaml"


def list_personas() -> list[str]:
    """Return every known persona slug, sorted.

    Reads the registry first and falls back to the directory listing so a
    persona works even before the registry has been written.
    """
    index = profile_index_path()
    if index.exists():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            known = data.get("personas")
            if isinstance(known, dict) and known:
                return sorted(known)
            if isinstance(known, list) and known:
                return sorted(str(item) for item in known)
        except (OSError, json.JSONDecodeError):
            pass
    if personas_dir().is_dir():
        found = sorted(
            path.name
            for path in personas_dir().iterdir()
            if path.is_dir() and (path / "profile.yaml").exists()
        )
        if found:
            return found
    return []


def active_persona() -> str:
    """Return the persona slug this invocation operates on.

    Resolution order: the environment variable, then ``active_persona`` in the
    registry, then ``default``. Never a guess across multiple personas - the
    caller is expected to have selected one explicitly.
    """
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env
    index = profile_index_path()
    if index.exists():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            stored = data.get("active_persona")
            if isinstance(stored, str) and stored.strip():
                return stored.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_PERSONA


def persona_dir(persona: str | None = None) -> Path:
    """Return ``profiles/<persona>``."""
    return personas_dir() / (persona or active_persona())


def persona_yaml(persona: str | None = None) -> Path:
    """Return the persona's derived-facts file."""
    return persona_dir(persona) / "profile.yaml"


def profile_file(persona: str | None = None) -> Path:
    """Return the persona's generated profile aggregate."""
    return persona_dir(persona) / "PROFILE.md"


def state_dir(persona: str | None = None) -> Path:
    """Return the persona's state directory."""
    return persona_dir(persona) / "state"


def seen_jobs_path(persona: str | None = None) -> Path:
    """Return the persona's seen-jobs store."""
    return state_dir(persona) / "seen_jobs.json"


def tracker_path(persona: str | None = None) -> Path:
    """Return the persona's application tracker."""
    return state_dir(persona) / "tracker.csv"


def search_queries_path(persona: str | None = None) -> Path:
    """Return the persona's generated search-queries file."""
    return state_dir(persona) / "search-queries.md"


def scratch_dir(persona: str | None = None) -> Path:
    """Return the persona's scratch directory for run intermediates."""
    return state_dir(persona) / "scratch"


def reports_dir(persona: str | None = None) -> Path:
    """Return the persona's report output directory."""
    return ROOT / "reports" / (persona or active_persona())


def resumes_dir() -> Path:
    """Return the directory holding user resumes."""
    return ROOT / "resumes"


def extracted_dir() -> Path:
    """Return the extracted-text cache directory."""
    return resumes_dir() / "extracted"


def ensure_persona_dirs(persona: str | None = None) -> None:
    """Create the directories a run needs. Safe to call repeatedly."""
    for directory in (state_dir(persona), scratch_dir(persona), reports_dir(persona), extracted_dir()):
        directory.mkdir(parents=True, exist_ok=True)


__all__ = [
    "ROOT",
    "DEFAULT_PERSONA",
    "ENV_VAR",
    "personas_dir",
    "profile_index_path",
    "profile_inputs_path",
    "list_personas",
    "active_persona",
    "persona_dir",
    "persona_yaml",
    "profile_file",
    "state_dir",
    "seen_jobs_path",
    "tracker_path",
    "search_queries_path",
    "scratch_dir",
    "reports_dir",
    "resumes_dir",
    "extracted_dir",
    "ensure_persona_dirs",
]
