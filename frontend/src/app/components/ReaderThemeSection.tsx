"use client";

import Link from "next/link";
import { ThemeChartAndDayDocs } from "../themes/[id]/ThemeChartAndDayDocs";
import { ThemeConfidenceChart } from "../themes/[id]/ThemeConfidenceChart";
import { ThemeStanceChart } from "../themes/[id]/ThemeStanceChart";
import { TodaysNarratives } from "../themes/[id]/TodaysNarratives";

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

  return (
    <section
      className="scroll-mt-24 rounded-xl border border-zinc-200 bg-zinc-50/50 dark:border-zinc-800 dark:bg-zinc-950/50"
      data-theme-id={theme.id}
    >
      {/* Sticky header bar */}
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            {theme.canonical_label}
          </h2>
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
        {/* Description */}
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {theme.description ?? "—"}
        </p>

        {/* Narrative summary */}
        <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            Narrative summary (past month)
          </h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            AI-generated summary. Updated daily.
          </p>
          {narrativeSummary?.summary ? (
            <>
              <div className="mt-3 whitespace-pre-line text-sm leading-relaxed text-zinc-700 dark:text-zinc-200">
                {narrativeSummary.summary.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
                  part.startsWith("**") && part.endsWith("**") ? (
                    <strong
                      key={i}
                      className="font-semibold text-zinc-900 dark:text-zinc-50"
                    >
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
                  <div className="mt-4">
                    <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                      Trending sub-themes
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {narrativeSummary.trending_sub_themes.map((st) => (
                        <span
                          key={st}
                          className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
                        >
                          {st}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              {hasExtendedSummary && narrativeSummary.inflection_alert && (
                <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100">
                  <div className="font-semibold text-amber-800 dark:text-amber-200">
                    Inflection alert
                  </div>
                  <p className="mt-1">{narrativeSummary.inflection_alert}</p>
                </div>
              )}
            </>
          ) : (
            <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
              No narratives yet for this theme in the past month.
            </p>
          )}
        </div>

        {/* Share of voice chart */}
        <div className="mt-6">
          <ThemeChartAndDayDocs
            metrics={metrics}
            metricsBySubTheme={metricsBySubTheme}
            documents={documents}
            themeId={themeId}
          />
        </div>

        {/* Narrative stance chart */}
        <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            Narrative stance over time
          </h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Percentage of narratives by stance (bullish / bearish / mixed / neutral).
          </p>
          <div className="mt-4">
            {metricsByStance.length > 0 ? (
              <ThemeStanceChart data={metricsByStance} />
            ) : (
              <div className="flex h-48 w-full items-center justify-center rounded border border-zinc-200 bg-zinc-50/50 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/30 dark:text-zinc-400">
                No stance data for this time range.
              </div>
            )}
          </div>
        </div>

        {/* Fact vs Opinion chart */}
        <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            Sentiment: Fact vs Opinion
          </h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Bullish / bearish / mixed / neutral breakdown of fact-based vs opinion-based narratives.
          </p>
          <div className="mt-4">
            <ThemeConfidenceChart themeId={themeId} />
          </div>
        </div>

        {/* Recent narratives — scroll target for j/k */}
        <div ref={narrativesStartRef} className="mt-6">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            Narratives
          </h3>
          <p className="mt-1 mb-4 text-xs text-zinc-500 dark:text-zinc-400">
            All narratives for this theme, newest first.
          </p>
          <TodaysNarratives narratives={narratives} />
        </div>
      </div>
    </section>
  );
}
