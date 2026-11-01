# Job Hunter

Find the jobs worth applying to, with a report that explains why each one fits
and what to change in your CV for it.

> **Origin:** This project is a scrap from [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search), originally created with Claude as part of the `ai-job-verification` effort. It's been adapted into this OpenCode-native, local-first "Job Hunter" workflow. The portal CLIs under `.agents/skills/` are vendored from the upstream repo and keep their own licenses.

Job Hunter searches job boards for postings that match a **persona** built from
your resume, scores each posting against that resume, and writes a report with
direct links, fit scores, honest gaps and tailored CV suggestions.

**It never applies to anything.** You read the report, open the links, and
apply yourself.

Built for [OpenCode](https://opencode.ai). The commands, the agents and the
permission model are OpenCode-native.

---

## Quick start

### After a fork or a ZIP download

You do not need to run every command by hand. One script does the setup:

```bash
./setup.sh && ./run.sh
```

**Or with `make`:**

```bash
make run
```

The setup script will:
- Check for the required tools (`python3`, `bun`, `opencode`) and give install hints if one is missing
- Create a Python virtual environment (`.venv`)
- Install the Python dependencies (`pip install -r requirements.txt`)
- Install the portal CLI dependencies (`bun install`)
- Create the working directories (`resumes/`, `profiles/`, `reports/`)

It is safe to run again at any time - every step is skipped when it is already
done. `./setup.sh --check` reports what is still missing without installing
anything.

**Windows:** use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)
or Git Bash. Configure a model provider in OpenCode before running.

### From a git clone

```bash
git clone <this repo>
cd job-hunter

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

bun install          # installs the portal CLIs from the workspace lockfile
./run.sh             # starts OpenCode, with the setup checks
```

**Bring your own model.** `opencode.json` in this repository deliberately names
no provider, so Job Hunter runs on whichever model you already use - or on the
free one OpenCode ships with.

OpenCode starts and waits for you. Connect a provider whenever you like:

| Where | How |
|---|---|
| Inside the app | type `/connect`, pick a provider, paste your key |
| From a terminal | `opencode auth login` |
| In your own config | add `model` and `provider` to `~/.config/opencode/opencode.jsonc` |

Your key is stored by OpenCode, in your home directory - never in this
repository. See <https://opencode.ai/docs/> for the provider list.

Without a provider OpenCode still opens; it just answers with its free model
until you connect one.

Inside OpenCode:

```
/setup               # guided setup - asks where your resumes are,
                     # which roles, which places, which portals
/profile-build       # build your persona from your resume
/find-jobs           # search, score, report
```

Your first report lands in `reports/<persona>/YYYY-MM-DD/jobs-YYYY-MM-DD-HH-MM.md` (and `.html`) — timestamped in **Cairo time (GMT+2)**, grouped by day.

## Smart query generation (strict & guarded)

`/find-jobs` now runs a **query guard** before searching:

1. **Base queries** — generated deterministically from your persona by `profile_query.py`
2. **Agent proposes up to 2 extra queries** — learned from high-scoring jobs in prior runs
3. **Query guard validates** — `tools/query_guard.py` rejects any query carrying:
   - Portal filter words (junior, senior, remote, hybrid, sponsorship, etc.)
   - Fewer than 2 or more than 4 words
   - Repeats of a base query
   - Over the 2-query cap
4. **Only validated queries reach the portals** — the run summary reports accepted/rejected

This stops the model from "overthinking" queries and producing searches that match nothing.

---

### The steps in detail

**1. Put your resume in `resumes/`.**

```
resumes/
  your-name--ai-llm-rag--v20261027.pdf
```

PDF, DOCX and TXT are supported. The naming pattern is
`<you>--<what-it-is-for>--v<date>`. See `resumes/README.md`. You can add
several resumes; each one aimed at a different kind of role becomes its own
persona.

**2. Set up your preferences.**

Either let `/setup` ask you the questions, or fill the file in yourself:

```bash
cp config/profiles.example/inputs.example.yaml profiles/inputs.yaml
```

`profiles/inputs.yaml` is yours to edit and nothing overwrites it. It holds
your contact details, the roles you want, the locations you can work from,
the seniority you are aiming at and the dealbreakers.

**3. Build the persona, then search.**

```
/profile-build
/find-jobs
```

`/profile-build` reads your resume, works out which roles and skills it
actually supports, and writes a persona where every claim points back to the
lines of the resume that support it. `/find-jobs` then searches, scores and
reports.

