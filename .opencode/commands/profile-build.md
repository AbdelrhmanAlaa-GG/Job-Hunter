---
description: Build or refresh a search persona from the resumes in resumes/ and the preferences in profiles/inputs.yaml
---

# /profile-build - Build or refresh a persona

Turns the resumes in `resumes/` plus the user's preferences into a persona:
a machine-readable file of derived facts, each backed by a line of a resume.

## Usage

- `/profile-build` - build or rebuild the active persona
- `/profile-build ai-llm-rag` - build or rebuild a named persona
- `/profile-build --check` - validate without writing

## Steps

### Step 1: Resolve the persona

Read `profiles/index.json` for `active_persona`. If the user named one, use
that. If the registry is empty, use the slug of the resume being built.

### Step 2: Extract the resume text

```bash
python3 tools/extract_resume.py --all
```

This writes plain text to `resumes/extracted/` and prints each resume's slug,
sha256 and character count. If a resume failed to extract, report it and stop
for that resume - never build a persona from a partial extraction.

### Step 3: Read the sources

Read, in parallel:

- every file in `resumes/extracted/`
- `profiles/inputs.yaml`

Do **not** read the PDF directly. The extracted text is the source of truth for
this step, and reading it keeps the build reproducible.

### Step 4: Write the persona file

Write `profiles/<persona>/profile.yaml` following the schema of the existing
persona file. The rules that matter:

- **Every fact carries evidence.** A skill, role, project or identity field
  records the resume slug and the line numbers it came from:
  `source: "resume:<slug>#L11,L18-19"`. A fact you cannot point at a line for
  does not go in the file.
- **Never invent.** Only state what the resume says. If the resume does not
  mention a skill, it is not a skill - not even if the user would like it.
- **Target roles come from the resume.** Order them by how strongly the
  resume supports them. The first role should be the one the resume's own
  summary and headline point at, not the most desirable title.
- **Skills carry a weight.** `primary` is a headline capability, `secondary`
  is supporting, `weak` is present but not a differentiator. Only `primary`
  and `secondary` skills are used to build search queries.
- **Evidence bullets are the strongest claims** a report may quote, each with
  its line reference.
- **Record conflicts.** If two resumes disagree about a fact, add it to
  `conflicts` rather than picking one.

### Step 5: Finalize

```bash
python3 tools/profile_build.py --persona <persona> --finalize
```

This validates the file, refreshes `profiles/index.json` and regenerates
`profiles/<persona>/PROFILE.md`. If it reports problems, fix the persona file
and run it again. Do not report success while problems remain.

### Step 6: Report

Tell the user:

- which persona was built and from which resume(s)
- the target roles, in priority order
- the primary skills
- anything that needs their decision (conflicts, missing fields)

## Notes

- The user's own preferences live in `profiles/inputs.yaml` and are never
  written here. This file holds only what the resumes say.
- `profiles/<persona>/PROFILE.md` is generated from both files. The
  `## User Notes` section at the bottom of it belongs to the user and is
  preserved when the aggregate is rebuilt.
