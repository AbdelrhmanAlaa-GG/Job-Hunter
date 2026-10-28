# Job Hunter Profile - <Persona title>

<!--
  This is an EXAMPLE of the generated profile aggregate.

  The real file lives at profiles/<persona>/PROFILE.md and is generated from
  three sources:
    - profiles/<persona>/profile.yaml   facts derived from your resume
    - profiles/inputs.yaml               your preferences
    - profiles/index.json                the persona registry

  Edit those, not this. The one exception is the "User Notes" section at the
  bottom, which is preserved exactly when the profile is rebuilt.

  Run /profile-build inside OpenCode to generate the real thing.
-->

- **Persona:** `<persona-slug>`
- **Active persona:** `<persona-slug>`
- **Built:** `<timestamp>`

## Sources

| File | Role | Editable by you |
|---|---|---|
| `profiles/<persona>/profile.yaml` | Resume-derived facts, with evidence | No - rebuilt from your resumes |
| `profiles/inputs.yaml` | Your preferences, locations, dealbreakers | **Yes** |
| `profiles/index.json` | Persona registry | Rarely |

## Resumes

| Slug | File | SHA-256 | Extracted text |
|---|---|---|---|
| `<slug>` | `resumes/<file>` | `<hash>` | `resumes/extracted/<slug>.txt` |

## Target roles

- **<Role>** (priority 1) - <why the resume supports this role>

## Skills

- **Primary:** <the headline capabilities>
- **Secondary:** <the supporting ones>

## Identity

- **Name:** <name>
- **Location:** <city, country>
- **Headline:** <the one-line summary>

## Education

- <degree, institution, date>

## Experience

- <role, organisation, dates>

## Evidence

Claims a report may quote. Each is backed by a line of your resume.

- <the strongest claim>  _(source: `resume:<slug>#L17-19`)_

## Projects

- **<Project>** - <what it is>

## Preferences

- **Seniority sought:** <tokens>
- **Seniority refused:** <tokens>
- **Work authorization:** <what an employer needs to do to hire you>

## Locations

| Region | Mode | Notes |
|---|---|---|
| <region> | <mode> | <note> |

## Dealbreakers

- <dealbreaker>

## Excluded by this persona

- <what this particular resume rules out>

## Conflicts

_None - every source resume agrees on the facts it states._

## User Notes

_Nothing here yet. Anything you write in this section is preserved when the
profile is rebuilt._
