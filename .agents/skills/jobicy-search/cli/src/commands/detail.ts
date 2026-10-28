import { apiGet, normalizeId, toDetail, writeError, type JobResponse } from "../helpers.js"

export interface DetailOpts {
  id: string // a Jobicy listing id or a /jobs/<id>-<slug> URL
  format: "json" | "plain"
}

// The API exposes no per-listing endpoint, so `detail` finds the listing in the
// feed. The feed is one request per page and holds a week of listings, so the
// walk is bounded rather than endless.
const MAX_PAGES = 20
const PAGE_SIZE = 200

/** A human-readable rendering of one listing. */
function renderPlain(job: ReturnType<typeof toDetail>): string {
  const lines = [job.title, `${job.company ?? "—"} · ${job.location ?? "—"}`]

  const field = (label: string, value: string | null) => {
    if (value) lines.push(`${label}: ${value}`)
  }
  field("Posted", job.date)
  field("Level", job.level)
  field("Industries", job.industries.length ? job.industries.join(", ") : null)
  field("Employment", job.employment_types.length ? job.employment_types.join(", ") : null)
  field("Salary", job.salary)

  lines.push("", job.description ?? "(no description)", "", `URL: ${job.url}`, `id: ${job.id}`)
  return lines.join("\n")
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`could not parse a Jobicy listing id from "${opts.id}"`, "BAD_ID")
    return 1
  }

  try {
    let cursor: string | undefined
    for (let page = 0; page < MAX_PAGES; page++) {
      const p = new URLSearchParams()
      p.set("count", String(PAGE_SIZE))
      if (cursor) p.set("cursor", cursor)

      const resp = await apiGet<JobResponse>(`/api/jobs?${p.toString()}`)
      if (!resp) {
        writeError("the Jobicy jobs API is not available", "DETAIL_FAILED")
        return 1
      }
      if (resp.success === false) {
        writeError(resp.error || "Jobicy API rejected the request", "DETAIL_REJECTED")
        return 1
      }

      const found = (resp.jobs ?? []).find((j) => String(j.id) === id)
      if (found) {
        const job = toDetail(found)
        if (opts.format === "plain") {
          process.stdout.write(renderPlain(job) + "\n")
        } else {
          process.stdout.write(JSON.stringify(job, null, 2) + "\n")
        }
        return 0
      }

      if (!resp.nextCursor) break
      cursor = resp.nextCursor
    }

    writeError(
      `listing ${id} was not found in the Jobicy feed; the feed only retains listings published in the last 7 days, so this one may have aged out of it`,
      "NOT_FOUND",
    )
    return 1
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
