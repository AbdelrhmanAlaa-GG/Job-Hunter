// Data source: the Jobicy public Jobs API (https://jobicy.com/api/jobs). Reads are
// unauthenticated — the public endpoint needs no API key, and Jobicy's terms allow
// use in your own products provided listings are credited and linked back. The
// response is JSON, so there is no markup to parse: we fetch JSON and reshape it
// into the portal-skill contract's result fields. The base URL is swappable via
// JOBICY_API_URL for a self-hosted or proxied instance.

export const DEFAULT_BASE_URL = "https://jobicy.com"

/** API base URL: JOBICY_API_URL (for a proxy or a self-hosted instance) or the default. */
export function baseUrl(): string {
  const raw = (process.env.JOBICY_API_URL ?? "").trim()
  return (raw || DEFAULT_BASE_URL).replace(/\/+$/, "")
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

// Names this project in the owner/project/version shape the other portal CLIs
// follow, so the API's operators can find the maintainer before a field or a
// limit changes.
const UA = "ai-job-search-dev/ai-job-search/1.0 (jobicy-search)"

/** The public Jobs API response. */
export interface JobResponse {
  jobs: JobicyJob[]
  jobCount: number
  nextCursor: string | null
  hasMore: boolean
  lastUpdated: string
  appliedFilters?: Record<string, unknown>
  success?: boolean
  statusCode?: number
  error?: string
}

/** A Jobicy listing — the fields this skill reads. */
export interface JobicyJob {
  id: number
  url: string
  jobTitle: string
  companyName: string
  jobIndustry?: string[]
  jobType?: string[]
  jobGeo?: string
  jobLevel?: string
  jobExcerpt?: string
  jobDescription?: string
  pubDate?: string
  salaryMin?: number
  salaryMax?: number
  salaryCurrency?: string
  salaryPeriod?: string
}

/** A search result in the portal-skill contract shape. */
export interface JobResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  geo: string | null
  level: string | null
  industries: string[]
  employment_types: string[]
  salary: string | null
  description: string | null
}

/** A job detail: the search result plus the full cleaned description. */
export interface JobDetailResult extends JobResult {
  excerpt: string | null
}

// The most apiGet sleeps across all retries of one request. Its own backoff
// schedule (500ms doubling to 8s, six retries) stays under it; a Retry-After
// that would push past it fails the request at once instead, so an outage still
// degrades this source quickly rather than outlasting the caller's tool timeout.
const RETRY_BUDGET_MS = 30_000

/**
 * The wait a 429/503 asks for via `Retry-After`, in ms, or null when absent or
 * unreadable. Accepts both RFC 9110 forms: delta-seconds and an HTTP-date.
 */
export function retryAfterMs(header: string | null, now = Date.now()): number | null {
  if (!header) return null
  const value = header.trim()
  if (/^\d+$/.test(value)) return Number(value) * 1000
  const date = Date.parse(value)
  if (Number.isNaN(date)) return null
  return Math.max(date - now, 0)
}

/**
 * GET a JSON document from the Jobicy API. Retries 429/5xx with backoff, waiting
 * at least as long as a `Retry-After` header asks within a total budget of
 * RETRY_BUDGET_MS. A 4xx is not retried: the API validates `geo`, `industry` and
 * `tag` values itself and answers 400 with a message naming the valid values, so
 * a bad value must surface rather than be retried into a success.
 */
export async function apiGet<T>(path: string): Promise<T | null> {
  const url = `${baseUrl()}${path}`
  const maxRetries = 6
  let delay = 500
  let waited = 0

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    let response: Response
    try {
      response = await fetch(url, {
        headers: { "User-Agent": UA, Accept: "application/json" },
        redirect: "follow",
        signal: AbortSignal.timeout(15000),
      })
    } catch (e) {
      throw new Error(
        `could not reach the Jobicy API at ${baseUrl()} (${e instanceof Error ? e.message : String(e)})`,
      )
    }

    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Jobicy API request failed: ${response.status} ${response.statusText}`)
      }
      const backoff = delay + Math.floor(Math.random() * 500)
      const retryAfter = retryAfterMs(response.headers.get("Retry-After"))
      const wait = Math.max(backoff, retryAfter ?? 0)
      if (waited + wait > RETRY_BUDGET_MS) {
        throw new Error(
          `Jobicy API request failed: ${response.status} ${response.statusText}; ` +
            `the server asked to retry in ${Math.ceil(wait / 1000)}s, past this CLI's ${RETRY_BUDGET_MS / 1000}s retry budget`,
        )
      }
      await sleep(wait)
      waited += wait
      delay = Math.min(delay * 2, 8000)
      continue
    }

    const body = (await response.json().catch(() => null)) as T | null
    if (!response.ok) {
      const message =
        body && typeof body === "object" && "error" in body
          ? String((body as { error?: unknown }).error)
          : ""
      throw new Error(message || `Jobicy API request failed: ${response.status} ${response.statusText}`)
    }
    if (!body) throw new Error("Jobicy API returned an unparseable response body")
    return body
  }
  throw new Error("Jobicy API request failed after retries")
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/**
 * The portal-contract date (`YYYY-MM-DD`) from a listing's ISO timestamp. Every
 * other portal CLI emits the date part only, and the run stores it as
 * `posted_date: "YYYY-MM-DD"`. Null when absent or not a date.
 */
export function contractDate(value: string | null | undefined): string | null {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(value ?? "")
  return m ? m[1] : null
}

