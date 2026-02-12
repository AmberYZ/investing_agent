import { NextResponse } from "next/server";
import { execSync } from "child_process";
import path from "path";
import { readFileSync, existsSync } from "fs";

/**
 * Run the backend's requeue script so the button works even when the backend
 * HTTP route isn't loaded (e.g. old process). Uses same DB as backend via script.
 */
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

export async function POST() {
  try {
    const frontendDir = process.cwd();
    const backendDir = path.resolve(frontendDir, "..", "backend");
    const python = path.join(backendDir, ".venv", "bin", "python");
    const script = path.join(backendDir, "scripts", "requeue_error_ingest_jobs.py");
    const env = loadRootEnv(backendDir);
    const out = execSync(`"${python}" "${script}"`, {
      cwd: backendDir,
      encoding: "utf-8",
      timeout: 15000,
      env,
    });
    const match = out.match(/Requeued (\d+) error ingest job/);
    const requeued = match ? parseInt(match[1], 10) : 0;
    return NextResponse.json({ requeued });
  } catch (e) {
    const err = e as Error & { status?: number; stdout?: string; stderr?: string };
    const msg = err.message ?? "Requeue failed";
    return NextResponse.json(
      { detail: msg, requeued: 0 },
      { status: 500 }
    );
  }
}
