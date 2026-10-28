"""Audit the Job Hunter repository.

Replaces the upstream Claude Code-specific ``lint_skills.py`` and
``security_guards.py``, both of which looked for ``.claude/`` paths that do
not exist in an OpenCode project and both of which failed outright.

What it checks:

    ignores     the required ignore rules are present, and the PII paths are
                actually ignored
    tracked     no personal data is tracked by git
    commands    every command has a description, and the agent it names exists
    agents      no agent grants unscoped bash, and an agent that reads
                untrusted posting text cannot write
    manifests   no portal CLI declares an install-time lifecycle script
    secrets     no command or agent hardcodes a personal identifier
    python      every tool compiles
    lockfile    the workspace lockfile is committed

Usage:
    python3 tools/check_repo.py
    python3 tools/check_repo.py --json

Exit codes:
    0 - everything passed
    1 - at least one check failed
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import ROOT  # noqa: E402
from policy import (  # noqa: E402
    FORBIDDEN_SCRIPTS,
    PII_PATHS as PII_DIRECTORIES,
    REQUIRED_IGNORE_RULES,
)

COMMANDS_DIR = ROOT / ".opencode" / "commands"
AGENTS_DIR = ROOT / ".opencode" / "agents"
GITIGNORE = ROOT / ".gitignore"

# The tracked READMEs are the only files in a personal directory that are
# allowed to be committed.
ALLOWED_TRACKED = {"resumes/README.md", "profiles/README.md"}


def pii_probe_paths() -> list[str]:
    """The personal paths to probe the ignore rules against.

    The directories come from the shared policy. The files are whatever is
    actually on disk, so the check works for any candidate rather than only
    for the one whose paths were written down here.
    """
    probes = list(PII_DIRECTORIES)
    for directory in ("resumes", "profiles", "reports"):
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = str(path.relative_to(ROOT))
            if relative in ALLOWED_TRACKED:
                continue
            probes.append(relative)
    return probes

# Files that must be tracked, so a clone is usable.
REQUIRED_TRACKED = (
    "README.md",
    "AGENTS.md",
    "LICENSE",
    "opencode.json",
    "package.json",
    "bun.lock",
    "requirements.txt",
    "run.sh",
    "setup.sh",
    "Makefile",
    "tools/check_repo.py",
    "tools/profile_query.py",
    "tools/profile_build.py",
    "tools/extract_resume.py",
    "tools/render_profile.py",
    "tools/paths.py",
    "tools/scrape_state.py",
    "tools/rank_state.py",
    "tools/job_key.py",
    "tools/install_portal_clis.py",
    "resumes/README.md",
)

# Patterns that catch a personal identifier in a committed file without the
# checker itself having to contain one. Hardcoding the candidate's email into
# the checker is the same mistake it is supposed to catch.
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3,4}[\s.-]\d{3,4}")

# Addresses that are obviously placeholders rather than a real person.
PLACEHOLDER_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "example",
    "evil.io",
    "evil.example",
    "localhost",
    "test",
)


def _looks_like_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(value.strip()))


def _looks_like_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15:
        return False
    # A run of identical digits is a placeholder, not a number.
    return len(set(digits)) > 1


def personal_needles() -> list[str]:
    """Collect the user's own identifiers from the local, untracked files.

    The personal files - ``profiles/inputs.yaml`` and each persona's
    ``profile.yaml`` - are git-ignored, so reading them here leaks nothing.
    What comes back is exactly the set of strings that must not appear in a
    committed file: the user's name, their contact details, their project
    names and their resume slug.

    Only identifying values are collected. A skill name or a target role is
    not identifying - those belong in the commands on purpose - but a name, a
    project title and a contact detail are.

    In a fresh clone there are no personal files, so this returns nothing and
    the generic patterns below do the work.
    """
    needles: set[str] = set()
    sources = [ROOT / "profiles" / "inputs.yaml"]
    personas_dir = ROOT / "profiles"
    if personas_dir.is_dir():
        sources.extend(personas_dir.glob("*/profile.yaml"))

    def add(value) -> None:
        if not isinstance(value, str):
            return
        text = value.strip()
        if len(text) >= 3:
            needles.add(text)

    def add_value(value) -> None:
        """Add a plain value, and any string buried inside it."""
        if isinstance(value, str):
            if _looks_like_email(value) or _looks_like_phone(value):
                add(value)
            else:
                add(value)
        elif isinstance(value, dict):
            for child in value.values():
                add_value(child)
        elif isinstance(value, list):
            for child in value:
                add_value(child)

    def add_field(block, key: str) -> None:
        """Add a named field, unwrapping the {value, source} shape."""
        if not isinstance(block, dict):
            return
        entry = block.get(key)
        if isinstance(entry, dict) and "value" in entry:
            entry = entry["value"]
        if isinstance(entry, str):
            add(entry)

    for source in sources:
        if not source.exists():
            continue
        try:
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue

        # Contact details, wherever they sit.
        add_value(data.get("identity", {}).get("email"))
        add_value(data.get("identity", {}).get("phone"))
        add_value(data.get("contact"))

        # The person's name.
        add_field(data.get("identity", {}), "name")
        add_field(data.get("identity", {}), "full_name")

        # Project names, and the resume slug and file name.
        for project in data.get("projects", []) or []:
            add_field(project, "name")
        for resume in data.get("resumes", []) or []:
            add_field(resume, "slug")
            add_field(resume, "file")
            add_field(resume, "extracted_text")

    return sorted(needles)


class Report:
    """Collects check results."""

    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "ok": ok, "detail": detail})
        return ok

    @property
    def failed(self) -> list[dict]:
        return [check for check in self.checks if not check["ok"]]

    @property
    def ok(self) -> bool:
        return not self.failed


def run_git(args: list[str]) -> tuple[int, str]:
    """Run a git command and return (returncode, output)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def agent_permissions(text: str) -> dict:
    """Return an agent file's permission block, parsed as YAML.

    The permission block lives in the frontmatter. It is parsed with a YAML
    parser rather than a regex because a regex cannot tell `allow` from
    `"allow"`, and that difference is the whole answer to whether a rule
    grants or denies.
    """
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(front, dict):
        return {}
    permission = front.get("permission")
    return permission if isinstance(permission, dict) else {}


