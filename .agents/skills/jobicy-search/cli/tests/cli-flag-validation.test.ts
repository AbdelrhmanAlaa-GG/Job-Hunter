import { describe, expect, test } from "bun:test";
import { parseError, runCLI } from "./helpers.js";

describe("flag validation", () => {
  test("an unknown flag is rejected rather than silently ignored", async () => {
    const result = await runCLI(["search", "--bogus", "value"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("UNKNOWN_FLAG");
  });

  test("an unknown flag on detail is rejected", async () => {
    const result = await runCLI(["detail", "123", "--bogus", "value"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("UNKNOWN_FLAG");
  });

  test("an unknown format is rejected", async () => {
    const result = await runCLI(["search", "--format", "xml"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("an empty query is rejected", async () => {
    const result = await runCLI(["search", "--query", ""]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("a bare query flag with no value is rejected", async () => {
    const result = await runCLI(["search", "--query"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("an empty location is rejected", async () => {
    const result = await runCLI(["search", "--location", ""]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("a non-numeric limit is rejected", async () => {
    const result = await runCLI(["search", "--limit", "many"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("a fractional jobage is rejected rather than truncated", async () => {
    const result = await runCLI(["search", "--jobage", "0.5"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("a zero limit is rejected", async () => {
    const result = await runCLI(["search", "--limit", "0"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_ARG");
  });

  test("detail without an id is rejected", async () => {
    const result = await runCLI(["detail"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("NO_ID");
  });

  test("an unknown command is rejected", async () => {
    const result = await runCLI(["browse"]);
    expect(result.exitCode).toBe(1);
    expect(parseError(result).code).toBe("BAD_CMD");
  });

  test("errors are written to stderr, never to stdout", async () => {
    const result = await runCLI(["search", "--bogus", "value"]);
    expect(result.stdout).toBe("");
    expect(result.stderr).toContain("UNKNOWN_FLAG");
  });
});
