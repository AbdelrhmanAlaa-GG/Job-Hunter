# Portals

Three portal CLIs live in `.agents/skills/`, each with a `SKILL.md` documenting
its exact flags and a `cli/` written in TypeScript. `freehire-search` and
`linkedin-search` are vendored from the upstream `ai-job-search` project;
`jobicy-search` was written for this repository.

## Which ones run

A portal runs only when **all** of these hold:

1. Its `SKILL.md` frontmatter does not set `enabled: false`.
2. `profiles/inputs.yaml` does not set `search.portals.<name>.enabled: false`.
3. Its CLI is installed - `bun install` at the repository root installs them
   from the workspace lockfile.

Currently enabled by default: `freehire-search`, `linkedin-search` and
`jobicy-search`.

## The portals

### `freehire-search`

An aggregator over roughly fifty ATS platforms, normalised into one schema.
The broadest coverage in the set, and the only one that returns full
descriptions in its search output - no per-hit detail fetch needed.

| Flag | Notes |
|---|---|
| `-q` | Keyword query |
| `--region` | `global`, `eu`, `uk`, `north_america`, `latam`, `apac`, `mena`, `africa`, `cis`, `none` |
| `--country` | ISO-3166 alpha-2. `us` is a country, not a region - `--region us` matches nothing |
| `--city` | **Ignored by the API.** Accepted, then discarded. Never sent |
| `--seniority` | `junior`, `middle`, `senior`, `staff`, `principal`, `lead` |
| `--category` | `backend`, `frontend`, `fullstack`, `devops`, `ml_ai`, `qa` |
| `--remote` | `remote`, `hybrid`, `onsite`. Comma-separate for OR |
| `--jobage` | Posted within N days |
| `--limit` | Results per page, default 25 |

`--region`, `--country` and `--city` are one OR group. A posting whose region
could not be resolved is only matched by `--region none`.

Two things to know, both verified against the live API:

- **The `eu` bucket already contains UK postings.** `--region eu,uk` returns
  exactly what `--region eu` returns. There is no EU-only value.
- **An unknown `--region` value does not fail.** The API writes
  `REGION_VALUE_UNKNOWN` to stderr and exits 0, so the run would look
  successful while returning the wrong market. The runner reads stderr, so
  this is now reported as a warning.

**Zero runtime dependencies** beyond bun.

### `linkedin-search`

LinkedIn's public job board, for any country and remote. Zero runtime
dependencies.

| Flag | Notes |
|---|---|
| `--location` | **Required.** A place string, or `Remote` |
| `--query` | Keyword search |
| `--jobage` | `1`, `7`, `14`, `30` days |
| `--remote` | `remote`, `hybrid`, `onsite` - one at a time |
| `--limit` | Client-side cap |
| `--format` | `json`, `table`, `plain` |

The `detail` command returns `isActive`. `false` means the posting page
itself renders LinkedIn's "no longer accepting applications" banner - the job
died between being indexed and being fetched. Treat that as expired, not as a
posting to report.

**LinkedIn resolves place strings silently and wrongly.** A string it does not
recognise falls back to an unrelated market - no error, just the wrong
country. These were checked against the live API:

| You would write | LinkedIn answers with | Use instead |
|---|---|---|
| `Jordan` | Berwick, Pennsylvania | `Amman, Jordan` |
| `Lebanon` | Exton, Pennsylvania | `Beirut, Lebanon` |
| `Armenia` | Pereira, Colombia | `Yerevan, Armenia` |
| `Georgia` | Atlanta, Georgia | `Tbilisi, Georgia` |
| `Czech Republic` | Santo Domingo | `Czechia` |
| `Viet Nam` | Springfield, Missouri | `Vietnam` |
| `Gulf` | Armidale, Australia | `Middle East` |
| `Arabian Peninsula` | Zamboanga, Philippines | `Middle East` |
| `Levant` | Colby, Kansas | `Middle East` |
| `CIS` | Bolzano, Italy | - (no value works) |
| `Worldwide` | Singapore | `Remote` |

`config/places.yaml` stores the working value for every place, so this is
handled for you. The table is here because it is the reason the catalogue
exists.

> **Terms.** The skill documents LinkedIn as being for **personal use only**.
> Do not run it at volume, and do not use it commercially. Other boards'
> terms apply to you too.

### `jobicy-search`