/** The date portion of an ISO timestamp, for the client-side age filter. */
export function isoDate(value: string | null | undefined): string | null {
  return contractDate(value)
}

/**
 * Human-readable salary line, or null when the listing records neither bound.
 * The period is kept when Jobicy records one, so a yearly figure is not
 * mistaken for an hourly one.
 */
export function formatSalary(j: JobicyJob): string | null {
  if (j.salaryMin == null && j.salaryMax == null) return null
  const cur = j.salaryCurrency ? `${j.salaryCurrency} ` : ""
  const per = j.salaryPeriod ? `/${j.salaryPeriod}` : ""
  if (j.salaryMin != null && j.salaryMax != null) return `${cur}${j.salaryMin}–${j.salaryMax}${per}`
  return `${cur}${j.salaryMin ?? j.salaryMax}${per}`
}

/** Reshape a Jobicy listing into the contract search-result fields. */
export function toResult(j: JobicyJob, includeDescription = true): JobResult {
  return {
    id: String(j.id),
    title: decodeHtmlEntities(j.jobTitle || "").trim() || "(untitled)",
    company: j.companyName || null,
    location: j.jobGeo || null,
    date: contractDate(j.pubDate),
    url: j.url,
    geo: j.jobGeo || null,
    level: j.jobLevel || null,
    industries: j.jobIndustry ?? [],
    employment_types: j.jobType ?? [],
    salary: formatSalary(j),
    description: includeDescription ? cleanHtml(j.jobDescription) : null,
  }
}

/** Reshape a Jobicy listing into the detail result. */
export function toDetail(j: JobicyJob): JobDetailResult {
  return {
    ...toResult(j, true),
    excerpt: j.jobExcerpt ? decodeHtmlEntities(j.jobExcerpt).trim() || null : null,
  }
}

function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  hellip: "…",
  mdash: "—",
  ndash: "–",
  rsquo: "’",
  lsquo: "‘",
  ldquo: "“",
  rdquo: "”",
}

/**
 * Decode HTML entities — named and numeric. An unknown entity is left as it
 * was found, because a posting's text is read by a human and a half-decoded
 * entity is worse than a visible one.
 */
export function decodeHtmlEntities(text: string): string {
  return text.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z][a-zA-Z0-9]*);/g, (match, body: string) => {
    if (body.startsWith("#x")) return numericEntity(parseInt(body.slice(2), 16))
    if (body.startsWith("#")) return numericEntity(parseInt(body.slice(1), 10))
    const named = NAMED_ENTITIES[body.toLowerCase()]
    return named ?? match
  })
}

/**
 * Strip a listing's HTML into readable prose: block tags become newlines,
 * inline tags are removed, entities are decoded. Null for empty input.
 *
 * Inline tags are removed rather than replaced with a space: replacing them
 * left "build <strong>pipelines</strong>." as "build pipelines .", with a
 * space before the full stop.
 */
export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(
      /<\/(p|li|ul|ol|div|h\d|tr|td|th|table|section|article|header|footer|main|aside|nav|blockquote|pre|figure|figcaption|hr)>/gi,
      "\n",
    )
  const text = decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, ""))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return text || null
}

const JOBICY_HOST = /(^|\.)jobicy\.com$/i

/** True for jobicy.com, any of its subdomains, or the configured base URL's host. */
function isJobicyHost(host: string): boolean {
  if (JOBICY_HOST.test(host)) return true
  try {
    const self = new URL(baseUrl()).hostname.toLowerCase()
    return host === self || host.endsWith(`.${self}`)
  } catch {
    return false
  }
}

/**
 * Extract a Jobicy listing id from a bare id or a `jobicy.com/jobs/<id>-<slug>`
 * URL. A URL on any other host is rejected: the previous pattern took the
 * leading number from ANY string, so an unrelated URL was reduced to a number
 * that never existed as a listing. URLs are parsed for real, so look-alike hosts
 * (jobicy.com.evil.io) and userinfo tricks (jobicy.com@evil.io) fall on the
 * reject side.
 */
export function normalizeId(input: string): string | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  const hasScheme = /^https?:\/\//i.test(trimmed)
  if (hasScheme || /^[a-z0-9.-]+\.[a-z]{2,}(\/|$)/i.test(trimmed)) {
    let parsed: URL
    try {
      parsed = new URL(hasScheme ? trimmed : `https://${trimmed}`)
    } catch {
      return null
    }
    if (!isJobicyHost(parsed.hostname.toLowerCase())) return null
    const m = parsed.pathname.match(/^\/jobs\/(\d+)(?:-[^/]*)?\/?$/i)
    return m ? m[1] : null
  }
  if (/^\d+$/.test(trimmed)) return trimmed
  return null
}

/**
 * The Jobicy feed only retains listings published in the last seven days, so an
 * age filter wider than that cannot be satisfied. The CLI filters client-side
 * and says so, rather than quietly returning a week-old feed as if it were a
 * month-old one.
 */
export const FEED_WINDOW_DAYS = 7

/**
 * Keep listings published within `days` of `now`. The feed is already seven
 * days wide, so this only ever narrows it.
 */
export function filterByAge(rows: JobResult[], days: number, now = new Date()): JobResult[] {
  if (!Number.isFinite(days) || days <= 0) return rows
  const cutoff = new Date(now.getTime() - days * 24 * 60 * 60 * 1000)
  const cutoffDate = cutoff.toISOString().slice(0, 10)
  return rows.filter((r) => (r.date ?? "") >= cutoffDate)
}
