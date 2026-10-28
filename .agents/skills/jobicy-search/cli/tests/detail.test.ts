import { describe, expect, test } from "bun:test";
import { parseError, parseJSON, runCLI, runWithFixture } from "./helpers.js";

interface DetailResponse {
  id: string;
  title: string;
  company: string | null;
  location: string | null;
  date: string | null;
  url: string;
  description: string | null;
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
      jobDescription: "<p>Build <strong>pipelines</strong>.</p><ul><li>Python</li></ul>",
      pubDate: "2026-10-27T04:36:40+00:00",
    },
  ],
  jobCount: 1,
  nextCursor: null,
  hasMore: false,
  success: true,
};

describe("detail", () => {
  test("finds a listing by id", async () => {
    const { result } = await runWithFixture(["detail", "154104"], fixture);
    const job = parseJSON<DetailResponse>(result);
    expect(job.id).toBe("154104");
    expect(job.title).toBe("Senior AI & Data Engineer");
    expect(job.description).toContain("Build pipelines.");
    expect(job.description).not.toContain("<");
  });

  test("finds a listing by its URL", async () => {
    const { result } = await runWithFixture(
      ["detail", "https://jobicy.com/jobs/154104-business-consultant"],
      fixture,
    );
    expect(parseJSON<DetailResponse>(result).id).toBe("154104");
  });

  test("a plain rendering carries the description and the source link", async () => {
    const { result } = await runWithFixture(["detail", "154104", "--format", "plain"], fixture);
    expect(result.exitCode).toBe(0);
    expect(result.stdout).toContain("Senior AI & Data Engineer");
    expect(result.stdout).toContain("Build pipelines.");
    expect(result.stdout).toContain("https://jobicy.com/jobs/154104");
  });

  test("a listing that is not in the feed reports that it may have aged out", async () => {
    const { result } = await runWithFixture(["detail", "999999"], fixture);
    expect(result.exitCode).toBe(1);
    const error = parseError<{ error: string; code: string }>(result);
    expect(error.code).toBe("NOT_FOUND");
    expect(error.error).toContain("7 days");
  });

  test("an id that is not a Jobicy listing is rejected before any request", async () => {
    const result = await runCLI(["detail", "https://evil.example/jobs/154104-x"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ID");
  });
});
