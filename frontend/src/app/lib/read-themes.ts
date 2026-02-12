const STORAGE_KEY = "investing-agent-read-theme-data";
const READ_DATA_UPDATED_EVENT = "investing-agent-read-theme-data-updated";
const MAX_ENTRIES = 200;

/** In-memory fallback so read state works even when localStorage is disabled or fails. */
let memoryCache: Record<number, string> = {};

/** Trim to MAX_ENTRIES but always keep entries for keepIds (so we never drop the theme we just marked). */
function trimReadDataKeeping(
  data: Record<number, string>,
  keepIds: Set<number>
): Record<string, string> {
  const entries = Object.entries(data);
  const keepKeys = new Set(keepIds.map(String));
  const other = entries.filter(([k]) => !keepKeys.has(k));
  const kept = other.slice(-Math.max(0, MAX_ENTRIES - keepIds.size));
  const justWritten = entries.filter(([k]) => keepKeys.has(k));
  const trimmed = Object.fromEntries([...kept, ...justWritten]);
  return trimmed as Record<string, string>;
}

/**
 * Returns themeId -> last_updated (ISO string) when the user last visited that theme.
 * Alert shows if theme has recent activity AND (never read OR theme's current last_updated > stored).
 */
export function getReadThemeData(): Record<number, string> {
  const out: Record<number, string> = {};
  if (typeof window !== "undefined") {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const obj = JSON.parse(raw) as unknown;
        if (obj && typeof obj === "object" && !Array.isArray(obj)) {
          for (const [k, v] of Object.entries(obj)) {
            const id = Number(k);
            if (Number.isInteger(id) && typeof v === "string") {
              out[id] = v;
              if (!(id in memoryCache)) memoryCache[id] = v;
            }
          }
        }
      }
    } catch {
      // ignore
    }
  }
  for (const [id, v] of Object.entries(memoryCache)) {
    const n = Number(id);
    if (Number.isInteger(n)) out[n] = v;
  }
  return out;
}

/**
 * Mark a theme as read. Store current time so "seen after update" always clears when you visit.
 */
export function markThemeAsRead(themeId: number, _themeLastUpdated?: string | null): void {
  const id = Number(themeId);
  if (!Number.isInteger(id)) return;
  const now = new Date().toISOString();
  memoryCache[id] = now;
  if (typeof window === "undefined") return;
  try {
    const data = getReadThemeData();
    data[id] = now;
    const trimmed = trimReadDataKeeping(data, new Set([id]));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    window.dispatchEvent(new CustomEvent(READ_DATA_UPDATED_EVENT));
  } catch {
    // ignore
  }
}

/**
 * Mark all given themes as read. Stores current time so "seen after update" comparison always clears.
 */
export function markAllThemesAsRead(
  themes: { id: number }[]
): void {
  const now = new Date().toISOString();
  const justWritten = new Set<number>();
  for (const t of themes) {
    const id = Number(t.id);
    if (Number.isInteger(id)) {
      memoryCache[id] = now;
      justWritten.add(id);
    }
  }
  if (typeof window === "undefined") return;
  try {
    const data = getReadThemeData();
    for (const id of justWritten) data[id] = now;
    const trimmed = trimReadDataKeeping(data, justWritten);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    window.dispatchEvent(new CustomEvent(READ_DATA_UPDATED_EVENT));
  } catch {
    // ignore
  }
}

export const READ_THEME_DATA_UPDATED_EVENT = READ_DATA_UPDATED_EVENT;

/** API response: one switch for "mark all", plus per-theme for single visits. */
export type ReadStatusResponse = {
  all_dismissed_at: string | null;
  themes: Record<number, string>;
};

function parseThemes(obj: unknown): Record<number, string> {
  const out: Record<number, string> = {};
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return out;
  for (const [k, v] of Object.entries(obj)) {
    const id = Number(k);
    if (Number.isInteger(id) && id > 0 && typeof v === "string") {
      out[id] = v;
      memoryCache[id] = v;
    }
  }
  return out;
}

const READ_STATUS_URL = "/api/themes/read-status";

/** Fetch read status: one "all dismissed" timestamp + per-theme. */
export async function fetchReadThemeDataFromAPI(_apiBase?: string): Promise<ReadStatusResponse> {
  const res = await fetch(READ_STATUS_URL, { cache: "no-store" });
  if (!res.ok) throw new Error(`read-status: ${res.status}`);
  const data = (await res.json()) as unknown;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { all_dismissed_at: null, themes: {} };
  }
  const o = data as Record<string, unknown>;
  const all_dismissed_at =
    typeof o.all_dismissed_at === "string" ? o.all_dismissed_at : null;
  const themes = parseThemes(o.themes);
  return { all_dismissed_at, themes };
}

/** Mark all as read: set single switch to now, optionally also mark individual theme IDs.
 *  Returns { all_dismissed_at, themes }. */
export async function setMarkAllReadAPI(
  themeIds?: number[]
): Promise<ReadStatusResponse> {
  const body: Record<string, unknown> = { mark_all: true };
  if (themeIds && themeIds.length > 0) body.theme_ids = themeIds;
  const res = await fetch(READ_STATUS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`read-status: ${res.status}`);
  const data = (await res.json()) as unknown;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("read-status: bad response");
  }
  const o = data as Record<string, unknown>;
  const at = typeof o.all_dismissed_at === "string" ? o.all_dismissed_at : null;
  if (!at) throw new Error("read-status: missing all_dismissed_at");
  const themes = parseThemes(o.themes);
  return { all_dismissed_at: at, themes };
}

/** Mark one theme as read (single card click). */
export async function markThemesReadAPI(
  _apiBase: string,
  themeIds: number[]
): Promise<ReadStatusResponse> {
  const ids = themeIds
    .map((id) => Number(id))
    .filter((id) => Number.isInteger(id) && id > 0);
  if (ids.length === 0) return fetchReadThemeDataFromAPI();
  const res = await fetch(READ_STATUS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme_ids: ids }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`read-status: ${res.status}`);
  const data = (await res.json()) as unknown;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { all_dismissed_at: null, themes: {} };
  }
  const o = data as Record<string, unknown>;
  const all_dismissed_at =
    typeof o.all_dismissed_at === "string" ? o.all_dismissed_at : null;
  const themes = parseThemes(o.themes);
  return { all_dismissed_at, themes };
}
