import { describe, expect, test } from "bun:test";
import { parseError, parseJSON, runCLI, runWithFixture } from "./helpers.js";

interface SearchResponse {
  meta: { count: number; page: number; feed_window_days: number };
  results: Array<{ id: string; title: string; company: string | null; url: string; date: string | null }>;
}

const fixture = {
  jobs: [
    {
      id: 154104,
      url: "https://jobicy.com/jobs/154104-business-consultant",
      jobTitle: "Senior AI & Data Engineer",
      companyName: "Example Corp",
      jobGeo: "Europe",
      jobLevel: "Senior",
      jobDescription: "<p>Build pipelines.</p>",
      pubDate: "2026-10-27T04:36:40+00:00",
    },
    {
      id: 154105,
      url: "https://jobicy.com/jobs/154105-backend-engineer",
      jobTitle: "Backend Engineer",
      companyName: "Another Corp",
      jobGeo: "USA",
      jobLevel: "Midweight",
      jobDescription: "<p>Build services.</p>",
      pubDate: "2026-10-26T04:36:40+00:00",
    },
  ],
  jobCount: 2,
  nextCursor: null,
  hasMore: false,
  lastUpdated: "2026-10-28T04:36:40+00:00",
  success: true,
  statusCode: 200,
};

describe("search against a saved response", () => {
  test("emits the contract's JSON shape", async () => {
    const { result } = await runWithFixture(["search", "--limit", "5"], fixture);
    const body = parseJSON<SearchResponse>(result);
    expect(body.meta.count).toBe(2);
    expect(body.meta.page).toBe(1);
    expect(body.results).toHaveLength(2);
    expect(body.results[0].id).toBe("154104");
    expect(body.results[0].title).toBe("Senior AI & Data Engineer");
    expect(body.results[0].company).toBe("Example Corp");
    expect(body.results[0].date).toBe("2026-10-27");
    expect(body.results[0].url).toContain("jobicy.com/jobs/");
  });

  test("sends the keyword as the tag filter and the location as the geo filter", async () => {
    const { result, requests } = await runWithFixture(
      ["search", "--query", "python", "--location", "europe", "--limit", "5"],
      fixture,
    );
    expect(result.exitCode).toBe(0);
    const sent = requests[0];
    expect(sent.searchParams.get("tag")).toBe("python");
    expect(sent.searchParams.get("geo")).toBe("europe");
  });

  test("sends the industry filter", async () => {
    const { requests } = await runWithFixture(
      ["search", "--industry", "data-science"],
      fixture,
    );
    expect(requests[0].searchParams.get("industry")).toBe("data-science");
  });

  test("the limit caps the rows emitted", async () => {
    const { result } = await runWithFixture(["search", "--limit", "1"], fixture);
    const body = parseJSON<SearchResponse>(result);
    expect(body.results).toHaveLength(1);
  });

  test("--no-description drops the descriptions", async () => {
    const { result } = await runWithFixture(["search", "--limit", "5", "--no-description"], fixture);
    const body = parseJSON<SearchResponse & { results: Array<{ description: string | null }> }>(result);
    expect(body.results[0].description).toBeNull();
  });

  test("a table renders a header and a row per listing", async () => {
    const { result } = await runWithFixture(["search", "--limit", "5", "--format", "table"], fixture);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("TITLE");
    expect(result.stdout).toContain("Senior AI & Data Engineer");
  });

  test("an age filter wider than the feed warns without failing", async () => {
    const { result } = await runWithFixture(["search", "--jobage", "30"], fixture);
    expect(result.exitCode).toBe(0);
    expect(parseError<{ warning: string; code: string }>(result).code).toBe("AGE_WINDOW_EXCEEDED");
  });

  test("an API rejection is reported on stderr with exit 1", async () => {
    const { result } = await runWithFixture(["search"], {
      success: false,
      error: "Invalid 'geo' value.",
    });
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("Invalid 'geo' value.");
  });
});

describe("search against the live API", () => {
  test("returns real listings with the contract's fields", async () => {
    const result = await runCLI(["search", "--query", "engineer", "--limit", "3", "--no-description"]);
    expect(result.exitCode).toBe(0);
    const body = parseJSON<SearchResponse>(result);
    expect(body.results.length).toBeGreaterThan(0);
    const first = body.results[0];
    expect(first.id).toBeTruthy();
    expect(first.title).toBeTruthy();
    expect(first.url).toContain("jobicy.com/jobs/");
  });

  test("an invalid location slug fails loudly", async () => {
    const result = await runCLI(["search", "--query", "engineer", "--location", "not-a-place"]);
    expect(result.exitCode).toBe(1);
    expect(result.stderr).toContain("geo");
  });
});
