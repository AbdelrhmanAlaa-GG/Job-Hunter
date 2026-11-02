"""Tests for tools/opencode_db.py."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from opencode_db import state
from paths import job_hunter_data_dir, job_hunter_db_path


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
        sqlite3.connect(p).close()
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


class TestJobHunterPaths(unittest.TestCase):
    def test_job_hunter_data_dir_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom-jh-data"
            with patch.dict(os.environ, {"JOB_HUNTER_DATA_DIR": str(custom)}):
                self.assertEqual(job_hunter_data_dir(), custom.resolve())

    def test_job_hunter_db_path_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "jh-data"
            with patch.dict(os.environ, {"JOB_HUNTER_DATA_DIR": str(custom)}):
                db_path = job_hunter_db_path(1)
                expected = custom / "v1" / "opencode" / "opencode.db"
                self.assertEqual(db_path, expected)

    def test_job_hunter_db_path_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "jh-data"
            with patch.dict(os.environ, {"JOB_HUNTER_DATA_DIR": str(custom)}):
                db_path = job_hunter_db_path(2)
                expected = custom / "v2" / "opencode" / "opencode.db"
                self.assertEqual(db_path, expected)

    def test_job_hunter_db_path_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "jh-data"
            with patch.dict(os.environ, {"JOB_HUNTER_DATA_DIR": str(custom)}):
                db_path = job_hunter_db_path(1)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self.assertTrue(db_path.parent.exists())


if __name__ == "__main__":
    unittest.main()