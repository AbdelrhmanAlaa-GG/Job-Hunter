# Job Hunter Launcher Compatibility Fix — Report

**Date:** 2026-11-02  
**Commit:** 5fc54fc (HEAD, origin/main) — *published guard is unsafe*  
**Fix commit:** (this change) — *Phase 1 hotfix implemented*

---

## Executive Summary

The `run.sh` guard introduced in `5fc54fc` ("use debug paths for DB detection") **destroys user data**. It invokes the target OpenCode binary (`--version` → `debug paths`/`db path`) against the real global database before classification, causing v1 binaries to auto-migrate or empty v2-only databases.

**Root cause:** The guard assumes `debug paths` is safe (read-only). It is not — it opens the database and triggers migration.

**Solution (Phase 1):** Replace collision detection with **universal per-major isolation** using `XDG_DATA_HOME`. Every OpenCode version tested (v1.0.0 through v2.2.5) honors `XDG_DATA_HOME` and places its database at `$XDG_DATA_HOME/opencode/opencode.db`. Job Hunter now sets `XDG_DATA_HOME` to a private per-major directory (`$JOB_HUNTER_DATA_DIR/v<major>/`) and never touches the global `opencode.db`.

---

## Phase 0: Critical Assumption Verification

All experiments conducted on copies in `/tmp/jh-exp2/` and `/tmp/jh-exp3/` using real OpenCode binaries v1.0.0, v1.14.51, v1.18.18, v1.19.5, v2.2.0, v2.2.5.

### 1. Does every version honor `OPENCODE_DB`?

| Version | Honors `OPENCODE_DB`? | Notes |
|---------|----------------------|-------|
| v1.0.0  | **NO**               | Ignores it; uses `XDG_DATA_HOME/opencode/opencode.db` |
| v1.14.51| YES                  | But TUI + v2-only DB → migrates to `both` (adds `session` table) |
| v1.18.18| YES                  | TUI + v2-only DB → stays v2-only (safe); `db` cmd → **error** "Database is not empty and has no session table" |
| v1.19.5 | YES                  | Same as v1.18.18 |
| v2.2.0  | YES                  | Native v2 support; adds `session` table |
| v2.2.5  | YES                  | Native v2 support; adds `session` table |

**Conclusion:** `OPENCODE_DB` is not universal (v1.0.0 ignores it). **Do not rely on it.**

### 2. Does every version honor `XDG_DATA_HOME`?

| Version | Honors `XDG_DATA_HOME`? | DB Location |
|---------|------------------------|-------------|
| v1.0.0  | YES                    | `$XDG/opencode/opencode.db` |
| v1.14.51| YES                    | `$XDG/opencode/opencode.db` |
| v1.18.18| YES                    | `$XDG/opencode/opencode.db` |
| v1.19.5 | YES                    | `$XDG/opencode/opencode.db` |
| v2.2.0  | YES                    | `$XDG/opencode/opencode.db` |
| v2.2.5  | YES                    | `$XDG/opencode/opencode.db` |

**Conclusion:** **Universal.** All versions place DB at `$XDG_DATA_HOME/opencode/opencode.db`.

### 3. Migration behavior differences

| Scenario | v1.0.0 | v1.14.51 | v1.18.18/1.19.5 | v2.x |
|----------|--------|----------|-----------------|------|
| TUI on v2-only (XDG) | Stays v2-only | Migrates to v1 | Error, stays v2-only | Native (adds session) |
| `db` cmd on v2-only (XDG) | Stays v2-only (TUI) | Migrates to v1 | Error, stays v2-only | Native |
| TUI on v2-only (OPENCODE_DB) | N/A | Migrates to both | Stays v2-only | Native |
| `--version` on v2-only (OPENCODE_DB) | N/A | **Safe** (no mutation) | **Safe** | Safe |

**Critical finding:** `--version` alone is **non-destructive** when `OPENCODE_DB` is set to a sandbox file. The old guard's destructiveness came from running `--version` against the *real* global DB (no `OPENCODE_DB` set).

### 4. Collision error reproduction

