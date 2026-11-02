#!/usr/bin/env bash
# Job Hunter launcher.
#
# Checks that everything the workflow needs is in place, installs the portal
# CLI dependencies, makes sure the output directories exist, and then starts
# OpenCode in this directory.
#
# Usage:
#   ./run.sh              start OpenCode
#   ./run.sh --check      run the checks and exit without starting OpenCode
#   ./run.sh --doctor     run checks and print OpenCode/DB diagnostics
#   ./run.sh --import-db <path>  import an existing DB into the per-major Job Hunter DB

set -euo pipefail

cd "$(dirname "$0")"

# Capture the user's opencode binary BEFORE we prepend ~/.bun/bin to PATH,
# so we don't silently switch to a different build (and thus a different
# channel database).
OPENCODE_BIN="$(command -v opencode || true)"

BUN_BIN="$HOME/.bun/bin"
[ -d "$BUN_BIN" ] && export PATH="$BUN_BIN:$PATH"

# Fall back to whatever's on PATH now if we didn't have one before.
[ -z "$OPENCODE_BIN" ] && OPENCODE_BIN="$(command -v opencode || true)"

# Use the virtual environment that setup.sh creates, so the Python
# dependencies installed there are the ones this script sees.
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . ".venv/bin/activate"
fi

# The site-scoped web searches (boards with no CLI) need a search provider.
# OpenCode's own provider covers this; without one, Exa or Parallel can be
# enabled instead. A user who has already chosen a provider is not overridden.
if [ -z "${OPENCODE_ENABLE_EXA:-}" ] && [ -z "${OPENCODE_ENABLE_PARALLEL:-}" ]; then
    export OPENCODE_ENABLE_EXA=1
fi

fail() {
    echo ""
    echo "  $1" >&2
    echo "" >&2
    exit "${2:-1}"
}

# --- 1. Required tools -------------------------------------------------------
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed. Install Python 3.10 or newer." 1

if ! command -v bun >/dev/null 2>&1; then
    fail "bun is not installed. Install it with: curl -fsSL https://bun.sh/install | bash" 1
fi

if [ -z "$OPENCODE_BIN" ]; then
    fail "opencode is not installed. See https://opencode.ai/docs/ for install instructions." 1
fi

# --- 2. Python dependencies ---------------------------------------------------
if ! python3 -c "import yaml" >/dev/null 2>&1; then
    echo "  PyYAML is missing. Install the Python dependencies:"
    echo "    python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    echo ""
fi

# --- 3. Portal CLI dependencies ----------------------------------------------
if [ ! -d "node_modules" ]; then
    echo "  Installing portal CLI dependencies..."
    python3 tools/install_portal_clis.py || fail "The portal CLI dependencies did not install." 1
fi

# --- 4. The directories -------------------------------------------------------
# The personal directories are git-ignored, so a clone has them only because
# their READMEs are tracked. Create them anyway, so a tarball, a partial
# checkout or a deleted README still works.
mkdir -p resumes/extracted profiles reports

# --- 5. The persona -----------------------------------------------------------
PERSONA="${JOB_HUNTER_PERSONA:-}"
if [ -z "$PERSONA" ] && [ -f "profiles/index.json" ]; then
    PERSONA="$(python3 -c "
import json
try:
    print(json.load(open('profiles/index.json')).get('active_persona', ''))
except Exception:
    print('')
" 2>/dev/null || true)"
fi
PERSONA="${PERSONA:-default}"

if [ ! -f "profiles/$PERSONA/profile.yaml" ]; then
    echo ""
    echo "  No persona '$PERSONA' yet."
    echo ""
    echo "  Put a resume in resumes/ and run the profile build inside OpenCode:"
    echo "    /profile-build"
    echo ""
    echo "  Or start from the example inputs:"
    echo "    cp config/profiles.example/inputs.example.yaml profiles/inputs.yaml"
    echo ""
    echo "  Or let the guided setup ask you the questions:"
    echo "    /setup"
    echo ""
    if [ "${1:-}" = "--check" ]; then
        echo "  Checks passed."
        exit 0
    fi
    echo "  Starting OpenCode anyway - run /profile-build to get set up."
    echo ""
else
    # Make sure the output directories exist before a run needs them.
    mkdir -p "profiles/$PERSONA/state/scratch" "reports/$PERSONA"
    if [ ! -d "resumes/extracted" ] || [ -z "$(ls -A resumes/extracted 2>/dev/null)" ]; then
        echo "  No resume has been extracted yet - run /profile-build inside OpenCode."
        echo ""
    fi
fi

if [ "${1:-}" = "--check" ]; then
    echo "  Checks passed."
    exit 0
fi

