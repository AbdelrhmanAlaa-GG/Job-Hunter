#!/usr/bin/env bun
// Self-contained CLI for searching jobs on the Jobicy public Jobs API — global
// remote listings for the USA, Canada, Europe, EMEA, APAC and LATAM. No API key,
// so it runs anywhere `bun` is available with zero install beyond the repo clone.
//
// Jobicy's terms allow use in your own products: credit the source and link
// back to the listing. The public endpoint always returns Jobicy's own listing
// URL, which is what this CLI reports and what the report links to.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { runTaxonomy, type TaxonomyOpts } from "./commands/taxonomy.js"
import { FEED_WINDOW_DAYS } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("--") || a.startsWith("-")) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (next === undefined || next.startsWith("-")) {
        flags[key] = true
      } else {
        flags[key] = next
        i++
      }
    } else {
      ;(flags._ as string[]).push(a)
    }
  }
  return flags
}

const HELP = `jobicy-cli — search global remote jobs on the Jobicy Jobs API

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, or role). Mapped to the API's tag filter.
  --location, -l <slug>   Location eligibility slug: usa, canada, europe, uk, emea,
                          latam, apac, anywhere, united-arab-emirates, israel, turkiye, ...
                          Mapped to the API's geo filter. Run --list-locations for the full list.
  --industry <slug>       Category slug: software-engineering, data-science, devops, ...
                          Run --list-industries for the full list.
  --jobage <days>         Only listings published within N days, filtered client-side.
                          The feed retains ${FEED_WINDOW_DAYS} days, so a wider window cannot be honoured.
  --page <n>              1-indexed page of the feed to start from. Costs one request per skipped page.
  --cursor <token>        Continue from a cursor instead of walking to a page.
  --limit, -n <n>         Cap results emitted (client-side).
  --no-description        Drop each listing's full description from the output.
  --format <fmt>          json (default) | table | plain.

TAXONOMY FLAGS
  --list-locations        Print the API's location slugs and exit.
  --list-industries       Print the API's category slugs and exit.

EXAMPLES
  bun run src/cli.ts search -q "python" -l europe --limit 20 --format table
  bun run src/cli.ts search -q "data scientist" -l emea --industry data-science --format table
  bun run src/cli.ts search -q "backend" -l united-arab-emirates --jobage 3 --format table
  bun run src/cli.ts detail 154104 --format plain

Jobicy listings must be credited and linked back to their Jobicy URL.
`

// Long-form flag names each command accepts (parseFlags resolves the short
// aliases q/l/n to these before validation). "help"/"h" pass so `search --help`
// still prints usage.
const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set([
    "query",
    "location",
    "industry",
    "jobage",
    "page",
    "cursor",
    "limit",
    "no-description",
    "format",
    "list-locations",
    "list-industries",
    "help",
    "h",
  ]),
  detail: new Set(["format", "help", "h"]),
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  // Reject unknown flags instead of silently discarding them: a discarded
  // filter changes what the search returns with no error, and a wrong flag name
  // once returned an entire portal's database as if it matched the query.
  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      process.stderr.write(
        JSON.stringify({
          error: `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help for the supported flags`,
          code: "UNKNOWN_FLAG",
        }) + "\n",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "table", "plain"].includes(fmt)) {
      process.stderr.write(
        JSON.stringify({ error: `--format must be one of json|table|plain, got "${fmt}"`, code: "BAD_ARG" }) + "\n",
      )
      return 1
    }

    if (flags["list-locations"] === true || flags["list-industries"] === true) {
      const opts: TaxonomyOpts = {
        kind: flags["list-locations"] === true ? "locations" : "industries",
        format: fmt as TaxonomyOpts["format"],
      }
      return runTaxonomy(opts)
    }

    // --query is optional, but a present one needs keywords: parseFlags stores
    // a bare -q as true and -q "" as "", and both would otherwise be treated as
    // unset, returning every listing as if it matched.
    if (flags.query !== undefined && (typeof flags.query !== "string" || !flags.query.trim())) {
      process.stderr.write(
        JSON.stringify({ error: "--query requires a non-empty value", code: "BAD_ARG" }) + "\n",
      )
      return 1
    }
    if (flags.location !== undefined && (typeof flags.location !== "string" || !flags.location.trim())) {
      process.stderr.write(
        JSON.stringify({ error: "--location requires a non-empty slug", code: "BAD_ARG" }) + "\n",
      )
      return 1
    }
    if (flags.industry !== undefined && (typeof flags.industry !== "string" || !flags.industry.trim())) {
      process.stderr.write(
        JSON.stringify({ error: "--industry requires a non-empty slug", code: "BAD_ARG" }) + "\n",
      )
      return 1
    }

    const parseIntFlag = (name: string, raw: string | boolean | string[]): number | null => {
      // Number(), not parseInt(): parseInt truncates, so "--jobage 0.5" became 0
      // and silently dropped the age filter.
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      if (!Number.isInteger(val) || val < 1) {
        process.stderr.write(
          JSON.stringify({ error: `--${name} must be a whole number of at least 1, got "${raw}"`, code: "BAD_ARG" }) + "\n",
        )
        return null
      }
      return val
    }

    let jobage: number | undefined
    if (flags.jobage !== undefined) {
      const v = parseIntFlag("jobage", flags.jobage)
      if (v === null) return 1
      jobage = v
    }
    let page = 1
    if (flags.page !== undefined) {
      const v = parseIntFlag("page", flags.page)
      if (v === null) return 1
      page = v
    }
    let limit = 25
    if (flags.limit !== undefined) {
      const v = parseIntFlag("limit", flags.limit)
      if (v === null) return 1
      limit = v
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      location: typeof flags.location === "string" ? flags.location : undefined,
      industry: typeof flags.industry === "string" ? flags.industry : undefined,
      jobage,
      page,
      limit,
      format: fmt as SearchOpts["format"],
      includeDescription: flags["no-description"] !== true,
      cursor: typeof flags.cursor === "string" ? flags.cursor : undefined,
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires an <id|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "plain"].includes(fmt)) {
      process.stderr.write(
        JSON.stringify({ error: `--format must be one of json|plain, got "${fmt}"`, code: "BAD_ARG" }) + "\n",
      )
      return 1
    }
    const opts: DetailOpts = {
      id,
      format: fmt as DetailOpts["format"],
    }
    return runDetail(opts)
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

main()
  // The exit code is set rather than the process being killed, so buffered
  // stdout is flushed. process.exit() truncates a large write to a pipe at
  // the pipe buffer size - 128KB - which silently loses results.
  .then((code) => {
    process.exitCode = code
  })
  .catch((e) => {
    process.stderr.write(
      JSON.stringify({
        error: e instanceof Error ? e.message : String(e),
        code: "INTERNAL_ERROR",
      }) + "\n",
    )
    process.exitCode = 1
  })