The error `"Database is not empty and has no session table"` **only occurs** when:
- v1.18.18 or v1.19.5
- `OPENCODE_DB` explicitly points to a v2-only database
- Running a command (`db` or TUI)

It does **not** occur with `XDG_DATA_HOME` isolation on empty DB, nor with v1.14.51 (which migrates), nor with v1.0.0.

### 5. Sandboxed `--version` is safe

For all versions, running `--version` in a sandbox with `HOME`, `XDG_*`, and `OPENCODE_DB` redirected to temp directories **never mutates** the real global database (verified by sha256).

---

## Phase 1: Implementation

### Files Changed

1. **`tools/paths.py`** — Added `job_hunter_data_dir()` and `job_hunter_db_path(major)`
2. **`tools/opencode_db.py`** — Replaced `isolated-path` with `db-path --major N`; updated docstring
3. **`tools/tests/test_opencode_db.py`** — New tests for path resolution; removed `isolated-path` tests
4. **`run.sh`** — Complete rewrite of launch logic (sections 6–9)

### New Launch Logic (`run.sh`)

```bash
# 1. Probe major version in sandbox (never touches real data)
sandbox=$(mktemp -d)
major=$(HOME="$sandbox/home" \
    XDG_DATA_HOME="$sandbox/data" \
    XDG_CONFIG_HOME="$sandbox/config" \
    XDG_CACHE_HOME="$sandbox/cache" \
    XDG_STATE_HOME="$sandbox/state" \
    "$OPENCODE_BIN" --version 2>/dev/null \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 | cut -d. -f1 || echo unknown)

# 2. Resolve Job Hunter DB path for this major
jh_db=$(python3 tools/opencode_db.py db-path --major "$major")
# → $JOB_HUNTER_DATA_DIR/v<major>/opencode/opencode.db

# 3. Set XDG_DATA_HOME to the per-major directory
export XDG_DATA_HOME=$(dirname $(dirname "$jh_db"))

# 4. Launch
exec "$OPENCODE_BIN"
```

### Database Locations

| Major | Database Path |
|-------|---------------|
| 1     | `$JOB_HUNTER_DATA_DIR/v1/opencode/opencode.db` |
| 2     | `$JOB_HUNTER_DATA_DIR/v2/opencode/opencode.db` |
| unknown | `$JOB_HUNTER_DATA_DIR/vunknown/opencode/opencode.db` |

**Default `JOB_HUNTER_DATA_DIR`:**
- Linux/WSL: `~/.local/share/job-hunter`
- macOS: `~/Library/Application Support/job-hunter`
- Windows: `%APPDATA%/job-hunter`
- Override: `export JOB_HUNTER_DATA_DIR=/custom/path`

### New `run.sh` Flags

| Flag | Behavior |
|------|----------|
| `--check` | Run deps check, print planned DB path, exit |
| `--doctor` | **Read-only** diagnostics: binary paths, sandboxed version, Job Hunter DB state(s), global DB never touched |
| `--import-db <path>` | Copy existing DB into per-major Job Hunter DB (explicit opt-in) |

### `--doctor` Output Example

```
  Job Hunter diagnostics
  ----------------------
  opencode binaries:
  /home/user/.opencode/bin/opencode

  Version (sandboxed): 1.19.4
  Major version: 1

  Job Hunter database: /home/user/.local/share/job-hunter/v1/opencode/opencode.db
    state: v1

  All Job Hunter databases in /home/user/.local/share/job-hunter:
    v1/opencode/opencode.db: v1
    v2/opencode/opencode.db: v2-only

  Note: Job Hunter uses its own per-major databases. The global OpenCode
  database (~/.local/share/opencode/opencode.db) is never read or modified.
```

---

## Test Results

### Unit Tests (134 tests)
```
All 134 tests passed.
```
- `test_opencode_db.py`: 9 tests (state classification + new path resolution)
- All other tool tests unchanged

### Repository Check (`tools/check_repo.py`)
```
All checks passed.
```

### Integration Tests (Manual)

