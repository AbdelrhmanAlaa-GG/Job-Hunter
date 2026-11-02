#!/usr/bin/env python3
"""Inspect an OpenCode SQLite database and classify its schema.

States:
  missing   - file does not exist
  empty     - no user tables (only sqlite_*)
  v1        - has 'session' table, no 'session_v2'
  v2-only   - has 'session_v2' but NO 'session' (v1 binary will crash)
  both      - has both 'session' and 'session_v2' (v1 binary works)

This module provides read-only database inspection and Job Hunter
database path resolution. It no longer performs collision detection;
run.sh now uses per-major isolated databases via XDG_DATA_HOME.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from paths import job_hunter_db_path


def state(path: Path) -> str:
    """Return the schema state of the database at path."""
    if not path.exists():
        return "missing"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return "missing"
    try:
        cur = con.cursor()
        tables = {r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        con.close()
    except Exception:
        return "missing"

    has_session = "session" in tables
    has_v2 = "session_v2" in tables

    if not has_session and not has_v2:
        return "empty"
    if has_session and not has_v2:
        return "v1"
    if not has_session and has_v2:
        return "v2-only"
    return "both"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_state = sub.add_parser("state", help="print schema state (missing|empty|v1|v2-only|both)")
    p_state.add_argument("path", type=Path)

    p_db_path = sub.add_parser("db-path", help="print Job Hunter database path for major version")
    p_db_path.add_argument("--major", type=int, required=True, choices=[1, 2])

    args = parser.parse_args()

    if args.cmd == "state":
        print(state(args.path))
        return 0
    if args.cmd == "db-path":
        print(job_hunter_db_path(args.major))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())