### The places you can search

Places are countries and regions, not cities. There are 10 regions and 158
countries in the catalogue:

| Region | Countries |
|---|---|
| `europe` | Europe |
| `european_union` | European Union |
| `uk` | United Kingdom |
| `mena` | Middle East and North Africa |
| `africa` | Africa |
| `emea` | Europe, Middle East and Africa |
| `north_america` | North America |
| `latam` | Latin America |
| `apac` | Asia-Pacific |
| `cis` | Commonwealth of Independent States |
| `anywhere` | No geographic restriction |

List them, or check a name before using it:

```bash
python3 tools/places.py --list all
python3 tools/places.py --resolve "the Gulf"
```

**A place the catalogue does not know produces no search, and the run tells
you so.** It never quietly searches somewhere else. Each portal expresses a
place its own way, and a portal that cannot express one searches a wider
area - the run summary says which, and why.

**Leave the list of places empty and the search is remote roles anywhere.**
The default is reported in the run summary, so it is never a silent one
either.

| Place | freehire | LinkedIn | Jobicy |
|---|---|---|---|
| Egypt | `--country EG` | `--location Egypt` | `--location emea` (wider - no Egypt slug) |
| Germany | `--country DE` | `--location Germany` | `--location germany` |
| MENA | `--region mena` | `--location "Middle East"` | `--location emea` (wider) |
| Anywhere | `--region global,none --remote remote` | `--location Remote --remote remote` | `--location anywhere` |

A mode that accepts more than one way of working - `onsite_remote_hybrid` or
`remote_or_relocation` - is sent with no work-mode filter at all. A filter
that asks for "remote, hybrid or on-site" still drops every posting that
declares no work mode, and in Egypt that is most of them.

### Where you live

`identity.location` is your **home place**, and it is not a search
preference. It is what the location gate accepts: a role on-site in the city
you already live in is a role you can take, so it is never gated out. A
posting in your own country that the scorer failed on location grounds is
downgraded to `FLAG` and shown to you, rather than dropped.

See `docs/portals.md` for the full table and for the places LinkedIn resolves
to the wrong country if you write them the obvious way.

---

## What a report looks like

For each job:

| Field | What it means |
|---|---|
| Fit score | 0-100, weighted across technical, experience, behavioural and career alignment |
| Work mode | Remote, Hybrid, On-site or Not specified - read from the posting |
| Visa / sponsorship | Allowed, Not indicated or Blocked, with the quoted wording when blocked |
| Key matches | Resume-backed, quoting your own projects |
| Gaps | Stated honestly, never smoothed over |
| Why apply | Two or three bullets tying the posting to what you have actually built |
| Tailored CV suggestions | Specific rewrites: which project to lead with, which bullet to move |

Plus an **Excluded** section showing what was filtered out and why, and a
**Closing soon** section for deadlines inside a week.

---

## Commands

| Command | What it does |
|---|---|
| `/setup` | Guided setup: resumes, roles, seniority, places, portals |
| `/profile-build` | Build or refresh a persona from your resumes and your inputs |
| `/find-jobs` | Search the boards, score the postings, write the report |

Useful arguments to `/find-jobs`:

| Argument | Meaning |
|---|---|
| `--persona <slug>` | Use a specific persona |
| `--limit <N>` | How many jobs to fetch and score (default 10) |
| `--top <N>` | How many to show in the report (default 10) |
| `--focus "<text>"` | Only jobs matching this text |
| `--report-only` | Report only, no CV suggestions |
| `--personas` | List the available personas |

---

## How it works

```
resumes/ ──► extract_resume.py ──► extracted text
                                         │
                              /profile-build (the model reads it)
                                         │
                              profile.yaml (facts + evidence)
profiles/inputs.yaml ────────────────┐   │
                                     ▼   ▼
                            profile_query.py ──► queries + portal flags
                                     │
                              /find-jobs (the search)
                                     │
              portal CLIs ──► scrape_state.py ──► seen_jobs.json
                                     │
                         posting-scorer (the model scores)
                                     │
                        rank_state.py ──► scores, verdicts, vetoes
                                     │
                              report .md + .html
```

**The model does the judgement, the tools do the mechanics.** Resume
extraction, query generation, deduplication, the weighted score, the vetoes
and the state writes are all deterministic Python. The model is used for the
two things that need judgement: reading a resume into structured facts, and
scoring a posting against those facts.

That split is what makes a run reproducible and a store step trustworthy. When
`scrape_state.py` reports what it stored, you can believe it.

