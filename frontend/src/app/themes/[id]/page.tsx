import Link from "next/link";
import { FollowThemeButtonWrapper } from "./FollowThemeButtonWrapper";
import { GroupThemeIntoParent } from "./GroupThemeIntoParent";
import { MarkThemeAsRead } from "./MarkThemeAsRead";
import { ThemePageRangeControls } from "./ThemePageRangeControls";
import { ThemeConfidenceChart } from "./ThemeConfidenceChart";
import { ThemeInstruments } from "./ThemeInstruments";
import { ThemeNotes } from "./ThemeNotes";
import { ThemeTrackItems } from "./ThemeTrackItems";
import { ThemeTrackedResultsBox } from "./ThemeTrackedResultsBox";
import { ThemeNarrativesClient } from "./ThemeNarrativesClient";
import { NarrativeBriefing } from "./NarrativeBriefing";

type ThemeDetail = {
  id: number;
  canonical_label: string;
  description?: string | null;
  last_updated?: string | null;
  parent_theme_id?: number | null;
  parent_theme_label?: string | null;
  child_theme_ids?: number[];
};

type ThemeDailyMetric = {
  theme_id: number;
  date: string;
  doc_count: number;
  mention_count: number;
  share_of_voice: number | null;
};

type NarrativeSummaryExtended = {
  summary: string;
  investment_relevance?: string | null;
  what_changed?: string | null;
  change_narrative_ids?: number[];
  trending_sub_themes?: string[];
  inflection_alert?: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Validated YYYY-MM-DD start for charts, or null. */
function parseChartStart(raw: string | undefined): string | null {
  if (!raw || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  const d = new Date(`${raw}T12:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  const end = new Date();
  end.setHours(23, 59, 59, 999);
  if (d > end) return null;
  const min = new Date();
  min.setFullYear(min.getFullYear() - 15);
  if (d < min) return null;
  return raw;
}

async function getTheme(id: string): Promise<ThemeDetail | null> {
  const res = await fetch(`${API_BASE}/themes/${id}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

async function getThemeMetrics(id: string, months: number, chartStartIso: string | null): Promise<ThemeDailyMetric[]> {
  const q = chartStartIso ? `start=${encodeURIComponent(chartStartIso)}` : `months=${months}`;
  const res = await fetch(`${API_BASE}/themes/${id}/metrics?${q}`, {
    cache: "no-store",
  });
  if (!res.ok) return [];
  return res.json();
}

async function getNarrativeSummary(id: string, period: "all" | "30d" = "30d"): Promise<NarrativeSummaryExtended | null> {
  const res = await fetch(`${API_BASE}/themes/${id}/narrative-summary?period=${period}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  return res.json();
}

function Sparkline({ data }: { data: number[] }) {
  if (data.length === 0) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const norm = max === min ? data.map(() => 0.5) : data.map((v) => (v - min) / (max - min));
  const width = 120;
  const height = 32;
  const step = data.length === 1 ? width : width / (data.length - 1);
  const points = norm
    .map((v, i) => {
      const x = i * step;
      const y = height - v * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-8 w-32 text-emerald-500 dark:text-emerald-400"
      aria-hidden="true"
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

export default async function ThemePage(
  props: {
    params: Promise<{ id: string }>;
    searchParams: Promise<{ months?: string; start?: string }>;
  }
) {
  const { id } = await props.params;
  const { months: monthsParam, start: startParam } = await props.searchParams;
  const months = monthsParam === "12" ? 12 : 6;
  const chartStartIso = parseChartStart(startParam);

  const [theme, narrativeSummary, metrics] = await Promise.all([
    getTheme(id),
    getNarrativeSummary(id, "30d"),
    getThemeMetrics(id, months, chartStartIso),
  ]);

  if (!theme) {
    return (
      <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
        <main className="mx-auto w-full max-w-5xl px-6 py-10">
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            <Link href="/" className="hover:underline">Themes</Link> / Theme not found
          </div>
          <p className="mt-4">This theme may have been removed or the link is invalid.</p>
        </main>
      </div>
    );
  }

  const sovSeries = (metrics ?? []).map((m) => {
    const sov = m.share_of_voice;
    if (sov == null) return 0;
    return sov <= 1 ? sov * 100 : sov;
  });

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <MarkThemeAsRead themeId={theme.id} themeLastUpdated={theme.last_updated ?? null} />
      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        <div className="flex flex-wrap items-stretch justify-between gap-6">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              <Link href="/" className="hover:underline">
                Themes
              </Link>{" "}
              / {theme.canonical_label}
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">
              {theme.canonical_label}
            </h1>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              {theme.description ?? "—"}
            </p>
            <div className="mt-3">
              <NarrativeBriefing data={narrativeSummary} compact />
            </div>
          </div>
          <div className="flex flex-col items-end justify-between gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <div className="flex flex-wrap items-center gap-2">
              <FollowThemeButtonWrapper themeId={theme.id} />
              <ThemeNotes themeId={id} />
              <ThemeTrackItems themeId={id} />
              <GroupThemeIntoParent
                themeId={theme.id}
                themeLabel={theme.canonical_label}
                parentThemeId={theme.parent_theme_id ?? undefined}
                parentThemeLabel={theme.parent_theme_label ?? undefined}
                childThemeIds={theme.child_theme_ids ?? []}
              />
            </div>
            <ThemePageRangeControls themeId={id} months={months} chartStartIso={chartStartIso} />
            {(metrics ?? []).length > 0 && (
              <div className="font-mono">
                {metrics[0].date} → {metrics[metrics.length - 1].date}
              </div>
            )}
            {sovSeries.length > 0 && (
              <div className="flex items-center gap-2">
                <Sparkline data={sovSeries} />
                <span className="text-[11px]">share of voice</span>
              </div>
            )}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-stretch">
          <div className="min-w-0 space-y-4">
            <ThemeTrackedResultsBox themeId={id} />
            <ThemeInstruments themeId={id} months={months} chartStartIso={chartStartIso} compactLayout />
            <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Sentiment: Fact vs Opinion
              </h2>
              <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
                Fact vs opinion stance breakdown.
              </p>
              <div className="mt-3">
                <ThemeConfidenceChart themeId={id} />
              </div>
            </section>
          </div>
          <div className="relative min-h-0 min-w-0 lg:h-full">
            <section className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950 lg:absolute lg:inset-0 lg:h-full">
              <div className="shrink-0 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
                <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                  Narratives
                </h2>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                  Newest dates first; within a document, reading order. Change-linked items are highlighted. Open original to view source; Reassign to move.
                </p>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3" data-narrative-scroll>
                <ThemeNarrativesClient
                  themeId={id}
                  themeLabel={theme.canonical_label}
                  changeNarrativeIds={narrativeSummary?.change_narrative_ids ?? []}
                />
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
