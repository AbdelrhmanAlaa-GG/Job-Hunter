# Architecture

## The split that matters

**The model judges. The tools do the mechanics.**

Everything mechanical is deterministic Python: extracting text from a resume,
building the search queries, deduplicating postings, computing the weighted
score, applying the vetoes, writing the state. The model is used for exactly
two things that need judgement:

1. Reading a resume into structured facts, each with an evidence reference.
2. Scoring one posting against those facts.

That split is why a run is reproducible and why a store step can be trusted.
When `scrape_state.py` prints the keys it wrote, those keys are really there.

## The pipeline

```
resumes/*.pdf
    │  tools/extract_resume.py          deterministic, model-free
    ▼
resumes/extracted/*.txt  +  sha256
    │
    │  /profile-build                   the model reads the text
    ▼
profiles/<persona>/profile.yaml         facts, each with `source: resume:...#L11`
profiles/inputs.yaml                    the user's preferences
    │
    │  tools/profile_query.py           pure function
    ▼
search_queries + portal_targets + filters
    │
    │  tools/search_portals.py          search -> select -> order -> fetch
    ▼                                    (all deterministic, model-free)
prepared.json + bodies/*.txt + store.json
    │
    │  tools/scrape_state.py store
    ▼
profiles/<persona>/state/seen_jobs.json  status: new
    │
    │  posting-scorer (subagents)       the model scores
    ▼
scoring results
    │
    │  tools/rank_state.py apply        weighted score, verdict, vetoes
    ▼
profiles/<persona>/state/seen_jobs.json  status: ranked
    │
    ▼
reports/<persona>/jobs-<timestamp>.{md,html}
```

## Why the front half is a tool

The first version of this workflow had the agent assemble the search results
itself: call the portals, merge the JSON, pick the new ones, fetch the
postings, build the store file. It worked - and it also wrote its own helper
script and ran it as though it were a portal, because the agent had no tool
for the job and the permission rules were tight enough that improvising felt
like the only way through.

That is the failure mode worth designing against. A model given a long
multi-step procedure will write a parallel implementation of it when the
procedure is not backed by a tool. The parallel implementation is unreviewed,
it does not survive a fresh clone, and it quietly diverges.

So `tools/search_portals.py` now does the whole front half: it calls every
portal with the flags that portal documents, merges and normalises the hits,
drops what has been seen, orders the rest by fit, fetches the posting text
and runs the guard over it. The agent's job starts at scoring.

Two things follow from it.

**The ordering is deterministic.** `tools/relevance.py` scores each posting
against the persona's target roles, its skills and the user's location
preferences. No model is involved. The model still decides how well a posting
fits; this only decides which postings get looked at first, so a run with a
tight `--limit` spends its budget on the promising ones.

**Nothing is stranded.** The tool prepares the first `--limit` postings and
stores only those. The rest stay unseen, so a later run selects them. Storing
more than you score would strand the surplus: they would be "seen", so
nothing would select them again, and they would never be ranked.

## The state contract

Two files, two lifecycles.

`profiles/<persona>/state/seen_jobs.json` is written by two tools and read by
three. `scrape_state.py store` writes entries with `status: "new"` and the
schema it validates:

```json
{
  "title": "...", "company": "...", "url": "...", "location": "...",
  "first_seen": "YYYY-MM-DD",
  "posted_date": "YYYY-MM-DD or null",
  "deadline": "YYYY-MM-DD or null",
  "fit": "high | medium | low",
  "status": "new",
  "portal": "<portal skill name>",
  "source": "cli | websearch"
}
```

`rank_state.py apply` then adds `rank_score`, `rank_verdict`, `rank_date`,
`location_verdict`, `language_gate`, `language_note`, `strengths`, `gaps`,
`guard` and sets `status: "ranked"`.

The two tools have different status vocabularies on purpose: `store` accepts
`new`, `skipped` and `expired`; `rank_state` accepts `scored`, `expired` and
`unreachable` from the scoring agents and writes `ranked`.

**A store step that adds nothing when the selection was not empty is a
failure.** The command checks this and reports it, because a silent store
failure means the next run re-reports the same postings and the learning loop
never sees anything. This was a real bug: the first version of the command
called the store with the wrong schema, so `seen_jobs.json` stayed empty
through two real runs.

## Why a persona

A resume is a document. A persona is a search intent: a role family, a
seniority, a set of locations, a work mode. One person can have two personas
that use the same resume - a RAG-heavy one and an AI-backend-heavy one - and
the difference between them is the valuable part.

So a persona references one or more resumes, and carries its own state:

```
profiles/<persona>/
  profile.yaml
  PROFILE.md
  state/
    seen_jobs.json
    tracker.csv
    search-queries.md
    scratch/
```

Per-persona state is what makes a multi-user clone safe. Two people using the
same repository never share a `seen_jobs.json`, so one person's history never
suppresses the other's postings.

One persona is active at a time, chosen by `JOB_HUNTER_PERSONA` or by
`active_persona` in `profiles/index.json`. There is no "merge every persona"
mode, on purpose: a merged report is exactly the cross-contamination the
persona exists to prevent.

## Provenance

Every fact in `profile.yaml` carries where it came from:

```yaml
- name: RAG evaluation (RAGAS)
  weight: primary
  evidence: "resume:<resume-slug>#L11,L25-26"
```

That is what lets the report say "RAGAS evaluation" and be able to point at
the line of the resume that says so. The `## Evidence` section of the report
quotes those bullets and nothing else.

## The agents

| Agent | Mode | Can do | Why |
|---|---|---|---|
| `posting-scorer` | subagent | fetch, score, return JSON. **No write, no edit, no task.** | It holds untrusted posting text. An agent that cannot write cannot be steered by a posting. |
| `job-reporter` | subagent | search, dispatch the scorer, write reports. Edits limited to `reports/**` and `profiles/**/state/**`. Bash limited to the portal CLIs and this project's tools. | It needs to write, so it is constrained to where writing is expected. |

The command `/find-jobs` runs as `job-reporter` with `subtask: true`, so it
does not pollute the primary context.

## Why the queries are keywords only

A portal search matches against a job title and description. A query of
"Applied AI Engineer junior remote" matches nothing, because no job title
contains the word "remote".

So `profile_query.py` splits the intent:

- **Queries** - the role plus the candidate's signature skills:
  `Applied AI Engineer RAG`, `LLM Application Engineer`, `Document AI Engineer`.
- **Flags** - seniority, work mode, geography, recency and result cap:
  `--seniority junior --remote remote --region eu,uk --jobage 14 --limit 20`.

The mapping from a place to a portal's geography flags lives in two data
files: `config/places.yaml` holds the places and what each portal calls them,
`config/portals.yaml` holds which filters each portal has and the flag each
one uses. `tools/portal_map.py` joins them, and it widens a search down a
ladder - exact place, then parent region, then anywhere - reporting the rung
it landed on. A portal that cannot filter by seniority simply does not get a
seniority flag, and the seniority gate does the work at scoring time instead.

A place the catalogue does not know produces no search at all, and the run
says so. `tools/places.py` resolves what a person typed into a catalogue key,
or returns the candidates for the agent to ask about.

## Where the candidate is

The search says where to look. The location gate decides whether a posting
that comes back is somewhere the candidate could take the job, and those are
different questions. Conflating them is what makes a search for "roles in
Egypt" come back with nothing for a candidate who lives in Egypt.

Three facts make the difference, and all three are deterministic:

- **The home place.** `identity.location` says where the candidate lives. A
  place they already live in is a place they can serve, so an on-site role
  there is never gated out. `tools/location_gate.py` resolves it, and
  `tools/rank_state.py` will not let a home-place posting be vetoed on
  location grounds.
- **The servable places.** The user's own list, with the countries each one
  covers and the conditions attached to it - sponsorship, relocation, remote
  from home. The scorer is handed these and judges the posting's own wording
  against them; it never works out the geography for itself.
- **The market.** A portal that answers `--country EG` with postings in the
  UAE is not answering the question. `tools/market.py` checks a posting's own
  location string against the country that was searched, and drops the
  outliers before they cost a fetch and a model's attention.

## Where the layout rules live

`tools/paths.py` is the only place a path is written down. `tools/policy.py`
holds the shared constants. `tools/check_repo.py` holds the rules the
repository must keep satisfying, and the CI runs it on every change.

## Launch-time database isolation

`run.sh` (and `make run`) no longer shares the global OpenCode database.
Instead, it probes the OpenCode major version in a sandbox (using only
`--version` with `HOME` and `XDG_*` redirected to temporary directories),
then sets `XDG_DATA_HOME` to a Job Hunter–owned per-major directory:

```
$JOB_HUNTER_DATA_DIR/v<major>/opencode/opencode.db
```

This works on all OpenCode versions (v1.0.0 through v2.x) because all of
them honor `XDG_DATA_HOME` and place their database at
`$XDG_DATA_HOME/opencode/opencode.db`.

The global OpenCode database (`~/.local/share/opencode/opencode.db`) is
never read, opened, or modified. Run `make doctor` to see the Job Hunter
databases and their schema states.
