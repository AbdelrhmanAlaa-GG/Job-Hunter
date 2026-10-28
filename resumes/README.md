# Resumes

Put every resume you want the job finder to read in this directory.

## What goes here

- One file per resume variant. A variant is a resume aimed at a different kind
  of role (for example one aimed at RAG/LLM work and another aimed at ML
  backend work).
- Supported formats: `.pdf`, `.docx`, `.txt`.
- These files are **never committed**. The whole directory is ignored except
  this README.

## Naming

Use this pattern so the system can tell your variants apart:

```
<owner-slug>--<variant-slug>--v<YYYYMMDD>.<ext>
```

For example:

```
<owner-slug>--ai-llm-rag--v20261027.pdf
<owner-slug>--ml-backend--v20261028.pdf
```

- `owner-slug` - your name in lowercase kebab-case (`<owner-slug>`)
- `variant-slug` - the role family this resume targets (`ai-llm-rag`)
- `v<YYYYMMDD>` - the date of that revision, so versions of the same resume
  sort chronologically

Any filename works for a single resume, but naming matters once you have more
than one: the slug becomes the key that identifies which resume produced which
search queries and report.

## Extracted text

`tools/extract_resume.py` reads the files here and writes plain text into
`resumes/extracted/`. That cache is generated - never edit it, and never treat
it as the source of truth. If you change a resume, re-run the profile build and
the cache is regenerated:

```bash
python3 tools/profile_build.py --persona <persona-slug>
```

## Privacy

Everything in this directory is personal data and is excluded from git by
`.gitignore`. Keep it that way - the repository is meant to be publishable.
