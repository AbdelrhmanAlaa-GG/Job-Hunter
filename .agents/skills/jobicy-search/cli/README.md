# jobicy-cli

Search global remote job listings through the Jobicy public Jobs API.

No API key, no authentication, **zero runtime dependencies** — plain `bun`,
`fetch` and JSON parsing.

## Usage

```bash
bun run src/cli.ts search -q "python" -l europe --limit 20 --format table
bun run src/cli.ts search --list-locations --format table
bun run src/cli.ts detail 154104 --format plain
```

Run `bun run src/cli.ts search --help` for the full flag list.

## Install

The repository root is a bun workspace, so `bun install` at the root installs
this CLI along with the others. To work on it alone:

```bash
cd .agents/skills/jobicy-search/cli
bun install
bun run typecheck
bun test
```

## Design notes

- **The API validates its own vocabulary.** A bad `geo` or `industry` slug
  comes back as a 400 with a message naming the valid values, so the CLI
  surfaces it and exits 1 rather than retrying or guessing.
- **`--jobage` is filtered client-side.** The feed only retains seven days, so
  a wider window cannot be honoured. The CLI filters what it has and warns on
  stderr when the window is wider than the feed.
- **`--page` walks the cursor chain.** The API paginates by opaque cursor, so
  each skipped page costs one request. `--cursor` continues a traversal
  directly.
- **`detail` searches the feed.** There is no per-listing JSON endpoint — only
  the HTML page — so the id is located by walking the feed. A listing older
  than seven days is no longer in it, and the CLI says so.
- **HTML is stripped, entities decoded.** `jobDescription` is HTML; the text a
  human reads has no tags in it.
- **Unknown flags are rejected.** A discarded filter changes what a search
  returns with no error, so an unknown flag exits 1 with a JSON error on
  stderr.

## Output

JSON is `{ "meta": { "count", "page", "next_cursor", "has_more", "feed_window_days" }, "results": [...] }`,
where each result carries `id`, `title`, `company`, `location`, `date`, `url`,
`geo`, `level`, `industries`, `employment_types`, `salary` and `description`.

Errors are `{"error": "...", "code": "..."}` on stderr with exit code 1.

## Terms

Jobicy's public API may be used in your own products, including commercial
ones, provided listings are credited to Jobicy and link back to their Jobicy
URL. See `../SKILL.md`.
