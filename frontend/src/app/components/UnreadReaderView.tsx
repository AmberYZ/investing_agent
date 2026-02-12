"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ReaderThemeSection } from "./ReaderThemeSection";

type ThemeMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
};

type Theme = {
  id: number;
  canonical_label: string;
  description?: string | null;
  last_updated: string | null;
  is_new: boolean;
};

type ThemeMetricsByStance = {
  date: string;
  bullish_count: number;
  bearish_count: number;
  mixed_count: number;
  neutral_count: number;
  total_count: number;
};

type ThemeSubThemeDaily = {
  date: string;
  sub_theme: string;
  doc_count: number;
  mention_count: number;
};

type NarrativeSummaryData = {
  summary: string;
  trending_sub_themes?: string[];
  inflection_alert?: string | null;
};

type ThemeDocument = {
  id: number;
  filename: string;
  received_at: string;
  summary: string | null;
  narratives: { statement: string; stance: string; relation_to_prevailing: string }[];
  excerpts: string[];
};

type Narrative = {
  id: number;
  theme_id: number;
  statement: string;
  date_created?: string | null;
  first_seen?: string | null;
  last_seen?: string | null;
  sub_theme?: string | null;
  narrative_stance?: string | null;
  confidence_level?: string | null;
  evidence: { id: number; quote: string; page?: number | null; document_id: number }[];
};

