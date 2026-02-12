import { NextResponse } from "next/server";
import path from "path";
import { existsSync, readFileSync, mkdirSync, writeFileSync } from "fs";

const BACKEND_BASE =
  process.env.API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000";

function watchDirsFilePath(): string {
  const frontendDir = process.cwd();
  return path.resolve(frontendDir, "..", "backend", "app", "prompts", "watch_dirs.json");
}

/** Fallback when backend returns 404: read watch_dirs from file (no last_file_at). */
function readFromFile(): { watch_dirs: { path: string; nickname: string }[]; config_updated_at: string | null } {
  const filePath = watchDirsFilePath();
  if (!existsSync(filePath)) {
    return { watch_dirs: [], config_updated_at: null };
  }
  try {
    const data = JSON.parse(readFileSync(filePath, "utf-8"));
    const dirs = Array.isArray(data.watch_dirs) ? data.watch_dirs : [];
    const watch_dirs = dirs.map((e: { path?: string; nickname?: string }) => ({
      path: String(e?.path ?? "").trim(),
      nickname: String(e?.nickname ?? "").trim(),
    }));
    return {
      watch_dirs: watch_dirs.filter((e) => e.path),
      config_updated_at: data.config_updated_at ?? null,
    };
  } catch {
    return { watch_dirs: [], config_updated_at: null };
  }
}

/** Fallback when backend returns 404: write watch_dirs to file. */
function writeToFile(body: { watch_dirs: { path: string; nickname: string }[] }): void {
  const filePath = watchDirsFilePath();
  const dir = path.dirname(filePath);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
  const normalized = (body.watch_dirs || [])
    .map((e) => ({ path: String(e.path).trim(), nickname: String(e.nickname ?? "").trim() }))
    .filter((e) => e.path);
  const config_updated_at = new Date().toISOString();
  writeFileSync(
    filePath,
    JSON.stringify({ watch_dirs: normalized, config_updated_at }, null, 2),
    "utf-8"
  );
}

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_BASE.replace(/\/$/, "")}/settings/watch-dirs`, {
      cache: "no-store",
    });
    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }
    if (res.status === 404) {
      const fallback = readFromFile();
      return NextResponse.json(fallback);
    }
    return NextResponse.json(
      { detail: `Backend returned ${res.status}` },
      { status: res.status }
    );
  } catch {
    const fallback = readFromFile();
    return NextResponse.json(fallback);
  }
}

export async function PUT(request: Request) {
  let body: { watch_dirs: { path: string; nickname: string }[] };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON" }, { status: 400 });
  }
  try {
    const res = await fetch(`${BACKEND_BASE.replace(/\/$/, "")}/settings/watch-dirs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const data = await res.json();
      return NextResponse.json(data);
    }
    if (res.status === 404) {
      writeToFile(body);
      const fallback = readFromFile();
      return NextResponse.json(fallback);
    }
    const err = await res.json().catch(() => ({}));
    return NextResponse.json(
      err as { detail?: string },
      { status: res.status }
    );
  } catch {
    writeToFile(body);
    const fallback = readFromFile();
    return NextResponse.json(fallback);
  }
}
