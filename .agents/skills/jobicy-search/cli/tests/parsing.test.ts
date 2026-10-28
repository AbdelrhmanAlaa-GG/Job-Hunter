import { describe, expect, test } from "bun:test";
import {
  cleanHtml,
  contractDate,
  decodeHtmlEntities,
  filterByAge,
  formatSalary,
  normalizeId,
  toResult,
  type JobicyJob,
} from "../src/helpers.js";

const listing: JobicyJob = {
  id: 154104,
  url: "https://jobicy.com/jobs/154104-business-consultant",
  jobTitle: "Senior AI & Data Engineer",
  companyName: "Example Corp",
  jobIndustry: ["Software Engineering"],
  jobType: ["Full-Time"],
  jobGeo: "Europe",
  jobLevel: "Senior",
  jobExcerpt: "Build & ship models",
  jobDescription: "<p>You will build <strong>pipelines</strong>.</p><ul><li>Python</li><li>SQL</li></ul>",
  pubDate: "2026-10-27T04:36:40+00:00",
  salaryMin: 90000,
  salaryMax: 120000,
  salaryCurrency: "USD",
  salaryPeriod: "yearly",
};

describe("toResult", () => {
  test("maps a listing onto the contract fields", () => {
    const result = toResult(listing);
    expect(result.id).toBe("154104");
    expect(result.title).toBe("Senior AI & Data Engineer");
    expect(result.company).toBe("Example Corp");
    expect(result.location).toBe("Europe");
    expect(result.date).toBe("2026-10-27");
    expect(result.url).toBe(listing.url);
  });

  test("keeps the extra fields the API carries", () => {
    const result = toResult(listing);
    expect(result.level).toBe("Senior");
    expect(result.industries).toEqual(["Software Engineering"]);
    expect(result.employment_types).toEqual(["Full-Time"]);
    expect(result.salary).toBe("USD 90000–120000/yearly");
  });

  test("missing values are null, never omitted", () => {
    const result = toResult({ id: 1, url: "https://jobicy.com/jobs/1-x", jobTitle: "A", companyName: "" });
    expect(result.company).toBeNull();
    expect(result.location).toBeNull();
    expect(result.date).toBeNull();
    expect(result.level).toBeNull();
    expect(result.salary).toBeNull();
    expect(result.description).toBeNull();
  });

  test("the description can be dropped for a cheap discovery pass", () => {
    const result = toResult(listing, false);
    expect(result.description).toBeNull();
    expect(result.title).toBe("Senior AI & Data Engineer");
  });
});

describe("cleanHtml", () => {
  test("turns block tags into line breaks and strips the rest", () => {
    const text = cleanHtml(listing.jobDescription);
    expect(text).toContain("You will build pipelines.");
    expect(text).toContain("Python");
    expect(text).not.toContain("<");
  });

  test("decodes entities", () => {
    expect(cleanHtml("<p>AI & ML <3 &nbsp;done</p>")).toBe("AI & ML <3 done");
  });

  test("returns null for empty input", () => {
    expect(cleanHtml("")).toBeNull();
    expect(cleanHtml(undefined)).toBeNull();
  });
});

describe("decodeHtmlEntities", () => {
  test("decodes named entities", () => {
    const QUOT = "&" + "quot;";
    expect(decodeHtmlEntities(QUOT + "quoted" + QUOT)).toBe('"quoted"');
  });

  test("leaves a bare ampersand and angle brackets alone", () => {
    expect(decodeHtmlEntities("a & b < c > d")).toBe("a & b < c > d");
  });

  test("decodes decimal and hex entities", () => {
    expect(decodeHtmlEntities("&#65;&#x42;")).toBe("AB");
  });

  test("leaves an unknown entity as it was found", () => {
    expect(decodeHtmlEntities("&notarealentity;")).toBe("&notarealentity;");
  });
});

describe("contractDate", () => {
  test("cuts an ISO timestamp to its date part", () => {
    expect(contractDate("2026-10-27T04:36:40+00:00")).toBe("2026-10-27");
  });

  test("returns null for an absent or malformed date", () => {
    expect(contractDate(null)).toBeNull();
    expect(contractDate("not a date")).toBeNull();
  });
});

describe("formatSalary", () => {
  test("keeps the currency and the period", () => {
    expect(formatSalary({ id: 1, url: "", jobTitle: "", companyName: "", salaryMin: 10, salaryMax: 20, salaryCurrency: "EUR", salaryPeriod: "monthly" })).toBe(
      "EUR 10–20/monthly",
    );
  });

  test("returns null when neither bound is present", () => {
    expect(formatSalary({ id: 1, url: "", jobTitle: "", companyName: "" })).toBeNull();
  });
});

describe("normalizeId", () => {
  test("accepts a bare id", () => {
    expect(normalizeId("154104")).toBe("154104");
  });

  test("accepts a Jobicy listing URL", () => {
    expect(normalizeId("https://jobicy.com/jobs/154104-business-consultant")).toBe("154104");
  });

  test("rejects a URL on another host", () => {
    expect(normalizeId("https://evil.example/jobs/154104-x")).toBeNull();
  });

  test("rejects a look-alike host", () => {
    expect(normalizeId("https://jobicy.com.evil.io/jobs/154104-x")).toBeNull();
  });

  test("rejects a userinfo trick", () => {
    expect(normalizeId("https://jobicy.com@evil.io/jobs/154104-x")).toBeNull();
  });

  test("rejects a non-numeric id", () => {
    expect(normalizeId("not-an-id")).toBeNull();
    expect(normalizeId("")).toBeNull();
  });
});

describe("filterByAge", () => {
  const now = new Date("2026-10-28T00:00:00Z");

  test("keeps only listings inside the window", () => {
    const rows = [
      { id: "1", date: "2026-10-27" },
      { id: "2", date: "2026-10-20" },
      { id: "3", date: "2026-10-01" },
    ] as never[];
    expect(filterByAge(rows, 3, now).map((r) => r.id)).toEqual(["1"]);
  });

  test("a listing with no date is dropped by an age filter", () => {
    const rows = [{ id: "1", date: null }] as never[];
    expect(filterByAge(rows, 7, now)).toEqual([]);
  });

  test("no filter keeps everything", () => {
    const rows = [{ id: "1", date: null }] as never[];
    expect(filterByAge(rows, 0, now)).toHaveLength(1);
  });
});
