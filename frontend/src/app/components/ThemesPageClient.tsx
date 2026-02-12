"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import {
  fetchReadThemeDataFromAPI,
  getReadThemeData,
  setMarkAllReadAPI,
  READ_THEME_DATA_UPDATED_EVENT,
} from "../lib/read-themes";
import { ThemeCardGrid } from "./ThemeCardGrid";
import { UnreadReaderView } from "./UnreadReaderView";

const VIEW_MODE_KEY = "investing-agent-view-mode";
type ViewMode = "grid" | "reader";

type ThemeMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
  consensus_count: number;
  contrarian_count: number;
  refinement_count: number;
  new_angle_count: number;
};

type Theme = {
  id: number;
  canonical_label: string;
  description?: string | null;
  last_updated: string | null;
  is_new: boolean;
};

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const FETCH_TIMEOUT = 25000;

/**
 * Parse a date string as UTC.  Backend datetimes stored in SQLite lose their
 * timezone suffix, so JS `new Date()` would interpret "2026-02-10T12:30:00"
 * as *local* time instead of UTC.  We append "Z" when no timezone indicator is
 * present so comparisons with the always-UTC allDismissedAt / readAt are correct.
 */
function parseUTC(dateStr: string): number {
  if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(dateStr)) {
    return new Date(dateStr).getTime();
  }
  return new Date(dateStr + "Z").getTime();
}

/** 
 * Theme is considered "seen" only if:
 * - the user has read it *after* its latest update (readAt >= last_updated), OR
 * - "Mark all as read" was used and this theme's last_updated <= allDismissedAt.
 *
 * When last_updated is null/invalid we can't compare against allDismissedAt
 * (a time-based mechanism), so we only consider per-theme readAt.  This prevents
 * newly-appearing themes from being permanently suppressed once "Mark all as read"
 * has ever been clicked.
 */
function isSeen(
  t: Theme,
  readAt: string | undefined,
  allDismissedAt: string | null
): boolean {
  if (!t.last_updated) {
    // Without a last_updated timestamp we can't use allDismissedAt for comparison.
    // Only consider this theme "seen" if it was individually read.
    return !!readAt;
  }

  const lastUpdatedTime = parseUTC(t.last_updated);
  if (Number.isNaN(lastUpdatedTime)) {
    return !!readAt;
  }

  if (readAt) {
    const readTime = parseUTC(readAt);
    if (!Number.isNaN(readTime) && readTime >= lastUpdatedTime) {
      return true;
    }
  }

  if (allDismissedAt) {
    const allTime = parseUTC(allDismissedAt);
    if (!Number.isNaN(allTime) && lastUpdatedTime <= allTime) {
      return true;
    }
  }

  return false;
}

function hasUnread(
  t: Theme,
  readData: Record<number, string>,
  allDismissedAt: string | null
): boolean {
  const readAt = Number.isInteger(t.id) ? readData[t.id] : undefined;
  return !isSeen(t, readAt, allDismissedAt);
}

function MarkAllAsReadButton({
  themes,
  readData,
  allDismissedAt,
  onMarkAllRead,
}: {
  themes: Theme[];
  readData: Record<number, string>;
  allDismissedAt: string | null;
  onMarkAllRead: () => void | Promise<void>;
}) {
  const unreadCount = themes.filter((t) =>
    hasUnread(t, readData, allDismissedAt)
  ).length;
  const disabled = unreadCount === 0;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onMarkAllRead()}
      className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800"
    >
      Mark all as read
    </button>
  );
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    cache: "no-store",
    signal: AbortSignal.timeout(FETCH_TIMEOUT),
  });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

function getInitialViewMode(): ViewMode {
  if (typeof window === "undefined") return "grid";
  const v = window.localStorage.getItem(VIEW_MODE_KEY);
  return v === "reader" ? "reader" : "grid";
}

