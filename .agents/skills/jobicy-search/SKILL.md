---
name: jobicy-search
version: 1.0.0
description: >
  Use this skill to search live remote job listings through the Jobicy public Jobs
  API — global remote roles for the USA, Canada, the UK, Europe, EMEA (which
  includes the UAE, Israel and Türkiye), APAC and LATAM, plus listings open to
  anyone. Invoke when the user wants remote jobs, work-from-home openings,
  postings they can apply to from their own country, or a specific listing
  looked up. Trigger phrases: find remote jobs, remote work, work from home,
  work from anywhere, jobs open to candidates outside the country, "are there
  any remote X jobs for someone in <place>", look up this job posting,
 找一个远程工作, البحث عن وظائف عن بعد.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/jobicy-search/cli/src/cli.ts *)
---

# Jobicy Search Skill

Search live remote job listings from the **[Jobicy](https://jobicy.com)** Jobs
API — an aggregator of remote openings across the USA, Canada, the UK, Europe,
EMEA, APAC and LATAM. **No authentication, no API key, and zero runtime
dependencies** — it runs with just `bun`.

Unlike a board that lists jobs in one country, every Jobicy listing carries an
*eligibility* — "Europe", "USA", "EMEA", "Anywhere" — so one query finds the
roles a candidate can take from where they sit. That makes it the board for
"remote in EU/USA" and for Gulf-region employers hiring remotely.

## When to use this skill

- Find remote roles open to a candidate in a particular country
- Search a job category across a region (software engineering, data science, DevOps)
- Look up one listing by its id or URL

## Commands

### Search job listings

```bash
bun run .agents/skills/jobicy-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keywords (job title, skill, role). Maps to the API's `tag` filter.
- `--location <slug>` / `-l <slug>` — location eligibility: `usa`, `canada`, `uk`, `europe`, `emea`, `latam`, `apac`, `anywhere`, `united-arab-emirates`, `israel`, `turkiye`, … Maps to the API's `geo` filter.
- `--industry <slug>` — category: `software-engineering`, `data-science`, `devops`, `design`, … Maps to the API's `industry` filter.
- `--jobage <days>` — listings published within N days, filtered client-side. The feed retains 7 days, so a wider window cannot be honoured and the CLI says so.
- `--page <n>` — 1-indexed page of the feed to start from. Costs one request per skipped page.
- `--cursor <token>` — continue from a cursor instead of walking to a page.
- `--limit <n>` / `-n <n>` — cap total results emitted (client-side).
- `--no-description` — drop each listing's full description, for a cheap discovery pass.
- `--format json|table|plain` — default `json`.

### List the API's own vocabulary

```bash
bun run .agents/skills/jobicy-search/cli/src/cli.ts search --list-locations --format table
bun run .agents/skills/jobicy-search/cli/src/cli.ts search --list-industries --format table
```

The location and category slugs are the API's, and they change when its taxonomy
changes. Ask the API for them rather than keeping a copy here.

### Fetch full job detail

```bash
bun run .agents/skills/jobicy-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the numeric listing id from `search` results. A full
`jobicy.com/jobs/<id>-<slug>` URL is accepted too. Returns the description,
seniority level, industries, employment types and salary range.

## Usage examples

```bash
# Remote Python roles open across Europe
bun run .agents/skills/jobicy-search/cli/src/cli.ts search -q "python" -l europe --limit 20 --format table

# Data science roles in EMEA, including UAE and Israel
bun run .agents/skills/jobicy-search/cli/src/cli.ts search -q "data scientist" -l emea --industry data-science --format table

# Backend roles open to applicants in the Gulf, posted in the last 3 days
bun run .agents/skills/jobicy-search/cli/src/cli.ts search -q "backend" -l united-arab-emirates --jobage 3 --format table

# Any remote role, anywhere
bun run .agents/skills/jobicy-search/cli/src/cli.ts search -q "software engineer" -l anywhere --limit 30 --format table

# One listing
bun run .agents/skills/jobicy-search/cli/src/cli.ts detail 154104 --format plain
```

## Output format

| Field | Notes |
|---|---|
| `id` | Numeric listing id; what `detail` consumes |
| `title` | Job title, entities decoded |
| `company` | Employer name, `null` when absent |
| `location` | The listing's eligibility (`Europe`, `USA`, `EMEA`, `Anywhere`, …) |
| `date` | Posting date, `YYYY-MM-DD` |
| `url` | The Jobicy listing URL |
| `geo`, `level` | Eligibility and seniority level |
| `industries`, `employment_types` | Category and contract type |
| `salary` | Range with currency and period, `null` when absent |
| `description` | Full text, HTML stripped, `null` with `--no-description` |

JSON output is `{ "meta": { "count", "page", "next_cursor", "has_more", "feed_window_days" }, "results": [...] }`.

## Notes

- **The feed is a rolling seven days.** Jobicy only serves listings published in the last week, so `--jobage` beyond 7 cannot be satisfied. The CLI filters client-side and warns on stderr rather than returning a week-old feed as if it were a month-old one.
- **The API paginates by opaque cursor, not by page number.** `--page` walks the cursor chain, so each skipped page costs a request. Use `--cursor` to continue a traversal you already have.
- **`detail` searches the feed.** There is no per-listing endpoint, so the CLI walks the feed to find the id. A listing older than seven days is no longer in it, and the CLI says so instead of reporting "not found" without explanation.
- **A bad location or category slug is rejected by the API** with a message naming the valid values. The CLI surfaces it and exits 1 — a wrong geography never returns the wrong market silently.
- **`jobDescription` is HTML.** It is stripped to plain text and entities are decoded, so the text a human reads has no tags in it.
- **Jobicy has no Egypt, Saudi Arabia, Qatar, Kuwait, Morocco or Jordan in its location taxonomy.** Its EMEA bucket covers Europe, Israel, Türkiye and the UAE. For Egypt and the wider Gulf, use `freehire-search`, which carries postings in those countries.

> **Terms.** Jobicy allows use of the public API in your own products, including
> commercial ones, **provided listings are credited to Jobicy and link back to
> their Jobicy URL** — which is the `url` this CLI reports. The public endpoint
> always returns Jobicy's own listing URL; a commercial API key returns the
> original employer's apply link instead. Do not use the API to build a spam
> network, and cache responses rather than polling continuously.
