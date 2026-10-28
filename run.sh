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

set -euo pipefail

cd "$(dirname "$0")"

BUN_BIN="$HOME/.bun/bin"
[ -d "$BUN_BIN" ] && export PATH="$BUN_BIN:$PATH"

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

if ! command -v opencode >/dev/null 2>&1; then
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

# --- 6. Go ---------------------------------------------------------------------
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

exec opencode
