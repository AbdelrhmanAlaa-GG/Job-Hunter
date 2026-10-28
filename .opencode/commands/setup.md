---
description: Set up Job Hunter from scratch - your resumes, your target roles, and the places and portals to search
---

# /setup - Set up Job Hunter

Build a working configuration from nothing: where the resumes are, what the
roles are, and which places and portals to search. **Ask the user - do not
invent answers.** Every choice here changes what a run finds.

Arguments: `$ARGUMENTS`

## Arguments

| Argument | Meaning |
|---|---|
| `--resume <path>` | Add a resume file (repeatable) |
| `--place <place>` | Add a place to search (repeatable), e.g. `Egypt`, `Germany`, `MENA` |
| `--mode <mode>` | Work mode for the places: `remote`, `hybrid`, `onsite` |
| `--persona <slug>` | The persona slug to create (default: derived from the role) |
| `--reset` | Start the inputs file over, keeping the resumes |

## What this command does

1. **Find the resumes.** Ask for the paths, or look for PDF and DOCX files in
   `resumes/`. If there are none, say so and stop - there is nothing to build
   a persona from.
2. **Extract them.** Run `python3 tools/extract_resume.py` on each file.
3. **Ask the questions below**, one step at a time.
4. **Write `profiles/inputs.yaml`** from `config/profiles.example/inputs.example.yaml`.
5. **Build the persona.** Run `/profile-build`.
6. **Show the result.** Run `python3 tools/profile_query.py --persona <slug>`
   and read the portal targets back to the user, including any that were
   widened or skipped.

## The questions

Ask these with the `question` tool. Offer the options given; the user can type
their own instead.

### 1. Which roles?

Offer the role families this repository knows about, but let the user write
their own - the persona is built from their resume, not from a menu.

- **AI / LLM / RAG Engineer** - applied AI, LLM applications, RAG pipelines
- **Backend Engineer** - APIs, services, data
- **Data Engineer / Data Scientist** - pipelines, analytics, modelling
- **DevOps / Platform Engineer** - infrastructure, CI, deployment
- **Frontend Engineer** - web interfaces
- **Full-stack Engineer** - both sides
- **Other** - they write it in

### 2. Which seniority?

| Level | Who it is for |
|---|---|
| `junior` | 0-2 years, or a graduate. The default for a new graduate. |
| `middle` | 2-5 years |
| `senior` | 5+ years |

### 3. Which places?

**This is the most important question**, because a place the catalogue does
not know produces no search at all.

Ask for the places as free text, then resolve them:

```bash
python3 tools/places.py --resolve "<what the user said>"
```

- If it resolves, use the place key it returns.
- If it does **not** resolve, do not guess. Show the user the candidates the
  command returns and ask which one they meant. If none of them fit, say the
  place is not in the catalogue and offer to add it to `config/places.yaml`.

The catalogue covers 10 regions and 158 countries. See
`python3 tools/places.py --list all`.

### 4. Which work mode?

For each place, ask how they want to work there:

| Mode | Meaning |
|---|---|
| `remote` | Remote only. The default when the candidate cannot relocate. |
| `hybrid` | Hybrid only. |
| `onsite` | On-site only. |
| `onsite_remote_hybrid` | Any of the three. |

### 5. Which portals?

All three are enabled by default:

| Portal | Best for |
|---|---|
| `freehire-search` | The broadest coverage. Many markets, one API, full descriptions in the search output. |
| `linkedin-search` | Every market, and the biggest single source of postings. Personal use only per its terms. |
| `jobicy-search` | Remote roles by eligibility. Good for EU, US, Canada and EMEA. No Egypt, Saudi or Qatar. |

Offer each as enabled or disabled, and explain the trade-off in one line.

### 6. Any board without a CLI?

`search.site_queries` reaches boards that have no API, through a site-scoped
web search. The defaults cover Dice, Wellfound, Otta, Naukrigulf, Bayt and
WeWorkRemotely. Add the ones the user cares about.

**Note:** a web search needs a search provider. `run.sh` sets
`OPENCODE_ENABLE_EXA=1` for this; if the user runs `opencode` directly, they
need the OpenCode provider or `OPENCODE_ENABLE_EXA=1` in their environment.

## The presets

When the user has not said, these are the starting points. They are
**suggestions, not defaults** - ask before using them.

### Egypt-first (the common case for a candidate based in Egypt)

```yaml
preferences:
  locations:
    - place: Egypt
      mode: onsite_remote_hybrid
    - place: MENA
      mode: remote
    - place: Europe
      mode: remote
    - place: United States
      mode: remote
  work_authorization: >-
    Egyptian citizen. Roles outside Egypt need the employer to sponsor a work
    permit or provide relocation; roles that are silent on it are treated as
    unverified rather than assumed to be open.
```

Read the four entries as: roles based in Egypt, remote roles open across the
Arab region, remote roles open across Europe, and remote roles in the US.

### Fully remote, anywhere

```yaml
preferences:
  locations:
    - place: Anywhere
      mode: remote
```

### One country only

```yaml
preferences:
  locations:
    - place: Germany
      mode: onsite_remote_hybrid
```

## Writing the inputs file

Copy `config/profiles.example/inputs.example.yaml` to `profiles/inputs.yaml`
and fill it in. Do not write into `config/` - that file is the published
example and must stay free of personal data.

Keep these keys as they are in the example:

- `preferences.seniority.include` and `exclude` - the words that mark a
  posting as the right level
- `filters.visa_block` - the phrases that mean "this will not work for me"
- `filters.location_block` - the phrases that mean "on-site, and I cannot"
- `search.recency_days` and `search.limit_per_query`

The `locations` entries take:

| Key | Meaning |
|---|---|
| `place` | The place, as a name or a catalogue key. `region` still works. |
| `mode` | `remote`, `hybrid`, `onsite` or `onsite_remote_hybrid` |
| `requires_sponsorship` | The role must sponsor a work permit |
| `allows_relocation` | The employer will relocate the candidate |
| `remote_from_home` | The role explicitly allows working from the candidate's home country. Free text - `conditional`, `yes`, `must say so`. |
| `note` | A note for the candidate. Free text. |

## What to tell the user afterwards

Run the contract and read it back:

```bash
python3 tools/profile_query.py --persona <slug> --format markdown
```

Report, in this order:

1. **The places** that will be searched, and **how each one is expressed on
   each portal**. A portal that cannot express a place searches a wider one -
   say which, and say why.
2. **Any place that was skipped**, and why.
3. **Any place the catalogue did not recognise**, so the user can correct it.
4. **The portals** that will run.

Never present a widened search as an exact one. If Jobicy has no Egypt slug
and the search runs across EMEA instead, that is what the user gets - so say
it.

## Rules

- **Never invent an answer.** Every field in `profiles/inputs.yaml` comes from
  the user.
- **Never write a personal detail into `config/`.** It is published.
- **Never commit `profiles/`.** It holds the user's data.
- **Never apply to anything.** Setup stops at the configuration.
