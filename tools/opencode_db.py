#!/usr/bin/env python3
"""Inspect an OpenCode SQLite database and classify its schema.

States:
  missing   - file does not exist
  empty     - no user tables (only sqlite_*)
  v1        - has 'session' table, no 'session_v2'
  v2-only   - has 'session_v2' but NO 'session' (v1 binary will crash)
  both      - has both 'session' and 'session_v2' (v1 binary works)

This module is used by run.sh to detect the v1-over-v2 collision and
optionally switch to an isolated per-major database.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


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


def isolated_path(db_path: Path, major: int) -> Path:
    """Return an absolute sibling path for an isolated per-major database."""
    return db_path.parent / f"job-hunter-v{major}.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_state = sub.add_parser("state", help="print schema state (missing|empty|v1|v2-only|both)")
    p_state.add_argument("path", type=Path)

    p_isolated = sub.add_parser("isolated-path", help="print absolute sibling path for isolated DB")
    p_isolated.add_argument("path", type=Path)
    p_isolated.add_argument("--major", type=int, required=True, choices=[1, 2])

    args = parser.parse_args()

    if args.cmd == "state":
        print(state(args.path))
        return 0
    if args.cmd == "isolated-path":
        print(isolated_path(args.path, args.major))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())