export function ThemesPageClient({ months }: { months: number }) {
  const [themes, setThemes] = useState<Theme[] | null>(null);
  const [contrarianThemes, setContrarianThemes] = useState<{ id: number; canonical_label: string }[]>([]);
  const [metricsMap, setMetricsMap] = useState<Record<number, ThemeMetric[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [readData, setReadData] = useState<Record<number, string>>({});
  const [allDismissedAt, setAllDismissedAt] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(() => getInitialViewMode());

  const refreshReadData = useCallback(() => {
    fetchReadThemeDataFromAPI(API_BASE)
      .then(({ all_dismissed_at, themes }) => {
        setAllDismissedAt(all_dismissed_at ?? null);
        setReadData(themes);
      })
      .catch(() => {
        setAllDismissedAt(null);
        setReadData(getReadThemeData());
      });
  }, []);

  useLayoutEffect(() => {
    refreshReadData();
  }, [refreshReadData]);

  useEffect(() => {
    window.addEventListener(READ_THEME_DATA_UPDATED_EVENT, refreshReadData);
    window.addEventListener("pageshow", refreshReadData);
    return () => {
      window.removeEventListener(READ_THEME_DATA_UPDATED_EVENT, refreshReadData);
      window.removeEventListener("pageshow", refreshReadData);
    };
  }, [refreshReadData]);

  const loadThemes = useCallback(async () => {
    setError(null);
    setThemes(null);
    setContrarianThemes([]);
    setMetricsMap({});
    try {
      const [themeList, contrarian] = await Promise.all([
        fetchJson<Theme[]>(`${API_BASE}/themes?sort=recent`),
        fetchJson<{ id: number; canonical_label: string }[]>(
          `${API_BASE}/themes/contrarian-recent?days=14`
        ),
      ]);
      setThemes(Array.isArray(themeList) ? themeList : []);
      setContrarianThemes(Array.isArray(contrarian) ? contrarian : []);
    } catch (e) {
      setError("Could not reach the backend. Is the API running on port 8000?");
      setThemes([]);
    }
  }, []);

  useEffect(() => {
    loadThemes();
  }, [loadThemes]);

  useEffect(() => {
    if (!themes || themes.length === 0) return;

    let cancelled = false;
    const run = async () => {
      const results = await Promise.allSettled(
        themes.map((t) =>
          fetchJson<ThemeMetric[]>(
            `${API_BASE}/themes/${t.id}/metrics?months=${months}`
          ).then((metrics) => ({ themeId: t.id, metrics }))
        )
      );
      if (cancelled) return;
      setMetricsMap((prev) => {
        const next = { ...prev };
        results.forEach((r) => {
          if (r.status === "fulfilled") {
            next[r.value.themeId] = r.value.metrics;
          }
        });
        return next;
      });
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [themes, months]);

  if (themes === null) {
    return (
      <div className="mt-8 flex flex-col items-center justify-center gap-4 rounded-xl border border-zinc-200 bg-white py-16 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-600 dark:border-t-zinc-300" />
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Loading themes…
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-8 rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
        {error}{" "}
        <button
          type="button"
          onClick={loadThemes}
          className="ml-2 font-medium underline hover:no-underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (themes.length === 0) {
    return (
      <div className="mt-8 rounded-xl border border-zinc-200 bg-white p-5 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
        No themes yet. Run the ingest client to upload some PDFs.
      </div>
    );
  }

  return (
    <>
      {(contrarianThemes ?? []).length > 0 && (
        <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50/80 p-4 dark:border-rose-800 dark:bg-rose-950/30">
          <div className="flex items-center gap-2">
            <span className="text-rose-600 dark:text-rose-400" aria-hidden>
              ◉
            </span>
            <span className="text-sm font-medium text-rose-800 dark:text-rose-200">
              Themes with recent contrarian narrative
            </span>
          </div>
          <p className="mt-1 text-xs text-rose-700/90 dark:text-rose-300/90">
            These themes had contrarian views in the last 14 days.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(contrarianThemes ?? []).map((t) => (
              <Link
                key={t.id}
                href={`/themes/${t.id}`}
                className="rounded-full bg-rose-100 px-3 py-1.5 text-xs font-medium text-rose-800 hover:bg-rose-200 dark:bg-rose-900/50 dark:text-rose-200 dark:hover:bg-rose-800"
              >
                {t.canonical_label}
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="mt-8">
        <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
          <div className="flex items-center gap-1 rounded-lg border border-zinc-300 bg-white p-0.5 dark:border-zinc-700 dark:bg-zinc-900">
            <button
              type="button"
              onClick={() => {
                setViewMode("grid");
                try {
                  window.localStorage.setItem(VIEW_MODE_KEY, "grid");
                } catch {}
              }}
              className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                viewMode === "grid"
                  ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                  : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              Grid
            </button>
            <button
              type="button"
              onClick={() => {
                setViewMode("reader");
                try {
                  window.localStorage.setItem(VIEW_MODE_KEY, "reader");
                } catch {}
              }}
              className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                viewMode === "reader"
                  ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100"
                  : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              Reader
            </button>
          </div>
          <MarkAllAsReadButton
            themes={themes}
            readData={readData}
            allDismissedAt={allDismissedAt}
            onMarkAllRead={async () => {
              try {
                const allIds = themes.map((t) => t.id);
                const { all_dismissed_at, themes: updatedThemes } =
                  await setMarkAllReadAPI(allIds);
                setAllDismissedAt(all_dismissed_at);
                setReadData(updatedThemes);
              } catch {
                setAllDismissedAt(new Date().toISOString());
              }
            }}
          />
        </div>
        {viewMode === "reader" ? (
          <UnreadReaderView
            unreadThemes={themes.filter((t) => hasUnread(t, readData, allDismissedAt))}
            metricsMap={metricsMap}
            months={months}
          />
        ) : (
          <ThemeCardGrid
            list={themes}
            metricsMap={metricsMap}
            readData={readData}
            allDismissedAt={allDismissedAt}
          />
        )}
      </div>
    </>
  );
}
