# Templates

PII-free starting points. Copy what you need into the live tree.

| Template | Copy to | What it is |
|---|---|---|
| `PROFILE.example.md` | `profiles/<persona>/PROFILE.md` | The shape of the generated profile aggregate. Usually you do not need this - `/profile-build` generates it. |
| `../config/profiles.example/inputs.example.yaml` | `profiles/inputs.yaml` | Your preferences, locations, dealbreakers. **Start here.** |

## Setting up from scratch

```bash
mkdir -p profiles
cp config/profiles.example/inputs.example.yaml profiles/inputs.yaml
$EDITOR profiles/inputs.yaml
```

Then put a resume in `resumes/` and run `/profile-build` inside OpenCode.

## What never goes in here

Anything personal. The templates are tracked, the live files are not, and
`python3 tools/check_repo.py` fails the build if a personal file is tracked or
if a committed prompt contains a personal identifier.
