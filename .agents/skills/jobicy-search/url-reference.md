# Jobicy Jobs API — URL reference

The endpoint, its parameters and the response shape. This is the file to read
when the API changes and the parsing needs updating.

Base URL: `https://jobicy.com` — override with `JOBICY_API_URL` for a proxy or
a self-hosted instance.

## Endpoints

### `GET /api/jobs`

The public Jobs API. **No API key.** No authentication header. Reads are
unauthenticated and free for commercial use, subject to the attribution
requirement in `SKILL.md`.

| Parameter | Type | Notes |
|---|---|---|
| `count` | integer | Page size, 1–200. Default 200. |
| `cursor` | string | Opaque continuation token from the previous response's `nextCursor`. Valid 24 hours. |
| `geo` | string | Location eligibility slug. Must be a `geoSlug` from the locations taxonomy; the API answers 400 otherwise. |
| `industry` | string | Category slug. Must be an `industrySlug` from the industries taxonomy. |
| `tag` | string | Keyword search over the listing's title, description and excerpt. |
| `get` | string | `locations` or `industries` — returns the taxonomy instead of listings. |

Query parameters combine: `geo`, `industry` and `tag` narrow together, and the
API echoes what it applied in `appliedFilters`.

### `GET /api/jobs?get=locations`

The location taxonomy. Each entry is `{ geoID, geoName, geoSlug }`.

As of October 2026 there are 55 slugs. The macro buckets are `anywhere`, `apac`,
`emea`, `latam`, `europe` and `uk`; the rest are countries.

**The Arab-region coverage is `united-arab-emirates`, `israel` and `turkiye`
only.** There is no Egypt, Saudi Arabia, Qatar, Kuwait, Oman, Bahrain, Morocco,
Tunisia, Algeria, Jordan, Iraq or Lebanon slug. `emea` covers Europe, the Middle
East and Africa together, so it is broader than a Gulf-only search but narrower
than "Europe plus the Gulf" on other boards.

### `GET /api/jobs?get=industries`

The category taxonomy. Each entry is `{ industryID, industryName, industrySlug }`.

As of October 2026 there are 22 slugs, including `software-engineering`,
`data-science`, `devops`, `design`, `marketing`, `customer-success`,
`cybersecurity` and `qa-testing`.

### `GET /api/jobs/status?ids=<id,id,...>`

Batch availability check. Up to 100 ids. Each comes back `active`, `closed` or
`unknown`. `unknown` means the id is not visible to the public API — it is not
proof that the job closed.

### `GET /api/jobs/{id}`

**Not a JSON endpoint.** It answers with the site's HTML. The JSON listing is
reached only through `GET /api/jobs`, so the CLI's `detail` command finds the
id by walking the feed.

## Response shape

```json
{
  "apiVersion": "2.2.19",
  "documentationUrl": "https://jobi.cy/apidocs",
  "friendlyNotice": "Thanks for using Jobicy API! Please credit Jobicy and link to the source.",
  "jobCount": 2,
  "lastUpdated": "2026-10-28T04:36:40+00:00",
  "nextCursor": null,
  "hasMore": false,
  "appliedFilters": { "count": 200, "geo": "europe" },
  "jobs": [
    {
      "id": 154104,
      "url": "https://jobicy.com/jobs/154104-business-consultant-6-months-contract",
      "jobTitle": "Senior AI & Data Engineer",
      "companyName": "Example Corp",
      "jobIndustry": ["Software Engineering"],
      "jobType": ["Full-Time"],
      "jobGeo": "Europe",
      "jobLevel": "Senior",
      "jobExcerpt": "Build and ship models.",
      "jobDescription": "<p>Full description, as HTML.</p>",
      "pubDate": "2026-10-27T04:36:40+00:00",
      "salaryMin": 90000,
      "salaryMax": 120000,
      "salaryCurrency": "USD",
      "salaryPeriod": "yearly"
    }
  ],
  "statusCode": 200,
  "success": true
}
```

### Listing fields

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Unique listing id. What `detail` consumes. |
| `url` | string | The Jobicy listing URL. With the public API this is always Jobicy's own page. |
| `jobTitle` | string | May carry HTML entities. |
| `companyName` | string | |
| `jobIndustry` | string[] | Category labels, e.g. `Data Science & Analytics`. |
| `jobType` | string[] | e.g. `Full-Time`, `Contract`. |
| `jobGeo` | string | The eligibility — `USA`, `Europe`, `Europe,  Israel`, `EMEA`, `Anywhere`. Note the double space in compound values; it is how the source stores them. |
| `jobLevel` | string | `Any`, `Midweight`, `Senior`, … |
| `jobExcerpt` | string | Short summary. |
| `jobDescription` | string | **HTML.** Stripped to text by the CLI. |
| `pubDate` | string | ISO timestamp. The CLI emits its date part. |
| `salaryMin`, `salaryMax` | number | Optional. |
| `salaryCurrency`, `salaryPeriod` | string | Optional. |

## Quirks worth knowing

- **The feed is a rolling seven days.** Listings leave it as they age. The lower
  boundary is re-checked on every request, so a long traversal sees rows drop
  out of the window mid-run. The upper boundary is fixed at the first request.
- **Pagination is by cursor, not offset.** Changing `geo`, `industry` or `tag`
  while carrying a cursor returns 400 — a cursor belongs to the filter that
  produced it.
- **An unknown query parameter is a 400** with `Unexpected parameter 'name'`, not
  a silently ignored one.
- **An unknown slug value is a 400** with `Invalid 'geo' value. This value must
  contain a predefined 'geoSlug'` and a link to the taxonomy. Unlike some other
  boards, a wrong geography here fails loudly instead of returning another
  market's postings.
- **`jobGeo` is eligibility, not workplace.** A listing tagged `USA` is open to
  applicants in the USA; it says nothing about where the employer sits.

## Rate limits and fair use

Jobicy asks for a few synchronisation passes a day and no more than once an hour
per integration, and asks integrations to cache responses. This CLI is a
personal search tool: it makes a handful of requests per run.
