---
description: Find jobs matching your persona and report them with links, fit scores and tailored CV suggestions
agent: job-reporter
subtask: true
---

# /find-jobs - Find jobs and report them

Search the job boards for postings that match the active persona, score them
against the resume, and write a report with direct links. **Nothing is ever
applied to** - you apply yourself.

Arguments: `$ARGUMENTS`

## Arguments

| Argument | Meaning |
|---|---|
| `--persona <slug>` | Use a specific persona instead of the active one |
| `--limit <N>` | How many jobs to fetch and score (default 10) |
| `--top <N>` | How many jobs to show in the report (default 10) |
| `--focus "<text>"` | Only jobs whose title, company or notes match this text |
| `--report-only` | Report only - no tailored CV suggestions |
| `--personas` | List the available personas and stop |
| anything else | Treated as a focus term, like `--focus` |

`--limit` bounds the expensive work (fetching and scoring). `--top` only
bounds what appears in the report. Jobs past the limit are deferred, never
discarded - the next run picks them up.

## Steps

### Step 1: Resolve the persona

Read `profiles/index.json`. The persona is:

1. `--persona <slug>` if given, otherwise
2. the registry's `active_persona`, otherwise
3. the only persona that exists.

If none of those resolve, **stop** and list the personas in `profiles/`. Never
merge personas, never fall back to a hardcoded skill list.

### Step 2: Check the persona is current

```bash
python3 tools/profile_build.py --persona <persona> --check
```

If it reports a stale resume (the file on disk no longer matches the recorded
hash), stop and tell the user to run `/profile-build`. A persona built from an
older resume scores against facts the candidate no longer has.

### Step 3: Load the search contract

```bash
python3 tools/profile_query.py --persona <persona> --format json
```

This prints the whole contract: `search_queries`, `target_roles`,
`portal_targets`, `filters` and `provenance` (the resume, the evidence bullets
and the projects you may quote).

Also write the human-readable view for the run:

```bash
python3 tools/profile_query.py --persona <persona> --format markdown --out profiles/<persona>/state/search-queries.md
```

**The queries are keywords only.** Seniority, work mode, geography and recency
are portal flags and already appear in `portal_targets`. Never add "junior" or
"remote" to a query - no job title contains those words, and adding them
matches nothing.

### Step 4: Search, select and fetch

```bash
python3 tools/search_portals.py --persona <persona> --limit <limit>
```

**This one command does the searching, the selecting and the fetching.** It
reads the contract, calls every enabled portal with the flags that portal
documents, merges and normalises the hits, drops the ones already seen,
orders the rest by how well they fit the persona, keeps the first `--limit`,
fetches the full posting text, runs the guard over it, and writes:

- `profiles/<persona>/state/scratch/store.json` - the entries to store
- `profiles/<persona>/state/scratch/prepared.json` - the same postings, each
  with its key, its body file path and its guard verdict
- `profiles/<persona>/state/scratch/bodies/<key>.txt` - the posting text
- `profiles/<persona>/state/scratch/raw.json` - every hit, for reference

It prints a summary: `calls`, `hits`, `already_seen`, `new`, `prepared`,
`deferred`, `store_file`, `prepared_file` and `errors`.

- **Report the `errors` list** in the report. A portal that fails is skipped,
  never fatal.
- **Report `relaxed_searches`** in the report. A portal's facets are ANDed,
  and in a small market the stack can be empty - freehire with
  `--category ml_ai --seniority junior` returns nothing at all for Egypt. When
  that happens the tool drops a facet and searches again, and says so. Say it
  too: the search was wider than the filters suggest.
- **Report `widened_searches`** - a portal that could not express a place and
  searched a wider one instead.
- **Report `out_of_market`** - postings a portal returned from a country
  other than the one that was searched. They were dropped before scoring.
- `prepared` is how many postings this run will score. `deferred` is how many
  were found but not prepared - they stay unseen, so a later run picks them
  up. Nothing is lost.

Do not write your own helper script and do not run a portal CLI by hand. The
tool does all of it, and a hand-rolled script is not something you can
review.

If `prepared` is 0, there is nothing to score this run. Say so, report the
counts, and stop. That is a successful run, not a failure.

### Step 5: Store the prepared postings

```bash
python3 tools/scrape_state.py store --results profiles/<persona>/state/scratch/store.json --persona <persona>
```

**Always pass `--persona` to every state tool in this command.** Without it the
tool falls back to the *active* persona, so a run against `--persona other`
would deduplicate against - and then write into - a different persona's
history.

**Verify the store worked.** The tool prints `added` with the keys it wrote.
If `prepared` was non-empty and `added` is empty, the store failed - report
the error and **do not** claim the jobs were saved. A silent store failure
means the next run re-reports the same postings and the learning loop never
sees anything.

### Step 6: Score the postings

**This is the one step that needs the model.** Dispatch `posting-scorer`
subagents - one `task` call per batch of about five jobs, all in parallel.

Read `profiles/<persona>/state/scratch/prepared.json`. It holds one entry per
posting, each with:

- `key`, `title`, `company`, `url`, `location`, `portal`
- `body_file` - the posting text, already fetched and already guarded
- `guard` - the guard's verdict for that text
- `posted_date`, `deadline`, `work_mode`

Give each subagent, inline:

1. The jobs from its batch, each with its `key`, `title`, `company`, `url`,
   `body_file` and `guard`.
2. The scoring rubric: the persona's primary and secondary skills, the target
   roles, the seniority band, the location preferences and the visa-block
   phrases.
