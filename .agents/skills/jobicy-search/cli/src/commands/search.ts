import {
  apiGet,
  filterByAge,
  toResult,
  writeError,
  FEED_WINDOW_DAYS,
  type JobResponse,
  type JobResult,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  industry?: string
  jobage?: number
  page: number
  limit: number
  format: "json" | "table" | "plain"
  includeDescription: boolean
  cursor?: string
}

// The API's own maximum page size. A page is one request, and each request
// carries full listing descriptions, so a large page is expensive — but the
// feed is small and one request keeps the common path to one round trip.
const MAX_PAGE_SIZE = 200

// The most pages one search walks. A `--page` beyond this would mean a long
// chain of requests for a feed that holds at most a week of listings.
const MAX_PAGES = 20

function buildQuery(opts: SearchOpts, cursor: string | undefined, count: number): URLSearchParams {
  const p = new URLSearchParams()
  p.set("count", String(count))
  if (opts.query) p.set("tag", opts.query)
  if (opts.location) p.set("geo", opts.location)
  if (opts.industry) p.set("industry", opts.industry)
  if (cursor) p.set("cursor", cursor)
  return p
}

/** The date portion (YYYY-MM-DD) of an ISO timestamp, or "—" when absent. */
function shortDate(date: string | null): string {
  return date ? date.slice(0, 10) : "—"
}

interface Column {
  header: string
  width: number
  cell: (r: JobResult) => string
}

function renderTable(rows: JobResult[]): string {
  if (rows.length === 0) return "No results."
  const columns: Column[] = [
    { header: "ID", width: Math.max(2, ...rows.map((r) => r.id.length)), cell: (r) => r.id },
    { header: "TITLE", width: 38, cell: (r) => r.title },
    { header: "COMPANY", width: 22, cell: (r) => r.company ?? "—" },
    { header: "LOCATION", width: 22, cell: (r) => r.location ?? "—" },
    { header: "LEVEL", width: 10, cell: (r) => r.level ?? "—" },
    { header: "DATE", width: 10, cell: (r) => shortDate(r.date) },
  ]
  const row = (cells: string[]) =>
    cells.map((c, i) => c.slice(0, columns[i].width).padEnd(columns[i].width)).join("  ")

  const header = row(columns.map((c) => c.header))
  const body = rows.map((r) => row(columns.map((c) => c.cell(r))))
  return [header, "-".repeat(header.length), ...body].join("\n")
}

function renderPlain(rows: JobResult[]): string {
  if (rows.length === 0) return "No results."
  const block = (r: JobResult) =>
    [
      r.title,
      `  ${r.company ?? "—"} · ${r.location ?? "—"} · ${shortDate(r.date)}`,
      `  id: ${r.id}`,
      `  ${r.url}`,
    ].join("\n")
  return rows.map(block).join("\n\n")
}

/**
 * One line on stderr when an age filter is wider than the feed, written after
 * stdout and without touching the exit code, so a filter the API cannot honour
 * never reads as a complete answer.
 */
function warnOnWideAge(opts: SearchOpts): void {
  if (opts.jobage === undefined || opts.jobage <= FEED_WINDOW_DAYS) return
  process.stderr.write(
    JSON.stringify({
      warning: `--jobage ${opts.jobage} is wider than the Jobicy feed, which only retains listings published in the last ${FEED_WINDOW_DAYS} days; the result cannot be older than that`,
      code: "AGE_WINDOW_EXCEEDED",
    }) + "\n",
  )
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const perPage = Math.min(MAX_PAGE_SIZE, Math.max(25, opts.limit))
    const rows: JobResult[] = []
    let cursor = opts.cursor
    let skipped = 0
    let pagesFetched = 0
    let nextCursor: string | null = null
    let hasMore = false

    while (rows.length < opts.limit) {
      const path = `/api/jobs?${buildQuery(opts, cursor, perPage).toString()}`
      const resp = await apiGet<JobResponse>(path)
      if (!resp) {
        writeError(`${path} not found — this Jobicy instance does not serve the jobs API`, "SEARCH_FAILED")
        return 1
      }
      if (resp.success === false) {
        writeError(resp.error || "Jobicy API rejected the search", "SEARCH_REJECTED")
        return 1
      }

      const batch = (resp.jobs ?? []).map((j) => toResult(j, opts.includeDescription))
      // `--page` selects where in the feed to start, so the pages before it are
      // fetched and thrown away.
      if (skipped < opts.page - 1) {
        skipped++
      } else {
        for (const row of filterByAge(batch, opts.jobage ?? 0)) {
          rows.push(row)
          if (rows.length >= opts.limit) break
        }
      }

      nextCursor = resp.nextCursor ?? null
      hasMore = resp.hasMore === true
      if (!nextCursor) break
      cursor = nextCursor
      pagesFetched++
      if (pagesFetched >= MAX_PAGES) break
    }

    if (opts.format === "table") {
      process.stdout.write(renderTable(rows) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(renderPlain(rows) + "\n")
    } else {
      process.stdout.write(
        JSON.stringify(
          {
            meta: {
              count: rows.length,
              page: opts.page,
              next_cursor: nextCursor,
              has_more: hasMore,
              feed_window_days: FEED_WINDOW_DAYS,
            },
            results: rows,
          },
          null,
          2,
        ) + "\n",
      )
    }
    warnOnWideAge(opts)
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
