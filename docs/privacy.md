# Privacy

## The one-sentence version

Your resume, your profile and your reports never leave your machine except as
prompts to the model provider you configured in OpenCode, and as requests to
the job boards you are searching.

## What is on disk

| Path | Contents | Git |
|---|---|---|
| `resumes/*.pdf`, `*.docx`, `*.txt` | Your resume files | Ignored |
| `resumes/extracted/*.txt` | The extracted text, regenerated on demand | Ignored |
| `profiles/inputs.yaml` | Your contact details, preferences, locations, dealbreakers | Ignored |
| `profiles/<persona>/profile.yaml` | Facts derived from your resume, with evidence | Ignored |
| `profiles/<persona>/PROFILE.md` | The generated aggregate you read | Ignored |
| `profiles/<persona>/state/` | The postings seen, the tracker, the scratch files | Ignored |
| `reports/<persona>/` | Generated reports, which quote your profile | Ignored |

Nothing in those paths is tracked. `python3 tools/check_repo.py` fails the
build if one of them is tracked, and the CI runs that check on every change.

The only files under `resumes/` that are tracked are `resumes/README.md` and
`profiles/`'s sibling `config/profiles.example/inputs.example.yaml`, both of
which are PII-free by construction.

## What leaves your machine, and when

| Action | What goes out | Where |
|---|---|---|
| `/profile-build` | Your resume text | The model provider |
| `/find-jobs` - search | The search keywords | The job boards |
| `/find-jobs` - fetch | A request for a posting URL | The job board, and the model provider once the text is read |
| `/find-jobs` - score | The posting text | The model provider |
| `/find-jobs` - report | Nothing. The report is written locally. | - |

There is no telemetry, no analytics and no network call the tool makes on its
own.

## The model provider is the thing to check

**Your resume is sent to whatever provider you have configured in OpenCode.**
This tool cannot control that, and it is the most important privacy decision
you will make.

Check your provider's terms before you put a real CV in `resumes/`. In
particular:

- Some free or trial model endpoints explicitly prohibit personal or
  confidential data, or log prompts for safety review.
- Some providers train on inputs unless you opt out or use a zero-retention
  endpoint.
- OpenCode's own model catalogue records which models are zero-retention and
  which are not.

This project deliberately does **not** pin a model in `opencode.json`. An
earlier version pinned a third-party trial model, which would have steered
every user's CV into that endpoint by default. The model is your choice.

## Untrusted content

A job posting is written by whoever wants to hire you, or by whoever scraped
the posting. It is not trusted input, and it may contain text that tries to
instruct the model.

Every fetched posting passes through `tools/web/posting_guard.py` before it is
read, and the verdict is carried into the report so you can see it.

The guard is advisory. The real protection is structural: the agent that reads
posting text cannot write, edit or dispatch other agents, and the agent that
can write may only write under `reports/` and `profiles/*/state/`.

## The tracker

`profiles/<persona>/state/tracker.csv` exists so postings you have already
handled are not reported again. The current workflow never writes to it -
applying is manual - but it is the column that would hold your application
history, so it is treated as personal data and ignored.

## Before you push

```bash
python3 tools/check_repo.py
git status --short
```

The check verifies that the personal paths are ignored, that none of them is
tracked, that the required ignore rules are present, and that no committed
prompt or config file contains a personal identifier.

The identifier check does not keep a list of personal strings - that list
would itself be the leak. It reads your untracked `profiles/inputs.yaml` and
your persona's `profile.yaml`, works out what your name, your contact details
and your project names are, and then checks that none of them appear in a
tracked file. In a fresh clone there is nothing to compare against, so it
falls back to generic patterns for email addresses and phone numbers.

Then confirm there is no remote pointing somewhere public:

```bash
git remote -v
```

The repository is meant to be publishable. Keep it that way.

## If something personal was committed by mistake

Removing a file from the working tree is not enough. The value stays in the
git history, and anyone who clones the repository gets it.

The fix is to rewrite the history, replacing the value in every commit:

```bash
# Install once: pip install git-filter-repo
git filter-repo --replace-text replacements.txt --force
```

`replacements.txt` holds one `literal:==>replacement` line per value. Then
expire the reflog and drop the unreachable objects, or the old commits stay
in the object store:

```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

If the repository was never pushed, there is nothing to coordinate and no
one else to notify. If it was, the rewritten history has to replace it, and
everyone who cloned it needs to re-clone.
