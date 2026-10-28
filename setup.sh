#!/usr/bin/env bash
# Job Hunter setup.
#
# Prepares everything the workflow needs, so that a fresh clone, a fork or a
# downloaded ZIP is ready to run. Safe to run more than once - every step is
# skipped when it is already done.
#
# Usage:
#   ./setup.sh          install dependencies and create the directories
#   ./setup.sh --check  report what is missing and exit without installing

set -euo pipefail

cd "$(dirname "$0")"

BUN_BIN="$HOME/.bun/bin"
[ -d "$BUN_BIN" ] && export PATH="$BUN_BIN:$PATH"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '%s\n' "$*"; }
step() { printf '\n  %s\n' "$*"; }
missing_tools=""

need() {
    # need <command> <install-hint>
    if ! command -v "$1" >/dev/null 2>&1; then
        missing_tools="$missing_tools  - $1: $2
"
        return 1
    fi
    return 0
}

say "Job Hunter setup"
say "------------------------------------------------------------"

# --- 1. Required tools --------------------------------------------------------
step "Checking the required tools"

need python3 "Python 3.10 or newer - https://www.python.org/downloads/" || true
need bun "https://bun.sh/ - curl -fsSL https://bun.sh/install | bash" || true
need opencode "https://opencode.ai/docs/" || true

if [ -n "$missing_tools" ]; then
    say ""
    say "  Missing:"
    printf '%s' "$missing_tools"
    say ""
    say "  Install these, then run ./setup.sh again."
    exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    sys.stderr.write("  python3 is too old: %s. Python 3.10 or newer is needed.\n" % sys.version.split()[0])
    raise SystemExit(1)
PY
say "  python3  - $(python3 --version 2>&1)"
say "  bun      - $(bun --version 2>&1)"
say "  opencode - $(opencode --version 2>&1 | head -n 1)"

# --- 2. Python virtual environment --------------------------------------------
step "Preparing the Python environment"

if [ ! -d ".venv" ] && [ "$CHECK_ONLY" -eq 1 ]; then
    say "  .venv/ is missing - run ./setup.sh to create it"
elif [ ! -d ".venv" ]; then
    if python3 -m venv .venv 2>/dev/null; then
        say "  Created .venv/"
    else
        say "  Could not create .venv/ (the python3-venv package may be missing)."
        say "  Falling back to installing into the current Python environment."
    fi
else
    say "  .venv/ already exists"
fi

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . ".venv/bin/activate"
    say "  Using .venv/bin/python"
else
    say "  No virtual environment - using the system python3"
fi

if python3 -c "import yaml, pypdf" >/dev/null 2>&1; then
    say "  Python dependencies are already installed"
elif [ "$CHECK_ONLY" -eq 1 ]; then
    say "  Python dependencies are missing - run ./setup.sh to install them"
else
    python3 -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    python3 -m pip install --quiet -r requirements.txt
    say "  Installed requirements.txt"
fi

# --- 3. Portal CLI dependencies ------------------------------------------------
step "Preparing the portal CLIs"

if [ -d "node_modules" ]; then
    say "  node_modules/ already exists"
elif [ "$CHECK_ONLY" -eq 1 ]; then
    say "  Portal CLI dependencies are missing - run ./setup.sh to install them"
else
    python3 tools/install_portal_clis.py
fi

# --- 4. The directories --------------------------------------------------------
step "Creating the working directories"

mkdir -p resumes/extracted profiles reports
say "  resumes/extracted/  profiles/  reports/"

# --- 5. Done ------------------------------------------------------------------
say ""
say "------------------------------------------------------------"
if [ "$CHECK_ONLY" -eq 1 ]; then
    say "  Check finished."
else
    say "  Setup complete."
fi
say ""
say "  Next:"
say "    1. ./run.sh"
say "    2. Inside OpenCode, type /connect to add your model provider"
say "       (OpenCode starts on its free model until you do)."
say "    3. Then:  /setup  ->  /profile-build  ->  /find-jobs"
say ""
