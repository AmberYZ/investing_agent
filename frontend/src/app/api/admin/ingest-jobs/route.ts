import { NextResponse } from "next/server";
import { execSync } from "child_process";
import path from "path";
import { readFileSync, existsSync } from "fs";

/** Disable Next.js route caching so every request gets live data. */
export const dynamic = "force-dynamic";
export const revalidate = 0;

function loadRootEnv(backendDir: string): NodeJS.ProcessEnv {
  const rootEnv = path.join(backendDir, "..", ".env");
  if (!existsSync(rootEnv)) return process.env;
  const extra: Record<string, string> = {};
  for (const line of readFileSync(rootEnv, "utf-8").split(/\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (m) extra[m[1]] = m[2].replace(/^["']|["']$/g, "").trim();
  }
  return { ...process.env, ...extra };
}

/**
 * Run the backend script that lists all ingest jobs (queued, processing, done, error)
 * so the admin page shows full list when the backend HTTP route is not available.
 */
export async function GET() {
  try {
    const frontendDir = process.cwd();
    const backendDir = path.resolve(frontendDir, "..", "backend");
    const python = path.join(backendDir, ".venv", "bin", "python");
    const script = path.join(backendDir, "scripts", "list_ingest_jobs.py");
    const env = loadRootEnv(backendDir);
    const out = execSync(`"${python}" "${script}" 200`, {
      cwd: backendDir,
      encoding: "utf-8",
      timeout: 15000,
      env,
    });
    const jobs = JSON.parse(out.trim()) as unknown[];
    return NextResponse.json(jobs, {
      headers: { "Cache-Control": "no-store, no-cache, must-revalidate" },
    });
  } catch (e) {
    const err = e as Error & { stdout?: string; stderr?: string };
    return NextResponse.json(
      { detail: err.message ?? "Failed to list jobs" },
      { status: 500 }
    );
  }
}