The [Jobicy](https://jobicy.com) public Jobs API - remote listings aggregated
across many countries, each tagged with the **eligibility** it is open to.
Zero runtime dependencies, no API key.

| Flag | Notes |
|---|---|
| `--query` | Keyword search, maps to the API's `tag` filter |
| `--location` | An eligibility slug: `usa`, `canada`, `uk`, `europe`, `emea`, `latam`, `apac`, `anywhere`, `united-arab-emirates`, … |
| `--industry` | A category slug: `software-engineering`, `data-science`, `devops`, … |
| `--jobage` | Filtered client-side; the feed only retains 7 days |
| `--page` / `--cursor` | The API paginates by opaque cursor; `--page` walks to it |
| `--limit` | Client-side cap |
| `--no-description` | Drop descriptions for a cheap discovery pass |
| `--format` | `json`, `table`, `plain` |

`--list-locations` and `--list-industries` ask the API for its own vocabulary,
so the slugs are never guessed from a stale local copy.

**Two things to know.** The feed is a rolling seven days, so `--jobage` wider
than 7 cannot be honoured - the CLI filters what it has and warns. And the
`detail` command finds a listing by walking the feed, because the API has no
per-listing JSON endpoint; a listing older than seven days is gone from it and
the CLI says so.

**Coverage.** Jobicy's location taxonomy has **no Egypt, Saudi Arabia, Qatar,
Kuwait, Morocco or Jordan**. Its `emea` bucket covers Europe, Israel, Türkiye
and the UAE. For Egypt and the wider Gulf, use `freehire-search`.

> **Terms.** Jobicy's public API may be used commercially provided listings
> are credited to Jobicy and link back to their Jobicy URL - which is the
> `url` this CLI reports. See the skill's `SKILL.md`.

## How a place becomes a search

A place is not searched the same way on every portal, and it is not searched
the same way on one portal for every place. `config/places.yaml` holds the
geography and `config/portals.yaml` holds the mechanism:

| File | What it holds |
|---|---|
| `config/places.yaml` | 10 regions and 158 countries, the names people use, and the value each portal takes for each one |
| `config/portals.yaml` | Which filters each portal has, the flag each one uses, and which of them the portal actually honours |

The two are joined by a **ladder**: the place itself, then its parent region,
then "anywhere". The rung that was used is reported, so a widened search is
never mistaken for an exact one.

| Place | freehire | LinkedIn | Jobicy |
|---|---|---|---|
| Egypt | `--country EG` | `--location Egypt` | `--location emea` - **wider**, no Egypt slug |
| Germany | `--country DE` | `--location Germany` | `--location germany` |
| MENA | `--region mena` | `--location "Middle East"` | `--location emea` - **wider** |
| European Union | `--region eu` - **wider**, holds UK postings | `--location "European Union"` | `--location europe` - **wider** |
| North America | `--region north_america` | `--location "North America"` | `--location usa` and `--location canada` - two searches |
| EMEA | `--region eu,uk,mena,africa` | three searches: Europe, Middle East, Africa | `--location emea` |
| CIS | `--region cis` | **no value** - falls back to anywhere | **no value** - falls back to anywhere |
| Anywhere | `--region global,none --remote remote` | `--location Remote --remote remote` | `--location anywhere` |

A place the catalogue does not know produces **no search at all**, and the run
says so:

```bash
python3 tools/places.py --resolve "atlantis"
```

That is deliberate. A search that quietly answers a different question is
worse than no search, because it looks like it worked.

### The work mode

`remote`, `hybrid` and `onsite` are sent as the portal's own work-mode
filter. A mode that accepts **more than one** way of working -
`onsite_remote_hybrid` or `remote_or_relocation` - is sent with **no
work-mode filter at all**.

That is not a shortcut. `--remote remote,hybrid,onsite` looks equivalent and
is not: it drops every posting that declares no work mode, and in a market
such as Egypt that is most of them. It also costs three searches on LinkedIn
instead of one. The mode is reported on each target, and the target's note
says which way it was translated.

### The facets

A portal's facets are ANDed. In a small market the stack can be empty:
freehire with `--category ml_ai --seniority junior` returns nothing at all
for Egypt, Germany, the UAE and Saudi Arabia, and plenty for the United
States. When a search finds nothing, the tool drops a facet - the category
first, then the seniority - and searches again. Every relaxation is reported
in the run summary as `relaxed_searches`. A search that found nothing is not
the same as a market that has nothing.

### The market check

Portals leak. freehire answers `--country EG` with postings in the UAE and
Kazakhstan; LinkedIn answers `--location United States` with Toronto. Before
a posting is scored, its own location string is checked against the country
that was searched, and a posting that names a different country is dropped.
The count is reported as `out_of_market`.

Only an exact country target is checked, and only a posting that names a
country is judged. "Cairo" names no country, so it is kept - a city is not a
contradiction, and throwing it away would lose exactly the postings that
matter in a small market.

## Boards without a CLI

These are reached by site-scoped web search, configured under
`search.site_queries` in `profiles/inputs.yaml`. The `{q}` placeholder is
replaced with each generated query.

| Board | Covers |
|---|---|
| `dice.com` | US tech and engineering, strong for AI/ML |
| `wellfound.com` | US startups, the most junior-friendly of the set |
| `otta.co` | Curated roles, transparent pay ranges |
| `ziprecruiter.com` | US, broad |
| `naukrigulf.com` | Gulf |
| `bayt.com` | Gulf and the wider region |
| `gulftalent.com` | Gulf |
| `weworkremotely.com` | Remote worldwide |
| `euraxess.ec.europa.eu` | EU research and industry |

A web search needs a search provider. `run.sh` sets `OPENCODE_ENABLE_EXA=1`;
the OpenCode provider works too.

## Adding a portal

1. Put it in `.agents/skills/<name>/` with a `SKILL.md` documenting the exact
   flags, and a `cli/` with a `package.json`.
2. The manifest must not declare a lifecycle script
   (`preinstall`, `install`, `postinstall`, `prepare`, `prepack`) or
   `trustedDependencies`. `tools/install_portal_clis.py` refuses such a
   manifest and `tools/check_repo.py` fails the build on one.
3. Add it to `config/portals.yaml`, listing only the filters it actually
   honours. A filter the portal documents but ignores is marked
   `supported: false` and is never sent.
4. Give its geography facet a place in `config/places.yaml`, with the value
   that portal takes - and **verify that value against the live API**. A place
   string that resolves to the wrong market is the failure this catalogue
   exists to prevent.
5. Add it to `profiles/inputs.yaml` under `search.portals`.
6. Check its terms, and respect them.

The SKILL.md is the contract. The command reads it and uses its own
documented flags - it never guesses a flag.

`tools/tests/test_portal_drift.py` reads each portal's own `search --help` and
fails the build if `config/portals.yaml` names a flag the portal does not
have. The matrix cannot rot unnoticed.
