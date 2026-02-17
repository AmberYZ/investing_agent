"use client";

import Link from "next/link";
import { useState } from "react";
import { ThemeChartAndDayDocs } from "../themes/[id]/ThemeChartAndDayDocs";
import { ThemeConfidenceChart } from "../themes/[id]/ThemeConfidenceChart";
import { ThemeInstruments } from "../themes/[id]/ThemeInstruments";
import { ThemeStanceChart } from "../themes/[id]/ThemeStanceChart";
import { TodaysNarratives } from "../themes/[id]/TodaysNarratives";

const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function narrativesFromLastWeek(narratives: Narrative[]): Narrative[] {
  const cutoff = Date.now() - ONE_WEEK_MS;
  return narratives.filter((n) => {
    const d = n.last_seen ?? n.first_seen ?? n.date_created;
    if (!d) return false;
    return new Date(d).getTime() >= cutoff;
  });
}

type Evidence = {
  id: number;
  quote: string;
  page?: number | null;
  document_id: number;
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
  evidence: Evidence[];
};

type ThemeDailyMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
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

type Theme = {
  id: number;
  canonical_label: string;
  description?: string | null;
};

export function ReaderThemeSection({
  theme,
  narrativeSummary,
  metrics = [],
  metricsByStance = [],
  metricsBySubTheme = [],
  documents = [],
  narratives = [],
  showUnreadBadge = false,
  narrativesStartRef,
}: {
  theme: Theme;
  narrativeSummary: NarrativeSummaryData | null;
  metrics?: ThemeDailyMetric[];
  metricsByStance?: ThemeMetricsByStance[];
  metricsBySubTheme?: ThemeSubThemeDaily[];
  documents?: ThemeDocument[];
  narratives?: Narrative[];
  showUnreadBadge?: boolean;
  /** Ref for j/k scroll target: scroll to the Narratives section of this theme */
  narrativesStartRef?: (el: HTMLDivElement | null) => void;
}) {
  const themeId = String(theme.id);
  const hasExtendedSummary =
    narrativeSummary &&
    Array.isArray(narrativeSummary.trending_sub_themes) &&
    narrativeSummary.trending_sub_themes.length >= 0;
  const weekNarratives = narrativesFromLastWeek(narratives);
  const [summaryHover, setSummaryHover] = useState(false);

  return (
    <section
      className="scroll-mt-24 rounded-xl border border-zinc-200 bg-zinc-50/50 dark:border-zinc-800 dark:bg-zinc-950/50"
      data-theme-id={theme.id}
    >
      {/* Sticky header bar: title, narrative summary hover, unread badge, view full page */}
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            {theme.canonical_label}
          </h2>
          <div className="relative inline-block">
            <button
              type="button"
              onMouseEnter={() => setSummaryHover(true)}
              onMouseLeave={() => setSummaryHover(false)}
              onFocus={() => setSummaryHover(true)}
              onBlur={() => setSummaryHover(false)}
              className="text-xs font-medium text-zinc-500 underline decoration-dotted underline-offset-2 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-300"
            >
              Narrative summary (past month)
            </button>
            {summaryHover && narrativeSummary?.summary && (
              <div
                className="absolute left-0 top-full z-20 mt-1 max-h-64 w-96 overflow-y-auto rounded-lg border border-zinc-200 bg-white p-3 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
                onMouseEnter={() => setSummaryHover(true)}
                onMouseLeave={() => setSummaryHover(false)}
              >
                <div className="whitespace-pre-line text-xs leading-relaxed text-zinc-700 dark:text-zinc-200">
                  {narrativeSummary.summary.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
                    part.startsWith("**") && part.endsWith("**") ? (
                      <strong key={i} className="font-semibold text-zinc-900 dark:text-zinc-50">
                        {part.slice(2, -2)}
                      </strong>
                    ) : (
                      <span key={i}>{part}</span>
                    )
                  )}
                </div>
                {hasExtendedSummary &&
                  narrativeSummary.trending_sub_themes &&
                  narrativeSummary.trending_sub_themes.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {narrativeSummary.trending_sub_themes.map((st) => (
                        <span
                          key={st}
                          className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
                        >
                          {st}
                        </span>
                      ))}
                    </div>
                  )}
                {hasExtendedSummary && narrativeSummary.inflection_alert && (
                  <p className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-300">
                    Inflection: {narrativeSummary.inflection_alert}
                  </p>
                )}
              </div>
            )}
          </div>
          {showUnreadBadge && (
            <span
              className="rounded-full bg-amber-200 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900/60 dark:text-amber-200"
              aria-hidden
            >
              Unread
            </span>
          )}
        </div>
        <Link
          href={`/themes/${themeId}`}
          className="text-sm font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          View full page
        </Link>
      </div>

      <div className="p-4">
        {theme.description && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {theme.description}
          </p>
        )}

        {/* Narratives from the past week */}
        <div ref={narrativesStartRef} className="mt-4">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Narratives from the past week
          </h3>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            <Link href={`/themes/${themeId}`} className="text-sky-600 hover:underline dark:text-sky-400">View all narratives</Link>
          </p>
          <div className="mt-2">
            <TodaysNarratives narratives={weekNarratives} themeId={themeId} />
          </div>
        </div>

        {/* 2x2 grid: row1 = Share of voice | Narrative stance; row2 = Sentiment | Stock charts */}
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="min-w-0">
            <ThemeChartAndDayDocs
              metrics={metrics}
              metricsBySubTheme={metricsBySubTheme}
              documents={documents}
              themeId={themeId}
              compactLayout
            />
          </div>
          <div className="min-w-0 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              Narrative stance over time
            </h3>
            <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
              Bullish / bearish / mixed / neutral, stacked.
            </p>
            <div className="mt-3">
              {metricsByStance.length > 0 ? (
                <ThemeStanceChart data={metricsByStance} />
              ) : (
                <div className="flex h-40 w-full items-center justify-center rounded border border-zinc-200 bg-zinc-50/50 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
                  No stance data
                </div>
              )}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              Sentiment: Fact vs Opinion
            </h3>
            <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
              Fact vs opinion stance breakdown.
            </p>
            <div className="mt-3">
              <ThemeConfidenceChart themeId={themeId} />
            </div>
          </div>
          <div className="min-w-0">
            <ThemeInstruments themeId={themeId} compactLayout />
          </div>
        </div>
      </div>
    </section>
  );
}