# --- 6. Doctor mode -----------------------------------------------------------
if [ "${1:-}" = "--doctor" ]; then
    echo "  Job Hunter diagnostics"
    echo "  ----------------------"
    echo ""
    echo "  opencode binaries:"
    command -v opencode
    which -a opencode 2>/dev/null || true
    echo ""

    # Probe version in a sandbox (never touches real user data)
    sandbox="$(mktemp -d)"
    trap 'rm -rf "$sandbox"' RETURN
    mkdir -p "$sandbox"/{home,data,config,cache,state}
    major="$(HOME="$sandbox/home" \
        XDG_DATA_HOME="$sandbox/data" \
        XDG_CONFIG_HOME="$sandbox/config" \
        XDG_CACHE_HOME="$sandbox/cache" \
        XDG_STATE_HOME="$sandbox/state" \
        "$OPENCODE_BIN" --version 2>/dev/null \
        | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 | cut -d. -f1 || echo unknown)"
    version_display="$(HOME="$sandbox/home" \
        XDG_DATA_HOME="$sandbox/data" \
        XDG_CONFIG_HOME="$sandbox/config" \
        XDG_CACHE_HOME="$sandbox/cache" \
        XDG_STATE_HOME="$sandbox/state" \
        "$OPENCODE_BIN" --version 2>/dev/null | head -n1 || echo unavailable)"
    echo "  Version (sandboxed): $version_display"
    echo "  Major version: $major"
    echo ""

    # Job Hunter database path for this major
    jh_db="$(python3 tools/opencode_db.py db-path --major "$major" 2>/dev/null || echo unavailable)"
    echo "  Job Hunter database: $jh_db"
    if [ -f "$jh_db" ]; then
        python3 tools/opencode_db.py state "$jh_db" 2>/dev/null | sed 's/^/    state: /'
    else
        echo "    state: missing (will be created on first run)"
    fi
    echo ""

    # List all Job Hunter databases
    jh_data_dir="$(python3 -c "from paths import job_hunter_data_dir; print(job_hunter_data_dir())" 2>/dev/null || echo unavailable)"
    if [ -d "$jh_data_dir" ]; then
        echo "  All Job Hunter databases in $jh_data_dir:"
        for db in "$jh_data_dir"/v*/opencode/opencode.db; do
            [ -f "$db" ] || continue
            st=$(python3 tools/opencode_db.py state "$db" 2>/dev/null || echo "error")
            echo "    $(basename "$(dirname "$(dirname "$db")")")/opencode/opencode.db: $st"
        done
    fi

    echo ""
    echo "  Note: Job Hunter uses its own per-major databases. The global OpenCode"
    echo "  database (~/.local/share/opencode/opencode.db) is never read or modified."
    exit 0
fi

# --- 7. Import existing DB ----------------------------------------------------
if [ "${1:-}" = "--import-db" ]; then
    shift
    src_db="${1:-}"
    if [ -z "$src_db" ] || [ ! -f "$src_db" ]; then
        fail "Usage: ./run.sh --import-db <path-to-existing-db>"
    fi
    sandbox="$(mktemp -d)"
    trap 'rm -rf "$sandbox"' RETURN
    mkdir -p "$sandbox"/{home,data,config,cache,state}
    major="$(HOME="$sandbox/home" \
        XDG_DATA_HOME="$sandbox/data" \
        XDG_CONFIG_HOME="$sandbox/config" \
        XDG_CACHE_HOME="$sandbox/cache" \
        XDG_STATE_HOME="$sandbox/state" \
        "$OPENCODE_BIN" --version 2>/dev/null \
        | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 | cut -d. -f1 || echo unknown)"
    dst_db="$(python3 tools/opencode_db.py db-path --major "$major")"
    mkdir -p "$(dirname "$dst_db")"
    cp "$src_db" "$dst_db"
    echo "  Imported $src_db -> $dst_db"
    python3 tools/opencode_db.py state "$dst_db" | sed 's/^/    state: /'
    exit 0
fi

# --- 8. Launch preparation: per-major isolated database -----------------------
# Probe the major version in a sandbox (never touches real user data)
sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' RETURN
mkdir -p "$sandbox"/{home,data,config,cache,state}
major="$(HOME="$sandbox/home" \
    XDG_DATA_HOME="$sandbox/data" \
    XDG_CONFIG_HOME="$sandbox/config" \
    XDG_CACHE_HOME="$sandbox/cache" \
    XDG_STATE_HOME="$sandbox/state" \
    "$OPENCODE_BIN" --version 2>/dev/null \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 | cut -d. -f1 || echo unknown)"

# Resolve Job Hunter database path for this major
jh_db="$(python3 tools/opencode_db.py db-path --major "$major")"

# Create parent directory
mkdir -p "$(dirname "$jh_db")"

# Check writability
if [ ! -w "$(dirname "$jh_db")" ]; then
    fail "Job Hunter database directory is not writable: $(dirname "$jh_db")"
fi

# Set XDG_DATA_HOME to the per-major Job Hunter directory so OpenCode
# creates/uses the database at $jh_db (all versions honor this)
export XDG_DATA_HOME="$(dirname "$(dirname "$jh_db")")"

# First-run notice
if [ ! -f "$jh_db" ]; then
    echo ""
    echo "  Job Hunter database: $jh_db"
    echo "  First run: type /connect inside OpenCode to add your model provider."
    echo ""
fi

# --- 9. Go ---------------------------------------------------------------------
echo "  Persona:  $PERSONA"
echo "  Reports:  reports/$PERSONA/"
echo ""
echo "  Commands:"
echo "    /setup           guided setup: resumes, roles, places, portals"
echo "    /profile-build   build or refresh the persona from your resume"
echo "    /find-jobs       search, score and report"
echo ""
echo "  Type /connect inside OpenCode to add your model provider."
echo ""
echo "  Ctrl-C twice to exit."
echo ""

exec "$OPENCODE_BIN"