def parse_frontmatter(text: str) -> dict:
    """Parse the YAML-ish frontmatter of a command or agent file."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    block = parts[1]
    data: dict = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            data[key] = value
        elif key and line.startswith((" ", "\t")):
            value = line.strip()
            if value and data.get(key) in ("", None):
                data[key] = value
            elif value:
                data[key] = f"{data.get(key, '')} {value}".strip()
    return data


def check_ignores(report: Report) -> None:
    """The required ignore rules are present and the PII paths are ignored."""
    if not GITIGNORE.exists():
        report.add("ignores", False, ".gitignore is missing")
        return

    text = GITIGNORE.read_text(encoding="utf-8")
    # Match whole rules, not substrings, so a rule mentioned in a comment
    # cannot satisfy the check.
    rules = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [rule for rule in REQUIRED_IGNORE_RULES if rule not in rules]
    report.add(
        "ignores",
        not missing,
        "missing required rules: " + ", ".join(missing) if missing else "all required rules present",
    )

    # check-ignore takes one pathname at a time, so probe them individually.
    probes = pii_probe_paths()
    leaked = []
    for path in probes:
        probe, _ = run_git(["check-ignore", "--no-index", "--quiet", path])
        if probe != 0:
            leaked.append(path)
    report.add(
        "pii-ignored",
        not leaked,
        "not ignored: " + ", ".join(leaked) if leaked else f"all {len(probes)} personal paths are ignored",
    )


def check_tracked(report: Report) -> None:
    """No personal data is tracked, and the required files are."""
    code, output = run_git(["ls-files"])
    if code != 0:
        report.add("tracked", False, "not a git repository, or git failed")
        return

    tracked = [line.strip() for line in output.splitlines() if line.strip()]

    # The tracked READMEs are the only personal-directory files that are
    # allowed to be committed. They describe the layout and contain no user
    # data.
    leaked = [
        path
        for path in tracked
        if path.startswith(("resumes/", "profiles/", "reports/"))
        and path not in ALLOWED_TRACKED
    ]
    report.add(
        "tracked-pii",
        not leaked,
        "personal files are tracked: " + ", ".join(leaked) if leaked else "no personal files tracked",
    )

    missing = [path for path in REQUIRED_TRACKED if path not in tracked]
    report.add(
        "tracked-required",
        not missing,
        "missing from git: " + ", ".join(missing) if missing else f"all {len(REQUIRED_TRACKED)} required files tracked",
    )


def check_commands(report: Report) -> None:
    """Every command has a description, and the agent it names exists."""
    if not COMMANDS_DIR.is_dir():
        report.add("commands", False, f"{COMMANDS_DIR} is missing")
        return

    problems: list[str] = []
    command_files = sorted(COMMANDS_DIR.glob("*.md"))
    if not command_files:
        problems.append("no command files found")

    agent_names = {path.stem for path in AGENTS_DIR.glob("*.md")} if AGENTS_DIR.is_dir() else set()

    for path in command_files:
        text = path.read_text(encoding="utf-8")
        front = parse_frontmatter(text)
        if not front:
            problems.append(f"{path.name}: no frontmatter")
            continue
        description = str(front.get("description", "")).strip()
        if not description:
            problems.append(f"{path.name}: no description")
        agent = str(front.get("agent", "")).strip()
        if agent and agent not in agent_names:
            problems.append(f"{path.name}: names unknown agent '{agent}'")

        # A state tool called without --persona falls back to the *active*
        # persona. A run against a different persona would then deduplicate
        # against, and write into, someone else's history.
        for line_no, line in enumerate(text.splitlines(), start=1):
            invocation = re.search(r"python3\s+tools/(scrape_state|rank_state)\.py\b.*", line)
            if invocation and "--persona" not in invocation.group(0):
                problems.append(
                    f"{path.name}:{line_no}: {invocation.group(1)}.py called without --persona"
                )

            # Every tool the command invokes has to exist.
            for script in re.findall(r"python3\s+(tools/[A-Za-z0-9_/]+\.py)", line):
                if not (ROOT / script).exists():
                    problems.append(f"{path.name}:{line_no}: {script} does not exist")

    report.add(
        "commands",
        not problems,
        "; ".join(problems) if problems else f"{len(command_files)} command(s) valid",
    )


def check_agents(report: Report) -> None:
    """No agent grants unscoped bash; untrusted-text agents cannot write."""
    if not AGENTS_DIR.is_dir():
        report.add("agents", False, f"{AGENTS_DIR} is missing")
        return

    problems: list[str] = []
    agent_files = sorted(AGENTS_DIR.glob("*.md"))
    if not agent_files:
        problems.append("no agent files found")

    for path in agent_files:
        text = path.read_text(encoding="utf-8")
        front = parse_frontmatter(text)
        name = path.stem

        if not str(front.get("description", "")).strip():
            problems.append(f"{name}: no description")

        # The permission block lives in the frontmatter, not the body. Parse
        # it as YAML: a regex cannot tell `allow` from `"allow"`, and that
        # difference decides whether a rule grants or denies.
        permission = agent_permissions(text)
        edit_rules = permission.get("edit")
        write_rules = permission.get("write")
        bash_rules = permission.get("bash")

        def allows_anything(rules) -> bool:
            """Whether the rules allow the tool for any path at all."""
            if isinstance(rules, str):
                return rules.lower() == "allow"
            if not isinstance(rules, dict):
                return False
            return any(
                isinstance(value, str) and value.lower() == "allow"
                for value in rules.values()
            )

        def allows_wildcard(rules) -> bool:
            """Whether the rules allow the tool for every path."""
            if isinstance(rules, str):
                return rules.lower() == "allow"
            if not isinstance(rules, dict):
                return False
            wildcard = rules.get("*")
            return isinstance(wildcard, str) and wildcard.lower() == "allow"

        # An agent that reads untrusted posting text must not be able to
        # write or edit the repository.
        if "posting" in name or "scorer" in name:
            if allows_anything(edit_rules):
                problems.append(f"{name}: an agent handling untrusted text may not allow edit")
            if allows_anything(write_rules):
                problems.append(f"{name}: an agent handling untrusted text may not allow write")

        # bash permission blocks must scope the wildcard, never blanket-allow.
        if allows_wildcard(bash_rules):
            problems.append(f"{name}: bash grants unscoped allow")

    report.add(
        "agents",
        not problems,
        "; ".join(problems) if problems else f"{len(agent_files)} agent(s) valid",
    )


def check_manifests(report: Report) -> None:
    """No portal CLI declares an install-time lifecycle script."""
    problems: list[str] = []
    manifests = sorted((ROOT / ".agents" / "skills").glob("*/cli/package.json"))
    if not manifests:
        problems.append("no portal manifests found")

    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{manifest}: unreadable ({exc})")
            continue
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict):
            bad = sorted(FORBIDDEN_SCRIPTS & set(scripts))
            if bad:
                problems.append(f"{manifest.parent.parent.name}: lifecycle script(s) {bad}")
        if "trustedDependencies" in data:
            problems.append(f"{manifest.parent.parent.name}: declares trustedDependencies")

    report.add(
        "manifests",
        not problems,
        "; ".join(problems) if problems else f"{len(manifests)} portal manifest(s) clean",
    )


def check_secrets(report: Report) -> None:
    """No committed file hardcodes a personal identifier.

    Every tracked file this project owns is scanned. The vendored portal CLIs
    under ``.agents/`` are upstream code and are left alone: their test
    fixtures contain synthetic addresses and numbers that are not anyone's.
    """
    problems: list[str] = []

    code, output = run_git(["ls-files"])
    tracked = [line.strip() for line in output.splitlines() if line.strip()] if code == 0 else []

    targets = []
    for relative in tracked:
        if relative.startswith(".agents/"):
            continue
        if relative.endswith(".lock") or relative.endswith(".pdf"):
            continue
        if not relative.endswith((".md", ".py", ".yaml", ".yml", ".json", ".jsonc", ".txt")):
            continue
        path = ROOT / relative
        if path.exists():
            targets.append(path)

    # The user's own identifiers, learned from the untracked personal files.
    needles = personal_needles()

    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()

        for needle in needles:
            if needle.lower() in lowered:
                problems.append(f"{path.relative_to(ROOT)}: contains a personal identifier")
                break

        for match in EMAIL_PATTERN.findall(text):
            domain = match.rsplit("@", 1)[-1].lower()
            if not any(domain.endswith(known) for known in PLACEHOLDER_DOMAINS):
                problems.append(f"{path.relative_to(ROOT)}: contains an email address")
                break

        for match in PHONE_PATTERN.findall(text):
            if not _looks_like_phone(match):
                continue
            digits = re.sub(r"\D", "", match)
            if set(digits) <= {"0"}:
                continue
            problems.append(f"{path.relative_to(ROOT)}: contains a phone number")
            break

    report.add(
        "secrets",
        not problems,
        "; ".join(sorted(set(problems)))
        if problems
        else f"no personal identifiers in {len(targets)} tracked file(s)",
    )


def check_python(report: Report) -> None:
    """Every tool compiles."""
    problems: list[str] = []
    tools = sorted((ROOT / "tools").rglob("*.py"))
    for path in tools:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(ROOT)}: {exc}")
        except OSError as exc:
            problems.append(f"{path.relative_to(ROOT)}: {exc}")

    report.add(
        "python",
        not problems,
        "; ".join(problems) if problems else f"{len(tools)} tool(s) compile",
    )


def check_lockfile(report: Report) -> None:
    """The workspace lockfile exists and is committed."""
    lockfile = ROOT / "bun.lock"
    if not lockfile.exists():
        report.add("lockfile", False, "bun.lock is missing - run 'bun install' and commit it")
        return
    code, output = run_git(["ls-files", "bun.lock"])
    report.add(
        "lockfile",
        code == 0 and "bun.lock" in output,
        "bun.lock is committed" if code == 0 and "bun.lock" in output else "bun.lock is not committed",
    )


def check_agent_chain(report: Report) -> None:
    """A command's agent chain is allowed by the configured subagent depth.

    A command that runs as a subtask puts its agent at depth 1. If that agent
    is allowed to launch another agent, the chain needs depth 2 - and the
    default is 1, which makes the whole nested chain fail at runtime with
    "Subagent depth limit reached".
    """
    config_path = ROOT / "opencode.json"
    if not config_path.exists():
        report.add("agent-chain", False, "opencode.json is missing")
        return

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add("agent-chain", False, f"opencode.json is not valid JSON: {exc}")
        return

    depth = (config.get("experimental") or {}).get("subagent_depth")
    if not isinstance(depth, int):
        depth = config.get("subagent_depth")
    if not isinstance(depth, int):
        depth = 1  # the default

    problems: list[str] = []
    for path in sorted(COMMANDS_DIR.glob("*.md")) if COMMANDS_DIR.is_dir() else []:
        front = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not front or not front.get("subtask"):
            continue
        agent_name = str(front.get("agent", "")).strip()
        if not agent_name:
            continue
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        if not agent_path.exists():
            continue
        task_rules = agent_permissions(agent_path.read_text(encoding="utf-8")).get("task") or {}

        # Does this agent allow launching a *named* agent?
        launches = any(
            isinstance(value, str)
            and value.lower() == "allow"
            and name not in ("*", "")
            for name, value in task_rules.items()
        )

        if launches and depth < 2:
            problems.append(
                f"{path.name} runs {agent_name} as a subtask, and {agent_name} may launch "
                f"another agent - opencode.json needs experimental.subagent_depth of at least 2"
            )

    report.add(
        "agent-chain",
        not problems,
        "; ".join(problems) if problems else f"subagent depth {depth} allows the agent chain",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = parser.parse_args()

    report = Report()
    check_ignores(report)
    check_tracked(report)
    check_commands(report)
    check_agents(report)
    check_agent_chain(report)
    check_manifests(report)
    check_secrets(report)
    check_python(report)
    check_lockfile(report)

    if args.json:
        print(json.dumps({"ok": report.ok, "checks": report.checks}, ensure_ascii=False, indent=2))
        return 0 if report.ok else 1

    print("Job Hunter repository check")
    print("-" * 60)
    for check in report.checks:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"[{mark}] {check['check']:18} {check['detail']}")
    print("-" * 60)
    if report.ok:
        print("All checks passed.")
        return 0
    print(f"{len(report.failed)} check(s) failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
