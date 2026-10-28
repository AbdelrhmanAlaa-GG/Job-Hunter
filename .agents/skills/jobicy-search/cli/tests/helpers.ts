import { join } from "path";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

const CLI_PATH = join(import.meta.dir, "../src/cli.ts");

export interface CLIResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

export async function runCLI(args: string[], preload?: string): Promise<CLIResult> {
  const proc = Bun.spawn(["bun", "run", ...(preload ? ["--preload", preload] : []), CLI_PATH, ...args], {
    stdout: "pipe",
    stderr: "pipe",
  });

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);

  return { stdout: stdout.trim(), stderr: stderr.trim(), exitCode };
}

/**
 * Run the CLI against a saved response, with every outbound request redirected
 * to a local server. The server records the URL it was asked for, so a test can
 * assert on the query the CLI actually sent.
 */
export async function runWithFixture(
  args: string[],
  body: unknown,
): Promise<{ result: CLIResult; requests: URL[] }> {
  const requests: URL[] = [];
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      requests.push(new URL(request.url));
      return new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      });
    },
  });
  const dir = mkdtempSync(join(tmpdir(), "jobicy-fixture-"));
  const preload = join(dir, "fetch.ts");
  writeFileSync(
    preload,
    `
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      if (url.pathname !== "/api/jobs") {
        throw new Error("Unexpected fixture request: " + url.pathname);
      }
      return originalFetch(${JSON.stringify(server.url.origin)} + url.pathname + url.search, init);
    };
  `,
  );
  try {
    return { result: await runCLI(args, preload), requests };
  } finally {
    server.stop(true);
    rmSync(dir, { recursive: true, force: true });
  }
}

export function parseJSON<T = unknown>(result: CLIResult): T {
  if (result.exitCode !== 0) {
    throw new Error(`CLI exited with code ${result.exitCode}. stderr: ${result.stderr}`);
  }
  try {
    return JSON.parse(result.stdout) as T;
  } catch {
    throw new Error(`Failed to parse JSON. stdout: ${result.stdout}\nstderr: ${result.stderr}`);
  }
}

/** The error object a failing CLI writes to stderr. */
export function parseError<T = { error: string; code: string }>(result: CLIResult): T {
  try {
    return JSON.parse(result.stderr) as T;
  } catch {
    throw new Error(`Failed to parse stderr as JSON. stderr: ${result.stderr}`);
  }
}