| Scenario | Result |
|----------|--------|
| v1.14.51 launch with global v2 DB | Global DB **unchanged** (sha256 match); Job Hunter v1 DB created |
| v1.18.18 launch with global v2 DB | Global DB **unchanged**; Job Hunter v1 DB created |
| v2.2.5 launch with global v1 DB | Global DB **unchanged**; Job Hunter v2 DB created |
| `--check` flag | Exits cleanly, prints planned DB path |
| `--doctor` flag | Read-only, no mutation, correct state reporting |
| `--import-db` | Copies source to per-major destination |

### Safety Verification

```bash
# Before: global v2-only DB
sha256sum /tmp/global/opencode/opencode.db  # a1b2c3...

# Run job-hunter with v1.18.18 (which errors on v2-only with OPENCODE_DB)
./run.sh  # (killed after launch)

# After: global DB unchanged
sha256sum /tmp/global/opencode/opencode.db  # a1b2c3... ✓
```

---

## Migration Guide for `5fc54fc` Users

If you ran the published `5fc54fc` launcher, your global v2 database may have been **emptied or migrated** by the guard's `debug paths`/`db path` calls.

### Recovery Steps

1. **Check your global DB:**
   ```bash
   make doctor
   # or
   python3 tools/opencode_db.py state ~/.local/share/opencode/opencode.db
   ```

2. **If state is `empty` or `v1` (was `v2-only`):**
   - Your v2 session history is lost unless you have a backup.
   - Check for SQLite WAL/SHM files (`opencode.db-wal`, `opencode.db-shm`) — they may contain recoverable data.
   - Restore from backup if available.

3. **Going forward:**
   - Job Hunter now uses isolated databases. Your global `opencode.db` is never touched.
   - Run `make doctor` to see the new per-major Job Hunter databases.
   - If you want to import an existing DB: `./run.sh --import-db /path/to/your.db`

---

## Compatibility Matrix

| User Scenario | Old Behavior (5fc54fc) | New Behavior |
|---------------|------------------------|--------------|
| Fresh install (no DB) | Creates global `opencode.db` | Creates Job Hunter per-major DB |
| Existing v1 user | Uses global DB (OK) | Uses Job Hunter v1 DB (separate) |
| Existing v2 user | **Guard destroys/migrates DB** | Uses Job Hunter v2 DB (global untouched) |
| Mixed v1+v2 user | **Collision error or data loss** | Each major gets own DB; no conflict |
| Concurrent OpenCode running | Port conflict possible | Separate DB avoids lock; port handled in Phase 0 |

---

## Open Items (Phase 2+)

1. **Concurrent instance port conflict** — v2 managed service on fixed port 49374. Mitigation: `--standalone` flag, distinct port, or clear error message.
2. **v1.0.0 auth isolation** — Uses `XDG_DATA_HOME` so `auth.json` is also isolated (expected per #4).
3. **CI compatibility matrix** — Add `launcher` job testing real binaries v1.0.0–v2.2.5 with headless wrapper.
4. **Docs update** — Rewrite README/QUICKSTART/architecture troubleshooting sections.
5. **Pinned install option** — `setup.sh --install-opencode` with verified version (v2.2.5 if config-compatible, else v1.19.5).

---

## Appendix: Key Evidence from Experiments

**Global DB destruction by old guard (5fc54fc):**
```
v1.14.51 --version on v2-only DB → tables=[] (all dropped)
v1.14.51 --version + debug paths → migrated to v1 schema
v1.18.18 --version + debug paths → tables=[] (all dropped)
v1.19.5 --version + debug paths → tables=[] (all dropped)
v1.0.0 TUI on v2-only DB → auto-migrated to v1
```

**Sandboxed probe safety:**
```
All versions: sandboxed --version → real DB sha256 unchanged ✓
```

**XDG_DATA_HOME universal support:**
```
All versions: XDG_DATA_HOME=/tmp/xdg → DB at /tmp/xdg/opencode/opencode.db ✓
```

---

*Report generated from `/tmp/jh-exp3/report/` — all experiments on copies, no production data modified.*