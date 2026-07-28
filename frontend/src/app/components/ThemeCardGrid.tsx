"use client";

import Link from "next/link";
import { useMemo } from "react";
import { FollowThemeButton } from "./FollowThemeButton";

type Theme = {
  id: number;
  canonical_label: string;
  description?: string | null;
  last_updated: string | null;
  is_new: boolean;
};

export function ThemeCardGrid({
  list,
  readData,
  allDismissedAt = null,
  followedIds = new Set<number>(),
  onFollowToggle,
}: {
  list: Theme[];
  /** @deprecated Kept optional for call-site compatibility; charts removed. */
  metricsMap?: unknown;
  readData: Record<number, string>;
  /** Single switch: when set, theme is "read" if last_updated <= this time. */
  allDismissedAt?: string | null;
  followedIds?: Set<number>;
  onFollowToggle?: (themeId: number, followed: boolean) => void;
}) {
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
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {sortedList.map((t) => {
        const themeId = Number(t.id);
        const readAt = Number.isInteger(themeId) ? readData[themeId] : undefined;
        const seen = isSeen(t, readAt);
        const hasRecentActivity = !seen;
        return (
          <Link
            key={t.id}
            href={`/themes/${t.id}`}
            className={`group relative rounded-lg border bg-white p-3 transition hover:bg-zinc-50 dark:bg-zinc-950 dark:hover:bg-zinc-900 ${
              hasRecentActivity
                ? "border-l-4 border-l-emerald-500 dark:border-l-emerald-400 border-zinc-200 dark:border-zinc-800"
                : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700"
            }`}
          >
            <div className="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
              {hasRecentActivity && (
                <span
                  className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400"
                  title="Unread"
                  aria-hidden
                />
              )}
              <FollowThemeButton
                themeId={themeId}
                followed={followedIds.has(themeId)}
                onToggle={onFollowToggle}
                variant="compact"
              />
            </div>
            <div className="flex items-center gap-2 pr-16">
              <div className="text-xs font-semibold leading-tight">{t.canonical_label}</div>
            </div>
            <div className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400 line-clamp-2 leading-snug">
              {t.description ?? "—"}
            </div>
            <div className="mt-2 text-[11px] text-zinc-500 dark:text-zinc-400">
              <span className="group-hover:text-zinc-700 dark:group-hover:text-zinc-200">
                View narratives →
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