3. **`filters.home_place`** and **`filters.servable_places`** from the
   contract. These are the facts the location gate is judged against: where
   the candidate lives, and which places they can serve, with the countries
   each covers and its conditions (sponsorship, relocation, remote from
   home). The scorer does not work the geography out for itself.
4. The evidence bullets you may quote.

Do not make the agents re-read the profile files, and do not fetch the postings
again - `body_file` already holds the text.

**Do not score the postings yourself.** Score them in subagents, even when
there are only one or two. The scorer is an agent with no write permission
precisely because it holds untrusted posting text; scoring in the reporter
would defeat that.

Each agent returns a JSON array of scoring objects:

```json
{
  "key": "<the job's key in seen_jobs.json>",
  "status": "scored | expired | unreachable",
  "fetch_error": "<one short line, only when unreachable>",
  "scores": {"technical": 0-100, "experience": 0-100, "behavioral": 0-100, "career": 0-100},
  "location_verdict": "PASS | FAIL | FLAG",
  "location_note": "<the requirement and the reason, only when FLAG or FAIL>",
  "language_gate": "PASS | FAIL | FLAG",
  "language_note": "<the requirement and your level, only when FLAG or FAIL>",
  "deadline": "YYYY-MM-DD or null",
  "strengths": ["1-3 bullets, grounded in the posting"],
  "gaps": ["1-3 bullets, honest"],
  "language": "<the language the posting is written in>",
  "guard": "clean or the guard's verdict line"
}
```

`location_verdict` is the location gate, judged against `home_place` and
`servable_places`: `FAIL` when the posting needs the candidate to be somewhere
they cannot be or cannot get to, `FLAG` when it is possible but costly (heavy
travel, on-site in a country with no relocation route), `PASS` otherwise. The
agent must read the posting's own location and remote wording - not guess
from the title.

**A posting in the candidate's home place is never a location failure.** An
on-site role in the city the candidate lives in is a role they can take, and
`FAIL` on it is a mistake. `FAIL` a home-place posting only when the posting
itself asks for something else - relocation, a work permit, a language.

`language_gate` is `FAIL` when the posting requires a language the candidate
has not declared at all, `FLAG` when the bar reads above the declared level,
`PASS` otherwise.

### Step 7: Apply the scores

```bash
python3 tools/rank_state.py apply --results profiles/<persona>/state/scratch/<timestamp>-scored.json --persona <persona>
```

The tool computes the weighted score (technical 30%, experience 25%,
behavioral 15%, career 30%), maps it to a verdict band, applies the location
and language vetoes, stores the strengths and gaps, and sets each job's status
to `ranked`. It prints `ranked`, `vetoed`, `expired`, `unreachable`,
`location_overrides` and any `errors`.

`location_overrides` are postings the tool moved from `FAIL` to `FLAG`
because they are in the candidate's home place. Report them - the candidate
should see that the tool stepped in, and why.

If `errors` is non-empty, report them and do not present those jobs as scored.

### Step 8: Sweep the older entries

```bash
python3 tools/rank_state.py sweep --write --exclude "<the keys scored this run>" --persona <persona>
```

This retires ranked jobs whose deadline has passed and surfaces the ones
closing within seven days. It costs no fetch - it is a date comparison against
values already on disk. An entry with no deadline is left alone, never
guessed at.

### Step 9: Write the report

Write `reports/<persona>/jobs-<timestamp>.md` and the matching `.html`.

The report contains:

**Header** - persona, target roles, the resumes it was built from, the portals
searched, how many postings were found, how many were new, how many were
scored.

**Top matches** - at most `--top` jobs, highest score first. Each one shows:

- Title, company, location, portal
- Posted date and deadline
- **Work mode** - `Remote`, `Hybrid`, `On-site`, or `Not specified`, taken
  from the posting's own wording. Add a note when the posting restricts the
  location ("remote, US only").
- **Visa / sponsorship** - `Allowed`, `Not indicated`, or `Blocked`, with the
  quoted wording when it is blocked or restricted
- **Fit score** and verdict band
- **Direct link**
- **Key matches** - resume-backed, quoting the evidence bullets
- **Gaps** - stated honestly, never smoothed over
- **Why apply** - two or three bullets connecting the posting's requirements
  to the candidate's actual projects
- **Tailored CV suggestions** - unless `--report-only`. Two or three specific
  rewrites: which project to lead with, which bullet to reorder or reword,
  which skill to surface. Reference the project by the name in the profile.
  Never suggest claiming an experience the resume does not show.

**Excluded** - the vetoed jobs, each with the reason (location `FAIL` or
language `FAIL`) and the quoted requirement. These are not dropped silently:
the user needs to see what was filtered and why.

**Closing soon** - jobs with a deadline within seven days.

**Closing the loop** - the next steps: the direct links to apply, and the
suggestion to run this again later for new postings.

### Step 10: Report back to the user

In the conversation, give a short summary: how many jobs were found, how many
were new, the top three by score with their links, and where the full report
was written. Do not paste the whole report into the conversation - it is in the
file.

## Notes

- Every run learns: the next run reads the high-scoring jobs from
  `profiles/<persona>/state/seen_jobs.json` and uses what worked to refine the
  queries.
- The user applies. This command never submits anything, never contacts an
  employer and never writes to the tracker.
- If a portal is rate-limited or blocked, report it and continue with the
  others. A partial run with an honest summary beats a silent failure.
