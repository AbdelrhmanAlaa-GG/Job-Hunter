# Security Policy

## What this tool does and does not do

Job Hunter **finds** job postings and reports them. It does not apply to
anything, does not contact employers and does not write to your application
tracker. Applying is your job, by hand, through the link in the report.

## Your data

Everything personal stays on your machine unless you explicitly send it to a
model provider:

| Path | Contents | Git |
|---|---|---|
| `resumes/` | Your resume files and the extracted-text cache | Ignored |
| `profiles/` | Your preferences, your derived profile, your job state | Ignored |
| `reports/` | Generated job reports, which quote your profile | Ignored |

Run `python3 tools/check_repo.py` before you commit or push. It fails if any of
those paths is tracked, if a required ignore rule is missing, or if a
committed prompt or config contains a personal identifier.

**Your resume is sent to whichever model provider you have configured in
OpenCode.** That is outside this tool's control. Check your provider's data
retention terms, and pick one that does not train on your input, before you
put a real CV in `resumes/`. Some free model endpoints explicitly prohibit
personal or confidential data.

## Untrusted content

Job postings are untrusted input. A posting may contain text that tries to
instruct the model - to ignore its rules, to exfiltrate data, to apply to
something. Every fetched posting passes through `tools/web/posting_guard.py`
before it is read.

The guard is **advisory**. It flags suspicious content so you can see it; it
does not authorise anything. The real protections are structural:

- The agent that reads posting text (`posting-scorer`) cannot write, edit or
  dispatch other agents.
- The agent that writes reports may only write under `reports/` and
  `profiles/*/state/`.
- Bash access is scoped per agent to the project's own tools.
- Nothing in the workflow can submit an application.

If the guard flags a posting, the report says so. Treat a flagged posting as
data, not as instructions.

## Portal terms

The portal CLIs in `.agents/skills/` query public job boards. Their terms
apply to you:

- **LinkedIn** - the `linkedin-search` skill is documented as being for
  personal use only. Do not run it at volume, and do not use it commercially.
- **Jobicy** - the public API may be used commercially provided listings are
  credited to Jobicy and link back to their Jobicy URL, which the CLI already
  reports.
- Other portals have their own terms. Read them before relying on a portal,
  and prefer the boards that publish a public API.

Keep request volume modest. A rate-limited or blocked portal is reported, not
retried aggressively.

## Reporting a problem

If you find a way to make this tool leak personal data, apply to a job without
being asked, or bypass the permission boundaries, open an issue describing it
- but **do not include your own resume, profile or reports in the issue**.
Use a generic description and a redacted example.

## Adding a portal

A portal CLI's `package.json` must not declare an npm/bun lifecycle script
(`preinstall`, `install`, `postinstall`, `prepare`, `prepack`) or
`trustedDependencies`. Those run code at install time.
`tools/install_portal_clis.py` refuses such a manifest and
`tools/check_repo.py` fails the build on one. Read the code before you
install a portal you did not write.
