import { NextResponse } from "next/server";
import path from "path";
import { existsSync, readFileSync, mkdirSync, writeFileSync } from "fs";

const ALL_DISMISSED_KEY = "all_dismissed_at";
const MAX_THEME_ENTRIES = 500;

function filePath(): string {
  const cwd = process.cwd();
  const fromFrontend = path.resolve(cwd, "..", "backend", "app", "prompts", "theme_read_state.json");
  const fromRoot = path.resolve(cwd, "backend", "app", "prompts", "theme_read_state.json");
  if (existsSync(path.dirname(fromRoot))) return fromRoot;
  return fromFrontend;
}

function load(): { all_dismissed_at: string | null; themes: Record<string, string> } {
  const fp = filePath();
  if (!existsSync(fp)) {
    return { all_dismissed_at: null, themes: {} };
  }
  try {
    const data = JSON.parse(readFileSync(fp, "utf-8")) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return { all_dismissed_at: null, themes: {} };
    }
    const obj = data as Record<string, unknown>;
    const all_dismissed_at =
      typeof obj[ALL_DISMISSED_KEY] === "string" ? (obj[ALL_DISMISSED_KEY] as string) : null;
    const themes: Record<string, string> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (k === ALL_DISMISSED_KEY) continue;
      if (typeof v === "string" && /^\d+$/.test(String(k))) themes[k] = v;
    }
    return { all_dismissed_at, themes };
  } catch {
    return { all_dismissed_at: null, themes: {} };
  }
}

function save(all_dismissed_at: string | null, themes: Record<string, string>): void {
  const fp = filePath();
  const dir = path.dirname(fp);
  mkdirSync(dir, { recursive: true });
  const out: Record<string, string> = { ...themes };
  if (all_dismissed_at) out[ALL_DISMISSED_KEY] = all_dismissed_at;
  writeFileSync(fp, JSON.stringify(out, null, 2), "utf-8");
}

/** GET: return { all_dismissed_at: string | null, themes: { [id]: timestamp } } */
export async function GET() {
  const { all_dismissed_at, themes } = load();
  return NextResponse.json({ all_dismissed_at, themes });
}

/** POST: body { mark_all?: true } or { theme_ids?: number[] }. Returns same shape as GET. */
export async function POST(req: Request) {
  try {
    const body = (await req.json()) as { mark_all?: boolean; theme_ids?: unknown };
    const { all_dismissed_at: prevDismissed, themes } = load();
    const now = new Date().toISOString();

    if (body.mark_all === true) {
      // Also set per-theme timestamps if theme_ids are provided alongside mark_all.
      // This ensures themes with null last_updated are properly covered.
      const updatedThemes = { ...themes };
      if (Array.isArray(body.theme_ids)) {
        const ids = (body.theme_ids as unknown[])
          .map((x) => (typeof x === "number" ? x : typeof x === "string" ? Number(x) : NaN))
          .filter((x) => Number.isInteger(x) && x > 0);
        for (const id of ids) updatedThemes[String(id)] = now;
      }
      save(now, updatedThemes);
      return NextResponse.json({ all_dismissed_at: now, themes: updatedThemes });
    }

    const rawIds = Array.isArray(body?.theme_ids) ? body.theme_ids : [];
    const ids = rawIds
      .map((x) => (typeof x === "number" ? x : typeof x === "string" ? Number(x) : NaN))
      .filter((x) => Number.isInteger(x) && x > 0);
    if (ids.length === 0) {
      return NextResponse.json({ all_dismissed_at: prevDismissed, themes });
    }
    const nextThemes = { ...themes };
    for (const id of ids) nextThemes[String(id)] = now;
    const keys = Object.keys(nextThemes).filter((k) => k !== ALL_DISMISSED_KEY);
    if (keys.length > MAX_THEME_ENTRIES) {
      const entries = keys
        .map((k) => [k, nextThemes[k]] as const)
        .sort((a, b) => (b[1] < a[1] ? -1 : 1))
        .slice(0, MAX_THEME_ENTRIES);
      const trimmed: Record<string, string> = {};
      for (const [k, v] of entries) trimmed[k] = v;
      save(prevDismissed, trimmed);
      return NextResponse.json({ all_dismissed_at: prevDismissed, themes: trimmed });
    }
    save(prevDismissed, nextThemes);
    return NextResponse.json({ all_dismissed_at: prevDismissed, themes: nextThemes });
  } catch (e) {
    return NextResponse.json(
      { detail: e instanceof Error ? e.message : "Invalid request" },
      { status: 400 }
    );
  }
}
