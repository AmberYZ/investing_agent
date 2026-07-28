"use client";

import Link from "next/link";
import { ThemeConfidenceChart } from "../themes/[id]/ThemeConfidenceChart";
import { ThemeInstruments } from "../themes/[id]/ThemeInstruments";
import { TodaysNarratives } from "../themes/[id]/TodaysNarratives";
import { NarrativeBriefing } from "../themes/[id]/NarrativeBriefing";

const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function narrativesFromLastWeek(narratives: Narrative[]): Narrative[] {
  const cutoff = Date.now() - ONE_WEEK_MS;
  return narratives
    .filter((n) => {
      const d = n.last_seen ?? n.first_seen ?? n.date_created;
      if (!d) return false;
      return new Date(d).getTime() >= cutoff;
    })
    .sort((a, b) => {
      const ta = new Date(a.last_seen ?? a.first_seen ?? a.date_created ?? 0).getTime();
      const tb = new Date(b.last_seen ?? b.first_seen ?? b.date_created ?? 0).getTime();
      return ta - tb;
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

type NarrativeSummaryData = {
  summary: string;
  investment_relevance?: string | null;
  what_changed?: string | null;
  change_narrative_ids?: number[];
  trending_sub_themes?: string[];
  inflection_alert?: string | null;
};

type Theme = {
  id: number;
  canonical_label: string;
  description?: string | null;
};

export function ReaderThemeSection({
  theme,
  narrativeSummary,
  narratives = [],
  showUnreadBadge = false,
  narrativesStartRef,
}: {
  theme: Theme;
  narrativeSummary: NarrativeSummaryData | null;
  narratives?: Narrative[];
  showUnreadBadge?: boolean;
  /** Ref for j/k scroll target: scroll to the Narratives section of this theme */
  narrativesStartRef?: (el: HTMLDivElement | null) => void;
}) {
  const themeId = String(theme.id);
  const weekNarratives = narrativesFromLastWeek(narratives);
  const changeIds = narrativeSummary?.change_narrative_ids ?? [];

  return (
    <section
      className="scroll-mt-24 rounded-xl border border-zinc-200 bg-zinc-50/50 dark:border-zinc-800 dark:bg-zinc-950/50"
      data-theme-id={theme.id}
    >
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
        {theme.description && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {theme.description}
          </p>
        )}

        <div className="mt-3">
          <NarrativeBriefing data={narrativeSummary} />
        </div>

        <div ref={narrativesStartRef} className="mt-4">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Narratives from the past week
          </h3>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            <Link href={`/themes/${themeId}`} className="text-sky-600 hover:underline dark:text-sky-400">View all narratives</Link>
            {" · Oldest → newest"}
            {changeIds.length > 0 ? " · Highlighted items drive the change signal" : ""}
          </p>
          <div className="mt-2">
            <TodaysNarratives
              narratives={weekNarratives}
              themeId={themeId}
              changeNarrativeIds={changeIds}
            />
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
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
