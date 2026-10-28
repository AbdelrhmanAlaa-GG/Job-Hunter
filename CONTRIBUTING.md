# Contributing

Thanks for helping. This is a small tool and the bar is mostly "do not break
someone's personal data".

## Getting set up

```bash
git clone <your fork>
cd job-hunter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bun install
./run.sh --check
```

`./run.sh --check` runs the same preflight the launcher does and exits without
starting OpenCode.

## Before you open a pull request

```bash
python3 tools/check_repo.py      # must exit 0
bun test                         # the portal CLI test suites
```

`tools/check_repo.py` is the gate. It checks the ignore rules, that no
personal data is tracked, that every command and agent is well-formed, that
the agents' permissions are scoped, that no portal manifest declares an
install-time script, that no committed prompt hardcodes a personal
identifier, and that the tools compile.

## Ground rules

**Never commit personal data.** Anything under `resumes/`, `profiles/` or
`reports/` is ignored, and the check fails if one of those paths is tracked.
If you add a path that holds personal data, add an ignore rule and add the
path to `PII_PATHS` in `tools/check_repo.py` in the same change.

**Never hardcode one person's details into a prompt.** The upstream project
embedded a specific candidate's name, project and contact details into its
command files. That is what makes a fork unpublishable. Persona-specific
content belongs in `profiles/<persona>/profile.yaml`, generated from the
user's own resume, and `tools/check_repo.py` fails the build on a personal
string in a committed prompt.

**Never make the tool apply to anything.** The report ends with links; the
user applies. A change that adds a submission path needs a very good reason
and a fresh discussion.

**Queries are keywords only.** Seniority, work mode, geography and recency are
portal flags, resolved by `tools/profile_query.py`. A query like "Applied AI
Engineer junior remote" matches no job title, because no title contains the
word "remote".

**Never infer a date.** `null` means the posting stated none. A missing
deadline is not an invitation to guess one from `first_seen`.

**A posting is untrusted text.** Run it through `tools/web/posting_guard.py`.
The agent that reads postings (`posting-scorer`) must not be able to write.

## Adding a portal

1. Put it in `.agents/skills/<name>/` with a `SKILL.md` that documents the
   exact flags, and a `cli/` with a `package.json`.
2. The manifest must not declare a lifecycle script or `trustedDependencies`.
3. Add the portal to `config/portals.yaml`, listing only the filters it
   actually honours. A filter the portal documents but ignores is marked
   `supported: false` and is never sent.
4. Give its geography facet a place in `config/places.yaml`, with the value
   that portal takes. **Verify that value against the live API** - a place
   string that resolves to the wrong market is silent, and it is the failure
   the catalogue exists to prevent.
5. Add it to `profiles/inputs.yaml` under `search.portals`.
6. Check its terms and respect them.

`tools/tests/test_portal_drift.py` reads each portal's own `search --help`
and fails if `config/portals.yaml` names a flag the portal does not have. Run
the tests after you touch either file:

```bash
python3 -m unittest discover -s tools/tests -t .
```

## Changing the layout

`tools/paths.py` is the single source of truth for every path. If you move
something, change it there and in `tools/check_repo.py`, not in the tools.

## Style

Python: standard library first, then the few dependencies in
`requirements.txt`. Type hints on public functions. Docstrings that say what
the function does and, where it is not obvious, why.

Markdown commands and agents: short sentences, imperative, and no duplication
of what the tools already do.