---

## The layout

Four kinds of thing, so it is always obvious what is yours and what is the
project's.

| | Path | What it is |
|---|---|---|
| **Your input** | `resumes/` | Your resume files and the extracted-text cache |
| **Your input** | `profiles/` | Your preferences and one directory per persona |
| **Generated** | `reports/` | The reports, one directory per persona |
| **The project** | `.agents/`, `.opencode/`, `tools/` | The portal CLIs, the commands, the agents and the Python tools |
| **The project** | `templates/`, `config/`, `docs/` | PII-free starting points and documentation |

A **persona** is one search identity - a resume variant aimed at a role
family, plus the preferences that apply to it:

```
profiles/<persona>/
  profile.yaml     derived facts, each with the resume lines it came from
  PROFILE.md       the generated aggregate you read
  state/           seen_jobs.json, tracker.csv, search-queries.md, scratch/
```

`PROFILE.md` is generated from `profile.yaml` and `inputs.yaml`. It is a view,
not a source of truth. The one part you own is the `## User Notes` section at
the bottom, which is preserved exactly when the profile is rebuilt.

---

## Portals

| Portal | Covers | Status |
|---|---|---|
| `freehire-search` | Many markets, tech-focused, one API | Enabled |
| `linkedin-search` | Worldwide, incl. remote | Enabled - **personal use only** per its terms |
| `jobicy-search` | Remote roles by eligibility: USA, Canada, UK, Europe, EMEA, APAC, LATAM | Enabled |

Enable or disable them in `profiles/inputs.yaml`. A portal runs only when it
is enabled there **and** its own `SKILL.md` does not set `enabled: false`.

Boards with no CLI - Dice, Wellfound, Otta, Naukrigulf, Bayt, Wuzzuf,
WeWorkRemotely - are reached by site-scoped web search, configured under
`search.site_queries`.

Each portal expresses a place its own way, and a portal that cannot express
one searches a wider area instead. The run summary reports every widening, so
a search that quietly became "everywhere" is never mistaken for an exact one.

See `docs/portals.md` for what each one supports, the full place table, and
the places LinkedIn resolves to the wrong country if you write them the
obvious way.

---

## Privacy

Everything under `resumes/`, `profiles/` and `reports/` is git-ignored and
holds personal data. `python3 tools/check_repo.py` fails the build if any of
it is tracked, if an ignore rule is missing, or if a committed prompt contains
a personal identifier.

**One thing is outside this tool's control:** your resume is sent to whatever
model provider you have configured in OpenCode. Check that provider's data
retention terms, and choose one that does not train on your input, before you
put a real CV in `resumes/`.

See `SECURITY.md` for the details.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `bun is not installed` | `curl -fsSL https://bun.sh/install \| bash`, then reopen the shell |
| `No persona '<name>' yet` | Put a resume in `resumes/`, then run `/profile-build` |
| `PyYAML is missing` | `source .venv/bin/activate && pip install -r requirements.txt` |
| OpenCode answers nothing | No provider connected - type `/connect` inside OpenCode, or run `opencode auth login` |
| A portal returns nothing | Check its `SKILL.md` for the right flags; a query is keywords only |
| A place was not searched | `python3 tools/places.py --resolve "your place"` - an unknown place produces no search, on purpose |
| A search covered more than you asked | The run summary lists widened searches; `docs/portals.md` explains why |
| The report is empty of new jobs | Everything was seen before - check `profiles/<persona>/state/seen_jobs.json` |
| `resume changed since the profile was built` | Run `/profile-build` to refresh the persona |
| `Database is not empty and has no session table` | OpenCode v1 (1.19.x) opened a database created by v2 (2.x). Run `make doctor` to diagnose. `./run.sh` auto-isolates to a per-version DB; or set `OPENCODE_DB=~/.local/share/opencode/job-hunter-v1.db` manually. Migration is one-way; do not delete the v2 DB if you need its history. |

---

## Documentation

| File | What is in it |
|---|---|
| `AGENTS.md` | The rules the agent follows |
| `docs/architecture.md` | How the pieces fit together |
| `docs/privacy.md` | What leaves your machine, and when |
| `docs/portals.md` | The portals, their flags and their terms |
| `SECURITY.md` | The threat model |
| `CONTRIBUTING.md` | How to contribute |

## Licence

MIT. See `LICENSE`.

The portal CLIs in `.agents/skills/` are vendored from the upstream
`ai-job-search` project and keep their own licences.