type ThemeSectionData = {
  narrativeSummary: NarrativeSummaryData | null;
  metricsByStance: ThemeMetricsByStance[];
  metricsBySubTheme: ThemeSubThemeDaily[];
  documents: ThemeDocument[];
  narratives: Narrative[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const FETCH_TIMEOUT = 25000;

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    cache: "no-store",
    signal: AbortSignal.timeout(FETCH_TIMEOUT),
  });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export function UnreadReaderView({
  unreadThemes,
  metricsMap,
  months,
}: {
  unreadThemes: Theme[];
  metricsMap: Record<number, ThemeMetric[]>;
  months: number;
}) {
  const [sectionData, setSectionData] = useState<Record<number, ThemeSectionData>>({});
  const [loading, setLoading] = useState(true);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const sectionRefs = useRef<(HTMLElement | null)[]>([]);
  const narrativesStartRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Fetch batch narrative summaries, then per-theme data in parallel
  useEffect(() => {
    if (unreadThemes.length === 0) {
      setLoading(false);
      setSectionData({});
      return;
    }
    let cancelled = false;
    setLoading(true);
    const ids = unreadThemes.map((t) => t.id);
    const themeIdsParam = ids.join(",");

    const run = async () => {
      const summariesRes = await fetch(
        `${API_BASE}/themes/narrative-summaries?theme_ids=${encodeURIComponent(themeIdsParam)}`,
        { cache: "no-store", signal: AbortSignal.timeout(FETCH_TIMEOUT) }
      );
      const summariesMap: Record<string, NarrativeSummaryData> = summariesRes.ok
        ? await summariesRes.json()
        : {};

      const results = await Promise.allSettled(
        unreadThemes.map(async (theme) => {
          const [metricsByStance, metricsBySubTheme, documents, narratives] = await Promise.all([
            fetchJson<ThemeMetricsByStance[]>(
              `${API_BASE}/themes/${theme.id}/metrics-by-stance?months=${months}`
            ).catch(() => []),
            fetchJson<ThemeSubThemeDaily[]>(
              `${API_BASE}/themes/${theme.id}/metrics-by-sub-theme?months=${months}`
            ).catch(() => []),
            fetchJson<ThemeDocument[]>(`${API_BASE}/themes/${theme.id}/documents`).catch(() => []),
            fetchJson<Narrative[]>(`${API_BASE}/themes/${theme.id}/narratives`).catch(() => []),
          ]);
          return {
            themeId: theme.id,
            data: {
              narrativeSummary: summariesMap[String(theme.id)] ?? null,
              metricsByStance,
              metricsBySubTheme,
              documents,
              narratives,
            },
          };
        })
      );

      if (cancelled) return;
      const next: Record<number, ThemeSectionData> = {};
      results.forEach((r) => {
        if (r.status === "fulfilled") {
          next[r.value.themeId] = r.value.data;
        }
      });
      setSectionData(next);
      setLoading(false);
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [unreadThemes, months]);

  // j/k: move to next/previous theme and scroll so "Narratives" for that theme is in view
  const scrollToIndex = useCallback(
    (index: number) => {
      const i = Math.max(0, Math.min(index, unreadThemes.length - 1));
      setFocusedIndex(i);
      const narrativesEl = narrativesStartRefs.current[i];
      const sectionEl = sectionRefs.current[i];
      if (narrativesEl) {
        narrativesEl.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      if (sectionEl) {
        sectionEl.focus({ preventScroll: true });
      }
    },
    [unreadThemes.length]
  );

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (unreadThemes.length === 0) return;
      if (e.key === "j" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
        e.preventDefault();
        scrollToIndex(focusedIndex + 1);
      } else if (e.key === "k" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
        e.preventDefault();
        scrollToIndex(focusedIndex - 1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [unreadThemes.length, focusedIndex, scrollToIndex]);

  if (unreadThemes.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-8 text-center text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400">
        No unread themes. Switch to Grid or mark some themes unread.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-600 dark:border-t-zinc-300" />
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Loading reader…
        </p>
      </div>
    );
  }

  const total = unreadThemes.length;
  const current = Math.min(focusedIndex + 1, total);

  return (
    <div className="flex max-h-[calc(100vh-10rem)] flex-col overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
      {/* Progress indicator: sticky below Grid/Reader/Mark-all row, stays at top of this scroll area */}
      <div className="sticky top-0 z-10 flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            {current} of {total} unread themes
          </span>
          <div className="flex gap-1" aria-hidden>
            {unreadThemes.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => scrollToIndex(i)}
                className={`h-2 w-2 rounded-full transition-colors ${
                  i === focusedIndex
                    ? "bg-sky-500 dark:bg-sky-400"
                    : "bg-zinc-300 hover:bg-zinc-400 dark:bg-zinc-600 dark:hover:bg-zinc-500"
                }`}
                title={`Theme ${i + 1}`}
                aria-label={`Go to theme ${i + 1}`}
              />
            ))}
          </div>
        </div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Use <kbd className="rounded border border-zinc-300 px-1 dark:border-zinc-600">j</kbd> /{" "}
          <kbd className="rounded border border-zinc-300 px-1 dark:border-zinc-600">k</kbd> to move
          between themes.
        </p>
      </div>

      {/* Scrollable feed of theme sections */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-8 p-4">
        {unreadThemes.map((theme, i) => {
          const data = sectionData[theme.id];
          const metrics = metricsMap[theme.id] ?? [];
          return (
            <div
              key={theme.id}
              ref={(el) => {
                sectionRefs.current[i] = el;
              }}
              tabIndex={-1}
              className={`outline-none ring-offset-2 ${
                i === focusedIndex
                  ? "ring-2 ring-sky-500 dark:ring-sky-400 rounded-xl"
                  : ""
              }`}
            >
              <ReaderThemeSection
                theme={{
                  id: theme.id,
                  canonical_label: theme.canonical_label,
                  description: theme.description,
                }}
                narrativeSummary={data?.narrativeSummary ?? null}
                metrics={metrics}
                metricsByStance={data?.metricsByStance ?? []}
                metricsBySubTheme={data?.metricsBySubTheme ?? []}
                documents={data?.documents ?? []}
                narratives={data?.narratives ?? []}
                showUnreadBadge
                narrativesStartRef={(el) => {
                  narrativesStartRefs.current[i] = el;
                }}
              />
            </div>
          );
        })}
        </div>
      </div>
    </div>
  );
}
