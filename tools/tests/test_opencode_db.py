"""Tests for tools/opencode_db.py."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from opencode_db import isolated_path, state


class TestOpencodeDBState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for f in self.tmpdir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
        self.tmpdir.rmdir()

    def _write_db(self, name: str, tables: list[str]) -> Path:
        p = self.tmpdir / name
        con = sqlite3.connect(p)
        cur = con.cursor()
        for t in tables:
            if t == "session":
                cur.execute("""
                    CREATE TABLE session (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        title TEXT NOT NULL
                    )
                """)
            elif t == "session_v2":
                cur.execute("""
                    CREATE TABLE session_v2 (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        title TEXT NOT NULL
                    )
                """)
            elif t == "other":
                cur.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()
        return p

    def test_missing(self):
        self.assertEqual(state(self.tmpdir / "nope.db"), "missing")

    def test_empty(self):
        p = self.tmpdir / "empty.db"
        sqlite3.connect(p).close()  # creates file with only sqlite_ tables
        self.assertEqual(state(p), "empty")

    def test_v1(self):
        p = self._write_db("v1.db", ["session"])
        self.assertEqual(state(p), "v1")

    def test_v2_only(self):
        p = self._write_db("v2.db", ["session_v2", "other"])
        self.assertEqual(state(p), "v2-only")

    def test_both(self):
        p = self._write_db("both.db", ["session", "session_v2", "other"])
        self.assertEqual(state(p), "both")


class TestIsolatedPath(unittest.TestCase):
    def test_v1(self):
        db = Path("/home/user/.local/share/opencode/opencode.db")
        self.assertEqual(
            isolated_path(db, 1),
            Path("/home/user/.local/share/opencode/job-hunter-v1.db")
        )

    def test_v2(self):
        db = Path("/home/user/.local/share/opencode/opencode.db")
        self.assertEqual(
            isolated_path(db, 2),
            Path("/home/user/.local/share/opencode/job-hunter-v2.db")
        )


if __name__ == "__main__":
    unittest.main()