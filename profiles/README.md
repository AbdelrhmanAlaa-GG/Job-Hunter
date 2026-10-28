# Profiles

Your personas live here. Nothing in this directory except this README is
tracked by git - your data is yours.

## What goes here

| Path | What it is | Who writes it |
|---|---|---|
| `inputs.yaml` | Your preferences: locations, seniority, work mode, dealbreakers, which portals to use | **You** |
| `index.json` | The persona registry - which persona is active | `/profile-build` |
| `<persona>/profile.yaml` | Facts derived from your resume, each with the resume lines that support it | `/profile-build` |
| `<persona>/PROFILE.md` | The generated aggregate you read | `/profile-build` |
| `<persona>/state/seen_jobs.json` | Every posting seen, with its score | The search command |
| `<persona>/state/tracker.csv` | Your application history | You |
| `<persona>/state/search-queries.md` | The last run's search contract | The search command |
| `<persona>/state/scratch/` | Intermediate files from a run | The search command |

## Getting started

```bash
cp config/profiles.example/inputs.example.yaml profiles/inputs.yaml
$EDITOR profiles/inputs.yaml
```

Then put a resume in `resumes/` and run `/profile-build` inside OpenCode.

## A persona

One persona is one search identity: a resume variant aimed at a role family,
plus the preferences that apply to it. Each has its own state, so two people
using the same clone never suppress each other's postings, and one person's
history never pollutes another's report.

## Keeping it private

`inputs.yaml` holds your name, your email and your phone number. It is
git-ignored, and `python3 tools/check_repo.py` fails the build if it is ever
tracked. Do not commit it, and do not paste it into a command, an agent or a
prompt file - those are tracked, and the same check scans them for personal
identifiers.

See [docs/privacy.md](../docs/privacy.md).
