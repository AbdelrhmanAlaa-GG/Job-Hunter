import { apiGet, writeError } from "../helpers.js"

export interface TaxonomyOpts {
  kind: "locations" | "industries"
  format: "json" | "table" | "plain"
}

interface LocationEntry {
  geoID: number
  geoName: string
  geoSlug: string
}

interface IndustryEntry {
  industryID: number
  industryName: string
  industrySlug: string
}

interface TaxonomyResponse {
  locations?: LocationEntry[]
  industries?: IndustryEntry[]
}

interface Row {
  name: string
  slug: string
}

function renderTable(rows: Row[]): string {
  if (rows.length === 0) return "No entries."
  const nameWidth = Math.max(4, ...rows.map((r) => r.name.length))
  const head = "NAME".padEnd(nameWidth) + "  SLUG"
  const body = rows.map((r) => r.name.padEnd(nameWidth) + "  " + r.slug)
  return [head, "-".repeat(head.length), ...body].join("\n")
}

function renderPlain(rows: Row[]): string {
  return rows.map((r) => `${r.name}\t${r.slug}`).join("\n")
}

/**
 * Print the API's own vocabulary for a filter.
 *
 * The slugs are the API's, not ours, and they change when the API's taxonomy
 * changes. Asking the API for them is the only way to stay correct; a slug
 * list copied into this repository would be right until it was not.
 */
export async function runTaxonomy(opts: TaxonomyOpts): Promise<number> {
  try {
    const resp = await apiGet<TaxonomyResponse>(`/api/jobs?get=${opts.kind}`)
    if (!resp) {
      writeError(`the Jobicy API does not expose its ${opts.kind} taxonomy`, "TAXONOMY_FAILED")
      return 1
    }

    const rows: Row[] =
      opts.kind === "locations"
        ? (resp.locations ?? []).map((l) => ({ name: l.geoName, slug: l.geoSlug }))
        : (resp.industries ?? []).map((i) => ({ name: i.industryName, slug: i.industrySlug }))

    if (opts.format === "table") {
      process.stdout.write(renderTable(rows) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(renderPlain(rows) + "\n")
    } else {
      process.stdout.write(JSON.stringify({ [opts.kind]: rows }, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "TAXONOMY_FAILED")
    return 1
  }
}
