"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ThemeCardChart } from "./ThemeCardChart";

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

/** All unique dates across all themes, sorted, for normalized x-axis. */
function getAllDates(metricsMap: Record<number, ThemeMetric[]>): string[] {
  const set = new Set<string>();
  Object.values(metricsMap).forEach((metrics) => metrics.forEach((m) => set.add(m.date)));
  return Array.from(set).sort();
}

/** Fill theme metrics to the global date list so every chart shares the same x-axis. */
function normalizeThemeData(
  themeId: number,
  metrics: ThemeMetric[],
  allDates: string[]
): ThemeMetric[] {
  const byDate = new Map(metrics.map((m) => [m.date, m]));
  return allDates.map((date) => {
    const m = byDate.get(date);
    if (m) return m;
    return {
      theme_id: themeId,
      date,
      doc_count: 0,
      mention_count: 0,
      share_of_voice: null,
      consensus_count: 0,
      contrarian_count: 0,
      refinement_count: 0,
      new_angle_count: 0,
    };
  });
}

export function ThemeCardGrid({
  list,
  metricsMap,
  readData,
  allDismissedAt = null,
}: {
  list: Theme[];
  metricsMap: Record<number, ThemeMetric[]>;
  readData: Record<number, string>;
  /** Single switch: when set, theme is "read" if last_updated <= this time. */
  allDismissedAt?: string | null;
}) {
  const allDates = useMemo(() => getAllDates(metricsMap), [metricsMap]);

  /**
   * Parse a date string as UTC.  Backend datetimes stored in SQLite lose their
   * timezone suffix, so JS `new Date()` would interpret them as local time.
   * Append "Z" when no timezone indicator is present.
   */
  const parseUTC = (dateStr: string): number => {
    if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(dateStr)) {
      return new Date(dateStr).getTime();
    }
    return new Date(dateStr + "Z").getTime();
  };

  /**
   * Theme is "read" if:
   * - user opened it after its latest update (readAt >= last_updated), OR
   * - "Mark all as read" was used and this theme's last_updated <= allDismissedAt.
   *
   * When last_updated is null/invalid we can't compare against allDismissedAt,
   * so only per-theme readAt is used (prevents new themes from being permanently
   * suppressed once "Mark all as read" has been clicked).
   */
  const isSeen = (t: Theme, readAt: string | undefined): boolean => {
    if (!t.last_updated) {
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
  };

  const sortedList = useMemo(() => {
    return [...list].sort((a, b) => {
      const readAtA = Number.isInteger(Number(a.id)) ? readData[Number(a.id)] : undefined;
      const readAtB = Number.isInteger(Number(b.id)) ? readData[Number(b.id)] : undefined;
      const seenA = isSeen(a, readAtA);
      const seenB = isSeen(b, readAtB);
      const hasUnreadA = !seenA;
      const hasUnreadB = !seenB;
      if (hasUnreadA !== hasUnreadB) return hasUnreadA ? -1 : 1;
      const timeA = a.last_updated ? parseUTC(a.last_updated) : 0;
      const timeB = b.last_updated ? parseUTC(b.last_updated) : 0;
      return timeB - timeA;
    });
  }, [list, readData, allDismissedAt]);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {sortedList.map((t) => {
        const themeId = Number(t.id);
        const readAt = Number.isInteger(themeId) ? readData[themeId] : undefined;
        const seen = isSeen(t, readAt);
        const hasRecentActivity = !seen;
        return (
          <Link
            key={t.id}
            href={`/themes/${t.id}`}
            className={`group relative rounded-xl border bg-white p-5 transition hover:bg-zinc-50 dark:bg-zinc-950 dark:hover:bg-zinc-900 ${
              hasRecentActivity
                ? "border-l-4 border-l-emerald-500 dark:border-l-emerald-400 border-zinc-200 dark:border-zinc-800"
                : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700"
            }`}
          >
            {hasRecentActivity && (
              <span
                className="absolute right-3 top-3 h-2 w-2 rounded-full bg-emerald-500 dark:bg-emerald-400"
                title="Unread"
                aria-hidden
              />
            )}
            <div className="flex items-center gap-2">
              <div className="text-sm font-semibold">{t.canonical_label}</div>
            </div>
            <div className="mt-2 text-xs text-zinc-600 dark:text-zinc-400 line-clamp-3">
              {t.description ?? "—"}
            </div>
            <div className="mt-3">
              <ThemeCardChart
                id={t.id}
                data={normalizeThemeData(t.id, metricsMap[t.id] ?? [], allDates)}
              />
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
              <span className="group-hover:text-zinc-700 dark:group-hover:text-zinc-200">
                View narratives →
              </span>
              <span className="text-[10px]">share of voice</span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
